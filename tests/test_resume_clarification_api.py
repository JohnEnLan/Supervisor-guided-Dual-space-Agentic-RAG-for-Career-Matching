from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.state.schema import CareerState, SharedState


def _app() -> FastAPI:
    from app.api.auth.deps import require_owned_session
    from app.api.v1.router import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_owned_session] = lambda: None
    return app


def _targets() -> list[dict]:
    return [
        {
            "target_ref": "experience[0]",
            "field_path": "experience[0]",
            "status": "open",
            "severity": "high",
            "issue": "缺少职责与成果",
            "evidence_span_ids": ["R001"],
        },
        {
            "target_ref": "projects[0]",
            "field_path": "projects[0]",
            "status": "open",
            "severity": "medium",
            "issue": "缺少技术关联",
            "evidence_span_ids": ["R002"],
        },
    ]


def _state(*, rounds: int = 0, questions_used: int = 0) -> SharedState:
    return SharedState(
        session_id="session-1",
        user_id="user-1",
        career_state=CareerState(
            current_goal=["Data analyst"],
            hard_constraints={
                "locations": ["Birmingham"],
                "need_visa_sponsor": False,
            },
            soft_preferences={"title_keywords": ["data"]},
            avoid_roles=["Sales"],
            consult_rounds_used=rounds,
        ),
        resume_state={
            "normalized_base_resume": "IMMUTABLE BASE",
            "original_evidence_spans": [
                {"span_id": "R001", "text": "Acme 数据接口开发"},
                {"span_id": "R002", "text": "Career RAG 项目"},
            ],
            "clarification_targets": _targets(),
            "questions_used": questions_used,
        },
    )


def _context(state: SharedState, *, version: int = 4, generation: int = 9):
    from app.db.state_store import ConsultContext

    return ConsultContext(
        state=state.model_copy(deep=True),
        status="resume_ready",
        resume_version=version,
        confirmed_resume_version=version,
        resume_upload_generation=generation,
    )


def test_get_consult_assembles_real_clarification_progress(monkeypatch) -> None:
    from app.api.v1 import sessions

    state = _state(rounds=3, questions_used=2)
    state.resume_state.clarification_targets[0]["status"] = "answered"
    state.resume_state.clarification_targets[1]["status"] = "skipped"

    async def load(_session_id):
        return state

    monkeypatch.setattr(sessions.settings, "resume_clarify_enabled", True)
    monkeypatch.setattr(sessions, "load_state", load)

    with TestClient(_app()) as client:
        response = client.get("/api/v1/sessions/session-1/consult")

    assert response.status_code == 200
    assert response.json()["clarification_progress"] == {
        "answered": 1,
        "skipped": 1,
        "total": 2,
        "questions_used": 2,
    }


def test_consult_answer_creates_server_owned_c_span_and_composite_record(
    monkeypatch,
) -> None:
    from app.agents.consult_engine import ConsultTurn
    from app.api.v1 import sessions

    initial = _state(rounds=1, questions_used=1)
    initial.resume_state.pending_clarification_question = {
        "target_ref": "experience[0]",
        "asked_round": 1,
        "baseline_version": 4,
    }
    persisted = {}

    async def load_context(_session_id):
        return _context(initial)

    async def run(working, *, resume_version, **_kwargs):
        assert resume_version == 4
        working.resume_state.clarification_targets[0]["status"] = "answered"
        working.resume_state.questions_used = 2
        working.resume_state.pending_clarification_question = {
            "target_ref": "projects[0]",
            "asked_round": 2,
            "baseline_version": 4,
        }
        working.career_state.consult_rounds_used = 2
        working.career_state.consult_transcript.append(
            {
                "round": 2,
                "user_message": "我负责 Python API 开发",
                "assistant_reply": "收到。",
                "next_question": "项目用了哪些技术？",
                "phase": "resume_clarify",
            }
        )
        return ConsultTurn(
            assistant_reply="收到。",
            next_question="项目用了哪些技术？",
            phase="resume_clarify",
            completeness=0.7,
            can_finalize=True,
            round=2,
            profile_draft={},
            pending_clarification_at_round_start=True,
            issued_clarification_question=True,
            clarification_target_refs=("experience[0]",),
            clarification_action="answered",
            clarification_raw_answer="不得信任的内部伪造文本",
            clarification_answer_summary="负责 Python API 开发",
        )

    async def mutate(*, mutator, **_kwargs):
        latest = initial.model_copy(deep=True)
        result = mutator(latest, 4, 9)
        persisted["state"] = latest
        return result

    monkeypatch.setattr(sessions.settings, "resume_clarify_enabled", True)
    monkeypatch.setattr(sessions, "load_consult_context", load_context)
    monkeypatch.setattr(sessions, "run_consult_round", run)
    monkeypatch.setattr(sessions, "mutate_state_atomically", mutate)

    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/sessions/session-1/consult",
            json={
                "mode": "targeted",
                "message": "我负责 Python API 开发",
                "expected_round": 1,
            },
        )

    assert response.status_code == 200
    assert response.json()["clarification_progress"] == {
        "answered": 1,
        "skipped": 0,
        "total": 2,
        "questions_used": 2,
    }
    resume = persisted["state"].resume_state
    assert resume.clarification_evidence_spans == [
        {
            "span_id": "C001",
            "page": None,
            "text": "我负责 Python API 开发",
            "source": "user_clarification",
        }
    ]
    assert resume.clarifications == [
        {
            "target_ref": "experience[0]",
            "answer_summary": "负责 Python API 开发",
            "span_id": "C001",
            "round": 2,
            "action": "answered",
        }
    ]
    assert resume.normalized_base_resume == "IMMUTABLE BASE"
    assert [span["span_id"] for span in resume.original_evidence_spans] == [
        "R001",
        "R002",
    ]


def test_answer_without_pending_anchor_cannot_create_clarification_evidence(
    monkeypatch,
) -> None:
    from app.agents.consult_engine import ConsultTurn
    from app.api.v1 import sessions

    initial = _state()
    persisted = {}

    async def load_context(_session_id):
        return _context(initial)

    async def run(working, **_kwargs):
        working.career_state.consult_rounds_used = 1
        return ConsultTurn(
            assistant_reply="收到。",
            next_question="请补充第一段经历。",
            phase="resume_clarify",
            completeness=0.7,
            can_finalize=True,
            round=1,
            profile_draft={},
            clarification_target_refs=("experience[0]",),
            clarification_action="answered",
            clarification_raw_answer="模板阶段的回答",
            clarification_answer_summary="模板阶段的回答",
        )

    async def mutate(*, mutator, **_kwargs):
        latest = initial.model_copy(deep=True)
        result = mutator(latest, 4, 9)
        persisted["state"] = latest
        return result

    monkeypatch.setattr(sessions.settings, "resume_clarify_enabled", True)
    monkeypatch.setattr(sessions, "load_consult_context", load_context)
    monkeypatch.setattr(sessions, "run_consult_round", run)
    monkeypatch.setattr(sessions, "mutate_state_atomically", mutate)

    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/sessions/session-1/consult",
            json={"mode": "targeted", "message": "回答", "expected_round": 0},
        )

    assert response.status_code == 200
    assert persisted["state"].resume_state.clarifications == []
    assert persisted["state"].resume_state.clarification_evidence_spans == []


def test_feature_a_append_only_merge_is_idempotent_with_explicit_keys() -> None:
    from app.api.v1.sessions import _merge_feature_a_resume_state

    latest = _state().resume_state
    incoming = latest.model_copy(deep=True)
    incoming.clarification_evidence_spans.append(
        {
            "span_id": "C001",
            "page": None,
            "text": "原话",
            "source": "user_clarification",
        }
    )
    incoming.clarifications.append(
        {
            "target_ref": "experience[0]",
            "answer_summary": "原话",
            "span_id": "C001",
            "round": 2,
            "action": "answered",
        }
    )

    _merge_feature_a_resume_state(latest, incoming)
    _merge_feature_a_resume_state(latest, incoming)

    assert [item["span_id"] for item in latest.clarification_evidence_spans] == [
        "C001"
    ]
    assert [
        (item["target_ref"], item["round"]) for item in latest.clarifications
    ] == [("experience[0]", 2)]


def test_replayed_answer_record_does_not_allocate_a_second_span() -> None:
    from app.api.v1.sessions import _record_clarification_turn

    resume = _state().resume_state
    pending = {
        "target_ref": "experience[0]",
        "asked_round": 1,
        "baseline_version": 4,
    }
    turn = SimpleNamespace(
        round=2,
        clarification_action="answered",
        clarification_target_refs=("experience[0]",),
        clarification_answer_summary="负责 Python API 开发",
    )

    for _attempt in range(2):
        _record_clarification_turn(
            resume,
            turn=turn,
            pending_at_round_start=pending,
            raw_answer="我负责 Python API 开发",
        )

    assert [item["span_id"] for item in resume.clarification_evidence_spans] == [
        "C001"
    ]
    assert len(resume.clarifications) == 1


def test_invalid_summary_persists_none_while_projection_uses_raw(
    monkeypatch,
) -> None:
    from app.api.v1.sessions import _record_clarification_turn
    from app.config import settings
    from app.state.resume_view import effective_resume_text

    monkeypatch.setattr(settings, "resume_clarify_enabled", True)
    resume = _state().resume_state
    pending = {
        "target_ref": "experience[0]",
        "asked_round": 1,
        "baseline_version": 4,
    }
    turn = SimpleNamespace(
        round=2,
        clarification_action="answered",
        clarification_target_refs=("experience[0]",),
        clarification_answer_summary=None,
    )

    _record_clarification_turn(
        resume,
        turn=turn,
        pending_at_round_start=pending,
        raw_answer="我负责 Python API 开发",
    )

    assert resume.clarifications[0]["answer_summary"] is None
    assert "我负责 Python API 开发" in effective_resume_text(resume)


def test_finalize_atomically_skips_remaining_targets_and_clears_pending(
    monkeypatch,
) -> None:
    from app.api.v1 import sessions

    database_state = _state(rounds=1, questions_used=1)
    database_state.resume_state.pending_clarification_question = {
        "target_ref": "experience[0]",
        "asked_round": 1,
        "baseline_version": 4,
    }

    async def load_context(_session_id):
        return _context(database_state)

    async def mutate(*, mutator, **_kwargs):
        return mutator(database_state, 4, 9)

    monkeypatch.setattr(sessions.settings, "resume_clarify_enabled", True)
    monkeypatch.setattr(sessions, "load_consult_context", load_context)
    monkeypatch.setattr(sessions, "mutate_state_atomically", mutate)

    with TestClient(_app()) as client:
        response = client.post("/api/v1/sessions/session-1/consult/finalize")

    assert response.status_code == 200
    assert [
        target["status"]
        for target in database_state.resume_state.clarification_targets
    ] == ["skipped", "skipped"]
    assert database_state.resume_state.pending_clarification_question is None


def test_match_brief_lock_path_skips_remaining_targets(monkeypatch) -> None:
    from app.api.v1 import sessions

    database_state = _state(rounds=1, questions_used=1)
    database_state.resume_state.pending_clarification_question = {
        "target_ref": "experience[0]",
        "asked_round": 1,
        "baseline_version": 4,
    }

    async def metadata(_session_id):
        return {
            "exists": True,
            "resume_version": 4,
            "confirmed_resume_version": 4,
            "resume_upload_generation": 9,
        }

    async def mutate(*, mutator, **_kwargs):
        return mutator(database_state, 4, 9)

    async def create_run(**_kwargs):
        return SimpleNamespace(run_id="run-1")

    async def noop(**_kwargs):
        return None

    monkeypatch.setattr(sessions.settings, "resume_clarify_enabled", True)
    monkeypatch.setattr(sessions, "get_resume_metadata", metadata)
    monkeypatch.setattr(sessions, "mutate_state_atomically", mutate)
    monkeypatch.setattr(sessions, "create_run", create_run)
    monkeypatch.setattr(sessions, "save_match_brief", noop)

    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/sessions/session-1/match-brief",
            json={"career_goal": "Data analyst", "result_count": 5},
        )

    assert response.status_code == 201
    assert [
        target["status"]
        for target in database_state.resume_state.clarification_targets
    ] == ["skipped", "skipped"]
    assert database_state.resume_state.pending_clarification_question is None


@pytest.mark.asyncio
async def test_finalize_during_llm_wait_makes_consult_cas_409_without_resurrection(
    monkeypatch,
) -> None:
    from app.agents.consult_engine import ConsultTurn
    from app.api.v1 import sessions

    database_state = _state(rounds=1, questions_used=1)
    database_state.resume_state.pending_clarification_question = {
        "target_ref": "experience[0]",
        "asked_round": 1,
        "baseline_version": 4,
    }
    llm_started = asyncio.Event()
    allow_llm_to_finish = asyncio.Event()

    async def load_context(_session_id):
        return _context(database_state)

    async def run(working, **_kwargs):
        llm_started.set()
        await allow_llm_to_finish.wait()
        working.resume_state.clarification_targets[0]["status"] = "answered"
        working.resume_state.pending_clarification_question = None
        working.career_state.consult_rounds_used = 2
        return ConsultTurn(
            assistant_reply="收到。",
            next_question="下一步？",
            phase="resume_clarify",
            completeness=0.7,
            can_finalize=True,
            round=2,
            profile_draft={},
            pending_clarification_at_round_start=True,
            clarification_target_refs=("experience[0]",),
            clarification_action="answered",
            clarification_raw_answer="补充内容",
            clarification_answer_summary="补充内容",
        )

    async def mutate(*, mutator, **_kwargs):
        return mutator(database_state, 4, 9)

    monkeypatch.setattr(sessions.settings, "resume_clarify_enabled", True)
    monkeypatch.setattr(sessions, "load_consult_context", load_context)
    monkeypatch.setattr(sessions, "run_consult_round", run)
    monkeypatch.setattr(sessions, "mutate_state_atomically", mutate)

    in_flight = asyncio.create_task(
        sessions._execute_consult_round(
            session_id="session-1",
            mode="targeted",
            message="补充内容",
            expected_round=1,
            status="intent_consulting",
        )
    )
    await llm_started.wait()
    await sessions.finalize_consultation("session-1")
    allow_llm_to_finish.set()

    with pytest.raises(HTTPException) as conflict:
        await in_flight

    assert conflict.value.status_code == 409
    assert [
        target["status"]
        for target in database_state.resume_state.clarification_targets
    ] == ["skipped", "skipped"]
    assert database_state.resume_state.pending_clarification_question is None
    assert database_state.resume_state.clarification_evidence_spans == []


@pytest.mark.asyncio
async def test_clarification_round_rejects_202_generation_change_without_any_write(
    monkeypatch,
) -> None:
    from app.agents.consult_engine import ConsultTurn
    from app.api.v1 import sessions

    initial = _state(rounds=1, questions_used=1)
    initial.resume_state.pending_clarification_question = {
        "target_ref": "experience[0]",
        "asked_round": 1,
        "baseline_version": 4,
    }
    before = initial.model_dump()
    llm_started = asyncio.Event()
    allow_llm_to_finish = asyncio.Event()
    current_generation = 9

    async def load_context(_session_id):
        return _context(initial)

    async def run(working, **_kwargs):
        llm_started.set()
        await allow_llm_to_finish.wait()
        working.resume_state.clarification_targets[0]["status"] = "answered"
        working.resume_state.pending_clarification_question = None
        working.career_state.consult_rounds_used = 2
        return ConsultTurn(
            assistant_reply="收到。",
            next_question="下一步？",
            phase="deepen",
            completeness=0.7,
            can_finalize=True,
            round=2,
            profile_draft={},
            pending_clarification_at_round_start=True,
            clarification_target_refs=("experience[0]",),
            clarification_action="answered",
            clarification_raw_answer="补充内容",
            clarification_answer_summary="补充内容",
        )

    async def mutate(*, mutator, **_kwargs):
        return mutator(initial, 4, current_generation)

    monkeypatch.setattr(sessions.settings, "resume_clarify_enabled", True)
    monkeypatch.setattr(sessions, "load_consult_context", load_context)
    monkeypatch.setattr(sessions, "run_consult_round", run)
    monkeypatch.setattr(sessions, "mutate_state_atomically", mutate)

    in_flight = asyncio.create_task(
        sessions._execute_consult_round(
            session_id="session-1",
            mode="targeted",
            message="补充",
            expected_round=1,
            status="intent_consulting",
        )
    )
    await llm_started.wait()
    current_generation = 10
    allow_llm_to_finish.set()

    with pytest.raises(HTTPException) as conflict:
        await in_flight

    assert conflict.value.status_code == 409
    assert conflict.value.detail == "resume_changed"
    assert initial.model_dump() == before


@pytest.mark.asyncio
async def test_stale_pending_baseline_is_rejected_before_llm(monkeypatch) -> None:
    from app.api.v1 import sessions

    state = _state(rounds=1, questions_used=1)
    state.resume_state.pending_clarification_question = {
        "target_ref": "experience[0]",
        "asked_round": 1,
        "baseline_version": 3,
    }
    calls = 0

    async def load_context(_session_id):
        return _context(state)

    async def run(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("stale pending must not reach the LLM")

    monkeypatch.setattr(sessions.settings, "resume_clarify_enabled", True)
    monkeypatch.setattr(sessions, "load_consult_context", load_context)
    monkeypatch.setattr(sessions, "run_consult_round", run)

    with pytest.raises(HTTPException) as conflict:
        await sessions._execute_consult_round(
            session_id="session-1",
            mode="targeted",
            message="补充",
            expected_round=1,
            status="intent_consulting",
        )

    assert conflict.value.status_code == 409
    assert conflict.value.detail == "resume_changed"
    assert calls == 0


def test_clarify_only_switch_runs_question_answer_skip_finalize_flow(
    monkeypatch,
) -> None:
    from app.agents import consult_engine
    from app.api.v1 import sessions

    database_state = _state()
    responses = iter(
        [
            {
                "assistant_reply": "我想先补充第一段经历。",
                "next_question": "在 Acme 具体负责了什么？",
                "profile_updates": {},
                "phase_suggestion": "resume_clarify",
            },
            {
                "assistant_reply": "这段职责很清楚。",
                "next_question": "Career RAG 用了哪些技术？",
                "profile_updates": {},
                "phase_suggestion": "resume_clarify",
                "answer_summary": "负责 Python API 开发",
                "clarification_action": "answered",
            },
            {
                "assistant_reply": "没问题，我们继续职业偏好。",
                "next_question": "接下来更偏好哪类团队？",
                "profile_updates": {},
                "phase_suggestion": "deepen",
            },
        ]
    )

    async def chat(*_args, **_kwargs):
        return json.dumps(next(responses), ensure_ascii=False)

    async def load_context(_session_id):
        return _context(database_state)

    async def load_state(_session_id):
        return database_state.model_copy(deep=True)

    async def mutate(*, mutator, **_kwargs):
        return mutator(database_state, 4, 9)

    monkeypatch.setattr(sessions.settings, "resume_clarify_enabled", True)
    monkeypatch.setattr(sessions.settings, "consult_coach_enabled", False)
    monkeypatch.setattr(sessions.settings, "resume_clarify_max", 2)
    monkeypatch.setattr(consult_engine.settings, "resume_clarify_enabled", True)
    monkeypatch.setattr(consult_engine.settings, "resume_clarify_max", 2)
    monkeypatch.setattr(consult_engine.deepseek, "chat", chat)
    monkeypatch.setattr(sessions, "load_consult_context", load_context)
    monkeypatch.setattr(sessions, "load_state", load_state)
    monkeypatch.setattr(sessions, "mutate_state_atomically", mutate)

    with TestClient(_app()) as client:
        first = client.post(
            "/api/v1/sessions/session-1/consult",
            json={"mode": "targeted", "message": "开始", "expected_round": 0},
        )
        answered = client.post(
            "/api/v1/sessions/session-1/consult",
            json={
                "mode": "targeted",
                "message": "我负责 Python API 开发",
                "expected_round": 1,
            },
        )
        skipped = client.post(
            "/api/v1/sessions/session-1/consult",
            json={"mode": "targeted", "message": "跳过", "expected_round": 2},
        )
        finalized = client.post("/api/v1/sessions/session-1/consult/finalize")

    assert first.status_code == answered.status_code == skipped.status_code == 200
    assert finalized.status_code == 200
    assert first.json()["phase"] == "resume_clarify"
    assert answered.json()["clarification_progress"]["answered"] == 1
    assert skipped.json()["clarification_progress"] == {
        "answered": 1,
        "skipped": 1,
        "total": 2,
        "questions_used": 2,
    }
    assert skipped.json()["phase"] == "deepen"
    assert database_state.resume_state.pending_clarification_question is None
    assert database_state.resume_state.clarification_evidence_spans[0]["span_id"] == (
        "C001"
    )
