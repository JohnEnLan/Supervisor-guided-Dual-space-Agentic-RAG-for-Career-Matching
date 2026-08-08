from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.state.schema import CareerState, ResumeState, SharedState


def _api_app() -> FastAPI:
    from app.api.auth.deps import require_owned_session
    from app.api.v1.router import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_owned_session] = lambda: None
    return app


def _state(*, rounds: int = 1, complete: bool = False) -> SharedState:
    career = CareerState(
        current_goal=["Data analyst"],
        hard_constraints=(
            {"locations": ["Birmingham"], "need_visa_sponsor": False}
            if complete
            else {}
        ),
        consult_rounds_used=rounds,
        consult_transcript=[
            {
                "round": index,
                "user_message": f"user-{index}",
                "assistant_reply": f"assistant-{index}",
                "next_question": f"question-{index}",
                "phase": "template",
            }
            for index in range(1, rounds + 1)
        ],
    )
    return SharedState(
        session_id="session-1",
        user_id="user-1",
        career_state=career,
    )


def _l1(
    *,
    round_number: int = 2,
    phase: str = "template",
    streak: int = 0,
    can_finalize: bool = False,
    clarification_turn_active: bool = False,
) -> dict:
    return {
        "stage": "consult_coach_l1",
        "round": round_number,
        "phase": phase,
        "slot_gaps": [],
        "completeness_before": 0.2,
        "completeness": 0.2,
        "completeness_delta": 0.0,
        "stagnation_streak": streak,
        "clarification_progress": {
            "answered": 0,
            "skipped": 0,
            "total": 0,
            "questions_used": 0,
        },
        "clarification_turn_active": clarification_turn_active,
        "can_finalize": can_finalize,
        "coach_budget_remaining": 3,
    }


def _reservation(
    attempt_id: str = "attempt-1",
    *,
    round_number: int = 1,
    trigger: str = "deepen_entry",
    status: str = "reserved",
) -> dict:
    return {
        "coach_attempt_id": attempt_id,
        "round": round_number,
        "trigger": trigger,
        "status": status,
    }


def _note(
    attempt_id: str = "attempt-1",
    *,
    trigger: str = "deepen_entry",
) -> dict:
    return {
        "kind": "coach",
        "trigger": trigger,
        "text": "方向已经明确，下一轮补充岗位取舍依据。",
        "verdict": "advise",
        "coach_attempt_id": attempt_id,
    }


def test_l1_evaluation_persists_all_deterministic_facts() -> None:
    from app.agents.consult_coach import evaluate_consult_l1

    state = _state(rounds=1)
    state.supervisor_log.append(
        {
            "stage": "consult_coach_l1",
            "round": 1,
            "stagnation_streak": 1,
        }
    )

    facts = evaluate_consult_l1(
        state,
        round_number=2,
        phase="template",
        completeness_before=0.2,
        completeness=0.2,
        can_finalize=False,
        clarification_turn_active=False,
        clarification_progress={
            "answered": 1,
            "skipped": 0,
            "total": 2,
            "questions_used": 1,
        },
        coach_max=3,
    )

    assert facts == {
        "stage": "consult_coach_l1",
        "round": 2,
        "phase": "template",
        "slot_gaps": ["locations_or_remote", "need_visa_sponsor"],
        "completeness_before": 0.2,
        "completeness": 0.2,
        "completeness_delta": 0.0,
        "stagnation_streak": 2,
        "clarification_progress": {
            "answered": 1,
            "skipped": 0,
            "total": 2,
            "questions_used": 1,
        },
        "clarification_turn_active": False,
        "can_finalize": False,
        "coach_budget_remaining": 3,
    }


def test_l1_stagnation_streak_pauses_on_clarification_turn() -> None:
    """G18 用户裁决：澄清轮暂停停滞计数（保留前值），不清零。"""
    from app.agents.consult_coach import evaluate_consult_l1

    state = _state(rounds=1)
    state.supervisor_log.append(
        {
            "stage": "consult_coach_l1",
            "round": 1,
            "stagnation_streak": 1,
        }
    )

    facts = evaluate_consult_l1(
        state,
        round_number=2,
        phase="resume_clarify",
        completeness_before=0.2,
        completeness=0.2,
        can_finalize=False,
        clarification_turn_active=True,
        clarification_progress={},
        coach_max=3,
    )

    assert facts["stagnation_streak"] == 1


@pytest.mark.parametrize(
    ("facts", "targets", "expected"),
    [
        (_l1(phase="deepen"), [], "deepen_entry"),
        (_l1(streak=2), [], "stagnation"),
        (_l1(phase="deepen", can_finalize=True), [], "finalizable"),
        (
            _l1(phase="explore", can_finalize=True),
            [{"target_ref": "T1", "status": "open"}],
            None,
        ),
        (
            _l1(phase="explore", can_finalize=True),
            [
                {"target_ref": "T1", "status": "answered"},
                {"target_ref": "T2", "status": "skipped"},
            ],
            "finalizable",
        ),
        (_l1(streak=2, clarification_turn_active=True), [], None),
    ],
)
def test_trigger_matrix_is_deterministic(
    monkeypatch,
    facts,
    targets,
    expected,
) -> None:
    from app.agents.consult_coach import select_coach_trigger
    from app.config import settings

    monkeypatch.setattr(settings, "resume_clarify_enabled", True)
    state = _state(rounds=1)
    state.resume_state.clarification_targets = targets

    assert select_coach_trigger(state, facts, coach_max=3) == expected


def test_rollback_11_to_01_treats_stale_clarification_targets_as_exhausted(
    monkeypatch,
) -> None:
    from app.agents import consult_coach
    from app.config import settings

    state = _state(rounds=1, complete=True)
    state.resume_state.clarification_targets = [
        {"target_ref": "experience[0]", "status": "open"}
    ]
    facts = _l1(round_number=2, phase="explore", can_finalize=True)

    monkeypatch.setattr(settings, "resume_clarify_enabled", True)
    assert consult_coach.select_coach_trigger(state, facts, coach_max=3) is None

    monkeypatch.setattr(settings, "resume_clarify_enabled", False)
    assert (
        consult_coach.select_coach_trigger(state, facts, coach_max=3)
        == "finalizable"
    )


def test_trigger_priority_and_deepen_state_detection_prevent_starvation() -> None:
    from app.agents.consult_coach import select_coach_trigger

    state = _state(rounds=4, complete=True)
    state.coach_reservations.append(
        _reservation(
            "final",
            round_number=3,
            trigger="finalizable",
            status="succeeded",
        )
    )
    facts = _l1(round_number=5, phase="deepen", can_finalize=True)

    # finalizable is already consumed, so state-based deepen detection remains
    # eligible without requiring a template->deepen edge in the prior round.
    assert select_coach_trigger(state, facts, coach_max=3) == "deepen_entry"

    state.coach_reservations.clear()
    assert select_coach_trigger(state, facts, coach_max=3) == "finalizable"


def test_stagnation_trigger_has_priority_over_deepen_transition() -> None:
    from app.agents.consult_coach import select_coach_trigger

    state = _state(rounds=2)
    facts = _l1(round_number=3, phase="deepen", streak=2)

    assert select_coach_trigger(state, facts, coach_max=3) == "stagnation"


def test_reservation_budget_counts_all_statuses_and_enforces_limits() -> None:
    from app.agents.consult_coach import reserve_coach_attempt

    state = _state(rounds=2)
    state.coach_reservations = [
        _reservation("spent", trigger="deepen_entry", status="unavailable")
    ]

    assert (
        reserve_coach_attempt(
            state,
            _l1(round_number=2, phase="deepen"),
            coach_max=3,
            coach_attempt_id="retry",
        )
        is None
    )
    assert len(state.coach_reservations) == 1

    state.coach_reservations = [
        _reservation("a", trigger="deepen_entry", status="reserved"),
        _reservation("b", trigger="stagnation", status="unavailable"),
        _reservation("c", trigger="other", status="succeeded"),
    ]
    assert (
        reserve_coach_attempt(
            state,
            _l1(round_number=2, can_finalize=True),
            coach_max=3,
            coach_attempt_id="over-budget",
        )
        is None
    )


def test_reservation_allows_at_most_one_attempt_per_round() -> None:
    from app.agents.consult_coach import reserve_coach_attempt

    state = _state(rounds=2)
    state.coach_reservations.append(
        _reservation("existing", round_number=2, trigger="deepen_entry")
    )

    assert (
        reserve_coach_attempt(
            state,
            _l1(round_number=2, can_finalize=True),
            coach_max=3,
            coach_attempt_id="second",
        )
        is None
    )


def test_cross_round_merge_keeps_notes_and_never_reverses_reservation() -> None:
    from app.agents.consult_coach import (
        merge_coach_reservations,
        merge_consult_transcript,
    )

    latest_transcript = _state(rounds=1).career_state.consult_transcript
    latest_transcript[0]["supervisor_notes"] = [_note()]
    incoming_transcript = _state(rounds=2).career_state.consult_transcript
    merged_transcript = merge_consult_transcript(
        latest_transcript,
        incoming_transcript,
    )

    merged_reservations = merge_coach_reservations(
        [_reservation(status="succeeded")],
        [
            _reservation(status="reserved"),
            _reservation(
                "attempt-2",
                round_number=2,
                trigger="stagnation",
            ),
        ],
    )

    assert merged_transcript[0]["supervisor_notes"] == [_note()]
    assert [entry["round"] for entry in merged_transcript] == [1, 2]
    assert merged_reservations == [
        _reservation(status="succeeded"),
        _reservation("attempt-2", round_number=2, trigger="stagnation"),
    ]


def test_cas2_allows_newer_round_and_updates_latest_state_in_place() -> None:
    from app.agents.consult_coach import finalize_coach_reservation

    latest = _state(rounds=2)
    latest.career_state.current_goal.append("Product analyst")
    latest.coach_reservations = [_reservation()]

    changed = finalize_coach_reservation(
        latest,
        round_number=1,
        trigger="deepen_entry",
        coach_attempt_id="attempt-1",
        status="succeeded",
        note=_note(),
    )

    assert changed is True
    assert latest.coach_reservations[0]["status"] == "succeeded"
    assert latest.career_state.current_goal == ["Data analyst", "Product analyst"]
    assert latest.career_state.consult_transcript[0]["supervisor_notes"] == [
        _note()
    ]
    assert latest.supervisor_log[-1]["stage"] == "consult_coach"
    assert latest.supervisor_log[-1]["verdict"] == "advise"


def test_cas2_same_terminal_state_is_an_idempotent_noop() -> None:
    from app.agents.consult_coach import finalize_coach_reservation

    state = _state(rounds=2)
    state.coach_reservations = [_reservation(status="succeeded")]
    state.career_state.consult_transcript[0]["supervisor_notes"] = [_note()]
    state.supervisor_log.append(
        {
            "stage": "consult_coach",
            "coach_attempt_id": "attempt-1",
            "status": "succeeded",
        }
    )
    before = state.model_dump()

    changed = finalize_coach_reservation(
        state,
        round_number=1,
        trigger="deepen_entry",
        coach_attempt_id="attempt-1",
        status="succeeded",
        note=_note(),
    )

    assert changed is False
    assert state.model_dump() == before


@pytest.mark.parametrize(
    ("rounds", "reservations", "round_number", "trigger", "attempt_id", "status"),
    [
        (0, [_reservation()], 1, "deepen_entry", "attempt-1", "succeeded"),
        (2, [], 1, "deepen_entry", "attempt-1", "succeeded"),
        (2, [_reservation()], 1, "stagnation", "attempt-1", "succeeded"),
        (2, [_reservation()], 1, "deepen_entry", "wrong-id", "succeeded"),
        (
            2,
            [_reservation(status="unavailable")],
            1,
            "deepen_entry",
            "attempt-1",
            "succeeded",
        ),
    ],
)
def test_cas2_rejects_each_invalid_identity_or_transition_premise(
    rounds,
    reservations,
    round_number,
    trigger,
    attempt_id,
    status,
) -> None:
    from app.agents.consult_coach import CoachReservationConflict
    from app.agents.consult_coach import finalize_coach_reservation

    state = _state(rounds=rounds)
    state.coach_reservations = reservations

    with pytest.raises(CoachReservationConflict):
        finalize_coach_reservation(
            state,
            round_number=round_number,
            trigger=trigger,
            coach_attempt_id=attempt_id,
            status=status,
            note=_note(attempt_id, trigger=trigger),
        )


@pytest.mark.asyncio
async def test_l2_uses_fast_json_call_and_ignores_extra_output_fields() -> None:
    from app.agents.consult_coach import run_consult_coach

    calls = []

    async def chat(system, user, **kwargs):
        calls.append((system, json.loads(user), kwargs))
        return json.dumps(
            {
                "text": "  当前信息足够，建议继续聚焦关键取舍。  ",
                "verdict": "advise",
                "future_field": "ignored",
            },
            ensure_ascii=False,
        )

    outcome = await run_consult_coach(
        _state(rounds=1),
        reservation=_reservation(),
        l1_facts=_l1(round_number=1, phase="deepen"),
        chat=chat,
        timeout_seconds=1,
    )

    assert calls[0][2] == {"pro": False, "json_mode": True}
    assert outcome.status == "succeeded"
    assert outcome.note == _note() | {
        "text": "当前信息足够，建议继续聚焦关键取舍。"
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["parse", "service", "timeout"])
async def test_l2_failures_become_unavailable(failure) -> None:
    from app.agents.consult_coach import run_consult_coach

    async def chat(*_args, **_kwargs):
        if failure == "parse":
            return "not-json"
        if failure == "service":
            raise RuntimeError("offline")
        await asyncio.sleep(0.05)
        return "{}"

    outcome = await run_consult_coach(
        _state(rounds=1),
        reservation=_reservation(),
        l1_facts=_l1(round_number=1),
        chat=chat,
        timeout_seconds=0.001 if failure == "timeout" else 1,
    )

    assert outcome.status == "unavailable"
    assert outcome.note is None
    assert outcome.error_code == failure


@pytest.mark.asyncio
async def test_l2_cancelled_error_propagates() -> None:
    from app.agents.consult_coach import run_consult_coach

    async def cancelled(*_args, **_kwargs):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await run_consult_coach(
            _state(rounds=1),
            reservation=_reservation(),
            l1_facts=_l1(round_number=1),
            chat=cancelled,
            timeout_seconds=1,
        )


def test_consult_prompt_projection_strips_supervisor_notes() -> None:
    from app.agents.consult_engine import build_consult_user_prompt

    state = _state(rounds=5)
    for index, entry in enumerate(state.career_state.consult_transcript):
        entry["supervisor_notes"] = [_note(f"attempt-{index}")]

    payload = json.loads(
        build_consult_user_prompt(
            state,
            message="继续",
            phase="deepen",
        )
    )

    assert len(payload["recent_transcript"]) == 4
    assert all(
        "supervisor_notes" not in entry
        for entry in payload["recent_transcript"]
    )


def test_supervisor_note_dto_is_optional_and_nested_extra_is_ignored() -> None:
    from app.api.v1.schemas import ConsultTranscriptEntry

    legacy = ConsultTranscriptEntry.model_validate(
        _state(rounds=1).career_state.consult_transcript[0]
    )
    assert legacy.supervisor_notes == []

    payload = _state(rounds=1).career_state.consult_transcript[0]
    payload["supervisor_notes"] = [
        _note() | {"future_nested_field": "ignored"}
    ]
    parsed = ConsultTranscriptEntry.model_validate(payload)

    assert parsed.supervisor_notes[0].coach_attempt_id == "attempt-1"
    assert "future_nested_field" not in parsed.supervisor_notes[0].model_dump()


def test_supervisor_note_text_limit_is_independent_from_assistant_reply() -> None:
    from pydantic import ValidationError

    from app.api.v1.schemas import ConsultTranscriptEntry

    payload = _state(rounds=1).career_state.consult_transcript[0]
    payload["supervisor_notes"] = [_note() | {"text": "教" * 300}]
    assert len(
        ConsultTranscriptEntry.model_validate(payload).supervisor_notes[0].text
    ) == 300

    payload["supervisor_notes"][0]["text"] = "教" * 301
    with pytest.raises(ValidationError):
        ConsultTranscriptEntry.model_validate(payload)


def test_get_consult_omits_absent_note_key_but_returns_persisted_note(
    monkeypatch,
) -> None:
    from app.api.v1 import sessions

    state = _state(rounds=1)

    async def load(_session_id: str):
        return state

    monkeypatch.setattr(sessions, "load_state", load)
    monkeypatch.setattr(sessions, "load_consult_context", _context_from_load(load))
    with TestClient(_api_app()) as client:
        legacy = client.get("/api/v1/sessions/session-1/consult")
        state.career_state.consult_transcript[0]["supervisor_notes"] = [_note()]
        coached = client.get("/api/v1/sessions/session-1/consult")

    assert legacy.status_code == coached.status_code == 200
    assert "supervisor_notes" not in legacy.json()["transcript"][0]
    assert coached.json()["transcript"][0]["supervisor_notes"] == [_note()]


def _context_from_load(load):
    """B2：consult 读路径统一走 load_consult_context（flag-off 也要拿
    generation 供落库保护比对）。由既有 load 假件派生 context 假件；
    generation=0 与本文件 fake mutate 的 mutator(state, 0, 0) 调用对齐，
    保证既有用例的行为断言逐字不变。"""
    from app.db.state_store import ConsultContext

    async def context(session_id):
        state = await load(session_id)
        if state is None:
            return None
        return ConsultContext(
            state=state,
            status="intent_consulting",
            resume_version=1,
            confirmed_resume_version=1,
            resume_upload_generation=0,
        )

    return context


def _append_turn(
    state: SharedState,
    *,
    round_number: int,
    phase: str,
    message: str = "继续",
) -> None:
    state.career_state.consult_rounds_used = round_number
    state.career_state.consult_transcript.append(
        {
            "round": round_number,
            "user_message": message,
            "assistant_reply": "收到。",
            "next_question": "下一步你更看重什么？",
            "phase": phase,
        }
    )


def _turn(
    state: SharedState,
    *,
    phase: str,
    can_finalize: bool,
    clarification_turn_active: bool = False,
):
    from app.agents.consult_engine import ConsultTurn, profile_draft

    return ConsultTurn(
        assistant_reply="收到。",
        next_question="下一步你更看重什么？",
        phase=phase,
        completeness=(0.6 if can_finalize else 0.2),
        can_finalize=can_finalize,
        round=state.career_state.consult_rounds_used,
        profile_draft=profile_draft(state.career_state),
        clarification_turn_active=clarification_turn_active,
        issued_clarification_question=clarification_turn_active,
    )


@pytest.mark.asyncio
async def test_consult_post_waits_for_cas2_and_persists_verdict_twice(
    monkeypatch,
) -> None:
    from app.agents.consult_coach import CoachAttemptOutcome
    from app.api.v1 import sessions

    database_state = _state(rounds=0, complete=True)
    events: list[str] = []

    async def load(_session_id: str):
        return database_state.model_copy(deep=True)

    async def advisor(working, **_kwargs):
        events.append("advisor")
        _append_turn(working, round_number=1, phase="deepen")
        return _turn(working, phase="deepen", can_finalize=True)

    async def mutate(*, mutator, status=None, **_kwargs):
        result = mutator(database_state, 0, 0)
        events.append("cas2" if status is None else "cas1")
        return result

    async def coach(state, *, reservation, l1_facts):
        events.append("coach")
        assert database_state.coach_reservations[0]["status"] == "reserved"
        assert l1_facts["stage"] == "consult_coach_l1"
        return CoachAttemptOutcome(
            status="succeeded",
            note=_note(
                reservation["coach_attempt_id"],
                trigger=reservation["trigger"],
            ),
        )

    monkeypatch.setattr(sessions.settings, "consult_coach_enabled", True)
    monkeypatch.setattr(sessions.settings, "resume_clarify_enabled", False)
    monkeypatch.setattr(sessions, "load_state", load)
    monkeypatch.setattr(sessions, "load_consult_context", _context_from_load(load))
    monkeypatch.setattr(sessions, "run_consult_round", advisor)
    monkeypatch.setattr(sessions, "mutate_state_atomically", mutate)
    monkeypatch.setattr(sessions, "run_consult_coach", coach, raising=False)

    turn, persisted = await sessions._execute_consult_round(
        session_id="session-1",
        mode="targeted",
        message="继续",
        expected_round=0,
        status="intent_consulting",
    )

    assert turn.round == 1
    assert events == ["advisor", "cas1", "coach", "cas2"]
    assert persisted.coach_reservations[0]["status"] == "succeeded"
    notes = persisted.career_state.consult_transcript[0]["supervisor_notes"]
    assert notes[0]["trigger"] == "finalizable"
    assert [entry["stage"] for entry in persisted.supervisor_log] == [
        "consult_coach_l1",
        "consult_coach",
    ]
    assert persisted.supervisor_log[0]["coach_budget_remaining"] == 2
    assert persisted.supervisor_log[-1]["verdict"] == "advise"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_kind", ["reservation_conflict", "storage"])
async def test_cas2_persistence_failure_is_fail_open(
    monkeypatch,
    caplog,
    failure_kind,
) -> None:
    from app.agents.consult_coach import CoachAttemptOutcome, CoachReservationConflict
    from app.api.v1 import sessions

    database_state = _state(rounds=0, complete=True)
    mutate_calls = 0

    async def load(_session_id: str):
        return database_state.model_copy(deep=True)

    async def advisor(working, **_kwargs):
        _append_turn(working, round_number=1, phase="deepen")
        return _turn(working, phase="deepen", can_finalize=True)

    async def mutate(*, mutator, **_kwargs):
        nonlocal mutate_calls
        mutate_calls += 1
        if mutate_calls == 1:
            return mutator(database_state, 0, 0)
        if failure_kind == "reservation_conflict":
            raise CoachReservationConflict("reservation moved")
        raise RuntimeError("database unavailable")

    async def coach(*_args, **_kwargs):
        return CoachAttemptOutcome(status="succeeded", note=_note())

    monkeypatch.setattr(sessions.settings, "consult_coach_enabled", True)
    monkeypatch.setattr(sessions.settings, "resume_clarify_enabled", False)
    monkeypatch.setattr(sessions, "load_state", load)
    monkeypatch.setattr(sessions, "load_consult_context", _context_from_load(load))
    monkeypatch.setattr(sessions, "run_consult_round", advisor)
    monkeypatch.setattr(sessions, "mutate_state_atomically", mutate)
    monkeypatch.setattr(sessions, "run_consult_coach", coach, raising=False)

    with caplog.at_level("WARNING"):
        turn, persisted = await sessions._execute_consult_round(
            session_id="session-1",
            mode="targeted",
            message="继续",
            expected_round=0,
            status="intent_consulting",
        )

    assert turn.round == 1
    assert persisted.coach_reservations[0]["status"] == "reserved"
    assert "coach CAS2 persistence failed" in caplog.text


@pytest.mark.asyncio
async def test_cas2_persistence_cancelled_error_propagates(monkeypatch) -> None:
    from app.agents.consult_coach import CoachAttemptOutcome
    from app.api.v1 import sessions

    database_state = _state(rounds=0, complete=True)
    mutate_calls = 0

    async def load(_session_id: str):
        return database_state.model_copy(deep=True)

    async def advisor(working, **_kwargs):
        _append_turn(working, round_number=1, phase="deepen")
        return _turn(working, phase="deepen", can_finalize=True)

    async def mutate(*, mutator, **_kwargs):
        nonlocal mutate_calls
        mutate_calls += 1
        if mutate_calls == 1:
            return mutator(database_state, 0, 0)
        raise asyncio.CancelledError

    async def coach(*_args, **_kwargs):
        return CoachAttemptOutcome(status="succeeded", note=_note())

    monkeypatch.setattr(sessions.settings, "consult_coach_enabled", True)
    monkeypatch.setattr(sessions.settings, "resume_clarify_enabled", False)
    monkeypatch.setattr(sessions, "load_state", load)
    monkeypatch.setattr(sessions, "load_consult_context", _context_from_load(load))
    monkeypatch.setattr(sessions, "run_consult_round", advisor)
    monkeypatch.setattr(sessions, "mutate_state_atomically", mutate)
    monkeypatch.setattr(sessions, "run_consult_coach", coach, raising=False)

    with pytest.raises(asyncio.CancelledError):
        await sessions._execute_consult_round(
            session_id="session-1",
            mode="targeted",
            message="继续",
            expected_round=0,
            status="intent_consulting",
        )


@pytest.mark.asyncio
async def test_consult_coach_unavailable_is_fail_open_and_is_landed_before_return(
    monkeypatch,
) -> None:
    from app.agents.consult_coach import CoachAttemptOutcome
    from app.api.v1 import sessions

    database_state = _state(rounds=0, complete=True)

    async def load(_session_id: str):
        return database_state.model_copy(deep=True)

    async def advisor(working, **_kwargs):
        _append_turn(working, round_number=1, phase="deepen")
        return _turn(working, phase="deepen", can_finalize=True)

    async def mutate(*, mutator, **_kwargs):
        return mutator(database_state, 0, 0)

    async def unavailable(*_args, **_kwargs):
        return CoachAttemptOutcome(
            status="unavailable",
            error_code="service",
        )

    monkeypatch.setattr(sessions.settings, "consult_coach_enabled", True)
    monkeypatch.setattr(sessions.settings, "resume_clarify_enabled", False)
    monkeypatch.setattr(sessions, "load_state", load)
    monkeypatch.setattr(sessions, "load_consult_context", _context_from_load(load))
    monkeypatch.setattr(sessions, "run_consult_round", advisor)
    monkeypatch.setattr(sessions, "mutate_state_atomically", mutate)
    monkeypatch.setattr(sessions, "run_consult_coach", unavailable, raising=False)

    _, persisted = await sessions._execute_consult_round(
        session_id="session-1",
        mode="targeted",
        message="继续",
        expected_round=0,
        status="intent_consulting",
    )

    assert persisted.coach_reservations[0]["status"] == "unavailable"
    assert "supervisor_notes" not in persisted.career_state.consult_transcript[0]
    assert persisted.supervisor_log[-1]["error_code"] == "service"


@pytest.mark.asyncio
async def test_cancelled_coach_leaves_reserved_burned_and_propagates(
    monkeypatch,
) -> None:
    from app.api.v1 import sessions

    database_state = _state(rounds=0, complete=True)

    async def load(_session_id: str):
        return database_state.model_copy(deep=True)

    async def advisor(working, **_kwargs):
        _append_turn(working, round_number=1, phase="deepen")
        return _turn(working, phase="deepen", can_finalize=True)

    async def mutate(*, mutator, **_kwargs):
        return mutator(database_state, 0, 0)

    async def cancelled(*_args, **_kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(sessions.settings, "consult_coach_enabled", True)
    monkeypatch.setattr(sessions.settings, "resume_clarify_enabled", False)
    monkeypatch.setattr(sessions, "load_state", load)
    monkeypatch.setattr(sessions, "load_consult_context", _context_from_load(load))
    monkeypatch.setattr(sessions, "run_consult_round", advisor)
    monkeypatch.setattr(sessions, "mutate_state_atomically", mutate)
    monkeypatch.setattr(sessions, "run_consult_coach", cancelled, raising=False)

    with pytest.raises(asyncio.CancelledError):
        await sessions._execute_consult_round(
            session_id="session-1",
            mode="targeted",
            message="继续",
            expected_round=0,
            status="intent_consulting",
        )

    assert database_state.coach_reservations[0]["status"] == "reserved"


@pytest.mark.asyncio
async def test_disabled_coach_is_x0_equivalent_with_zero_call_or_side_effect(
    monkeypatch,
) -> None:
    from app.api.v1 import sessions

    database_state = _state(rounds=0, complete=True)
    cas_calls = 0

    async def load(_session_id: str):
        return database_state.model_copy(deep=True)

    async def advisor(working, **_kwargs):
        _append_turn(working, round_number=1, phase="deepen")
        return _turn(working, phase="deepen", can_finalize=True)

    async def mutate(*, mutator, **_kwargs):
        nonlocal cas_calls
        cas_calls += 1
        return mutator(database_state, 0, 0)

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("disabled coach must make zero L2 calls")

    monkeypatch.setattr(sessions.settings, "consult_coach_enabled", False)
    monkeypatch.setattr(sessions.settings, "resume_clarify_enabled", False)
    monkeypatch.setattr(sessions, "load_state", load)
    monkeypatch.setattr(sessions, "load_consult_context", _context_from_load(load))
    monkeypatch.setattr(sessions, "run_consult_round", advisor)
    monkeypatch.setattr(sessions, "mutate_state_atomically", mutate)
    monkeypatch.setattr(sessions, "run_consult_coach", forbidden, raising=False)

    _, persisted = await sessions._execute_consult_round(
        session_id="session-1",
        mode="targeted",
        message="继续",
        expected_round=0,
        status="intent_consulting",
    )

    assert cas_calls == 1
    assert persisted.coach_reservations == []
    assert persisted.supervisor_log == []
    assert "supervisor_notes" not in persisted.career_state.consult_transcript[0]


@pytest.mark.asyncio
async def test_feature_switch_matrix_preserves_scoped_equivalence_contract(
    monkeypatch,
) -> None:
    from app.agents import consult_engine
    from app.agents.consult_coach import CoachAttemptOutcome
    from app.api.v1 import sessions
    from app.api.v1.schemas import ConsultResponse
    from app.db.state_store import ConsultContext

    observations: dict[tuple[bool, bool], dict] = {}

    for clarify_enabled, coach_enabled in (
        (False, False),
        (True, False),
        (False, True),
        (True, True),
    ):
        database_state = _state(rounds=0, complete=True)
        calls = {"consult": 0, "coach": 0}
        prompts: list[str] = []

        async def load(_session_id: str):
            return database_state.model_copy(deep=True)

        async def context(_session_id: str):
            return ConsultContext(
                state=database_state.model_copy(deep=True),
                status="resume_ready",
                resume_version=1,
                confirmed_resume_version=1,
                resume_upload_generation=1,
            )

        async def chat(system: str, _user: str, **_kwargs):
            calls["consult"] += 1
            prompts.append(system)
            return json.dumps(
                {
                    "assistant_reply": "收到。",
                    "next_question": "还有其他岗位偏好吗？",
                    "profile_updates": {},
                    "phase_suggestion": "deepen",
                },
                ensure_ascii=False,
            )

        async def mutate(*, mutator, **_kwargs):
            return mutator(database_state, 1, 1)

        async def coach(_state, *, reservation, **_kwargs):
            calls["coach"] += 1
            attempt_id = str(reservation["coach_attempt_id"])
            return CoachAttemptOutcome(
                status="succeeded",
                note={
                    "kind": "coach",
                    "trigger": reservation["trigger"],
                    "text": "方向完整，可以生成确认单。",
                    "verdict": "advise",
                    "coach_attempt_id": attempt_id,
                },
            )

        monkeypatch.setattr(
            sessions.settings,
            "resume_clarify_enabled",
            clarify_enabled,
        )
        monkeypatch.setattr(
            sessions.settings,
            "consult_coach_enabled",
            coach_enabled,
        )
        monkeypatch.setattr(sessions, "load_state", load)
        monkeypatch.setattr(sessions, "load_consult_context", context)
        monkeypatch.setattr(sessions, "mutate_state_atomically", mutate)
        monkeypatch.setattr(sessions, "run_consult_coach", coach)
        monkeypatch.setattr(consult_engine.deepseek, "chat", chat)

        turn, persisted = await sessions._execute_consult_round(
            session_id="session-1",
            mode="targeted",
            message="继续",
            expected_round=0,
            status="intent_consulting",
        )
        public_response = ConsultResponse(
            assistant_reply=turn.assistant_reply,
            next_question=turn.next_question,
            phase=turn.phase,
            completeness=turn.completeness,
            can_finalize=turn.can_finalize,
            round=turn.round,
            profile_draft=turn.profile_draft,
            clarification_progress=sessions._clarification_progress(persisted),
        ).model_dump(mode="json")
        transcript_without_notes = [
            {key: value for key, value in entry.items() if key != "supervisor_notes"}
            for entry in persisted.career_state.consult_transcript
        ]
        observations[(clarify_enabled, coach_enabled)] = {
            "prompt": prompts,
            "calls": calls,
            "response": public_response,
            "state_delta": {
                "transcript": transcript_without_notes,
                "resume": persisted.resume_state.model_dump(mode="json"),
                "coach_reservations": [
                    {
                        "round": item["round"],
                        "trigger": item["trigger"],
                        "status": item["status"],
                    }
                    for item in persisted.coach_reservations
                ],
                "supervisor_stages": [
                    item.get("stage") for item in persisted.supervisor_log
                ],
                "note_count": sum(
                    len(entry.get("supervisor_notes", []))
                    for entry in persisted.career_state.consult_transcript
                ),
            },
        }

    baseline = observations[(False, False)]
    clarify_prompt = observations[(True, False)]["prompt"]
    expected_by_switches = {
        (False, False): {"coach_calls": 0, "coach_state": False},
        (True, False): {"coach_calls": 0, "coach_state": False},
        (False, True): {"coach_calls": 1, "coach_state": True},
        (True, True): {"coach_calls": 1, "coach_state": True},
    }
    for switches, expected in expected_by_switches.items():
        clarify_enabled, _coach_enabled = switches
        observation = observations[switches]
        assert observation["calls"] == {
            "consult": 1,
            "coach": expected["coach_calls"],
        }
        assert observation["response"] == baseline["response"]
        assert observation["state_delta"]["transcript"] == baseline[
            "state_delta"
        ]["transcript"]
        assert observation["state_delta"]["resume"] == baseline["state_delta"][
            "resume"
        ]
        # 审计二轮 T1 收紧：state-delta 用全形状精确断言——错 trigger/status/
        # stage、多余 reservation 或多写 note 都必须红，不接受真值级检查。
        if expected["coach_state"]:
            expected_trigger = (
                "finalizable"
                if baseline["response"]["can_finalize"]
                else "deepen_entry"
            )
            assert observation["state_delta"]["coach_reservations"] == [
                {"round": 1, "trigger": expected_trigger, "status": "succeeded"}
            ]
            assert observation["state_delta"]["supervisor_stages"] == [
                "consult_coach_l1",
                "consult_coach",
            ]
        else:
            assert observation["state_delta"]["coach_reservations"] == []
            assert observation["state_delta"]["supervisor_stages"] == []
        assert observation["state_delta"]["note_count"] == int(
            expected["coach_state"]
        )
        if clarify_enabled:
            assert observation["prompt"] == clarify_prompt
            assert observation["prompt"] != baseline["prompt"]
        else:
            assert observation["prompt"] == baseline["prompt"]


@pytest.mark.asyncio
async def test_same_round_cas_conflict_blocks_physical_coach_call(
    monkeypatch,
) -> None:
    from fastapi import HTTPException

    from app.api.v1 import sessions

    initial = _state(rounds=0, complete=True)

    async def load(_session_id: str):
        return initial.model_copy(deep=True)

    async def advisor(working, **_kwargs):
        _append_turn(working, round_number=1, phase="deepen")
        return _turn(working, phase="deepen", can_finalize=True)

    async def mutate(*, mutator, **_kwargs):
        concurrent = _state(rounds=1, complete=True)
        return mutator(concurrent, 0, 0)

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("CAS1 conflict must prevent the physical coach call")

    monkeypatch.setattr(sessions.settings, "consult_coach_enabled", True)
    monkeypatch.setattr(sessions.settings, "resume_clarify_enabled", False)
    monkeypatch.setattr(sessions, "load_state", load)
    monkeypatch.setattr(sessions, "load_consult_context", _context_from_load(load))
    monkeypatch.setattr(sessions, "run_consult_round", advisor)
    monkeypatch.setattr(sessions, "mutate_state_atomically", mutate)
    monkeypatch.setattr(sessions, "run_consult_coach", forbidden, raising=False)

    with pytest.raises(HTTPException) as captured:
        await sessions._execute_consult_round(
            session_id="session-1",
            mode="targeted",
            message="继续",
            expected_round=0,
            status="intent_consulting",
        )

    assert captured.value.status_code == 409


@pytest.mark.asyncio
async def test_cas2_interleaved_with_next_persist_keeps_note_and_terminal_status(
    monkeypatch,
) -> None:
    from app.agents.consult_coach import finalize_coach_reservation
    from app.api.v1 import sessions

    database_state = _state(rounds=1)
    database_state.coach_reservations = [_reservation()]
    advisor_started = asyncio.Event()
    release_advisor = asyncio.Event()

    async def load(_session_id: str):
        return database_state.model_copy(deep=True)

    async def advisor(working, **_kwargs):
        advisor_started.set()
        await release_advisor.wait()
        _append_turn(working, round_number=2, phase="template")
        return _turn(working, phase="template", can_finalize=False)

    async def mutate(*, mutator, **_kwargs):
        return mutator(database_state, 0, 0)

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("no second trigger is eligible")

    monkeypatch.setattr(sessions.settings, "consult_coach_enabled", True)
    monkeypatch.setattr(sessions.settings, "resume_clarify_enabled", False)
    monkeypatch.setattr(sessions, "load_state", load)
    monkeypatch.setattr(sessions, "load_consult_context", _context_from_load(load))
    monkeypatch.setattr(sessions, "run_consult_round", advisor)
    monkeypatch.setattr(sessions, "mutate_state_atomically", mutate)
    monkeypatch.setattr(sessions, "run_consult_coach", forbidden, raising=False)

    request = asyncio.create_task(
        sessions._execute_consult_round(
            session_id="session-1",
            mode="targeted",
            message="继续",
            expected_round=1,
            status="intent_consulting",
        )
    )
    await advisor_started.wait()
    finalize_coach_reservation(
        database_state,
        round_number=1,
        trigger="deepen_entry",
        coach_attempt_id="attempt-1",
        status="succeeded",
        note=_note(),
    )
    release_advisor.set()
    _, persisted = await request

    assert persisted.coach_reservations[0]["status"] == "succeeded"
    assert persisted.career_state.consult_transcript[0]["supervisor_notes"] == [
        _note()
    ]
    assert persisted.career_state.consult_rounds_used == 2
    assert any(
        entry.get("stage") == "consult_coach"
        and entry.get("coach_attempt_id") == "attempt-1"
        for entry in persisted.supervisor_log
    )


@pytest.mark.asyncio
async def test_both_switches_on_excludes_clarification_round_from_stagnation(
    monkeypatch,
) -> None:
    from app.api.v1 import sessions

    database_state = _state(rounds=1)
    database_state.resume_state = ResumeState(
        clarification_targets=[{"target_ref": "T1", "status": "open"}],
    )
    database_state.supervisor_log.append(
        {
            "stage": "consult_coach_l1",
            "round": 1,
            "stagnation_streak": 1,
        }
    )

    async def context(_session_id: str):
        return SimpleNamespace(
            state=database_state.model_copy(deep=True),
            status="resume_ready",
            resume_version=4,
            confirmed_resume_version=4,
            resume_upload_generation=9,
        )

    async def advisor(working, **_kwargs):
        _append_turn(working, round_number=2, phase="resume_clarify")
        return _turn(
            working,
            phase="resume_clarify",
            can_finalize=False,
            clarification_turn_active=True,
        )

    async def mutate(*, mutator, **_kwargs):
        return mutator(database_state, 4, 9)

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("clarification turn must not trigger stagnation")

    monkeypatch.setattr(sessions.settings, "consult_coach_enabled", True)
    monkeypatch.setattr(sessions.settings, "resume_clarify_enabled", True)
    monkeypatch.setattr(sessions, "load_consult_context", context)
    monkeypatch.setattr(sessions, "run_consult_round", advisor)
    monkeypatch.setattr(sessions, "mutate_state_atomically", mutate)
    monkeypatch.setattr(sessions, "run_consult_coach", forbidden, raising=False)

    _, persisted = await sessions._execute_consult_round(
        session_id="session-1",
        mode="targeted",
        message="补充这段经历",
        expected_round=1,
        status="intent_consulting",
    )

    assert persisted.coach_reservations == []
    # G18 用户裁决：澄清轮暂停计数——沿用上一轮已累计的 streak=1，不清零
    assert persisted.supervisor_log[-1]["stagnation_streak"] == 1
    assert persisted.supervisor_log[-1]["clarification_turn_active"] is True
