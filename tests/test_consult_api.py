from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.state.schema import CareerState, SharedState


def _app(*, user=None) -> FastAPI:
    from app.api.auth.deps import optional_current_user, require_owned_session
    from app.api.v1.router import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_owned_session] = lambda: None
    if user is not None:
        app.dependency_overrides[optional_current_user] = lambda: user
    return app


def _authed_user():
    from app.api.auth.sessions import AuthedUser

    return AuthedUser(
        user_id="11111111-1111-1111-1111-111111111111",
        display_name=None,
        avatar_url=None,
        status="active",
        token_version=0,
        is_admin=False,
        created_at=datetime(2026, 8, 5, tzinfo=UTC),
        last_login_at=None,
    )


def _complete_state(*, rounds: int = 0) -> SharedState:
    return SharedState(
        session_id="session-1",
        user_id="private-user",
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
    )


def test_post_consult_uses_atomic_cas_and_returns_new_contract(monkeypatch) -> None:
    from app.agents.consult_engine import ConsultTurn
    from app.api.v1 import sessions

    state = SharedState(session_id="session-1", user_id="private-user")
    persisted = []

    async def load(_session_id: str):
        return state.model_copy(deep=True)

    async def run(current, *, mode, message):
        assert mode == "targeted"
        assert message == "我想做数据分析。"
        current.career_state.current_goal = ["Data analyst"]
        current.career_state.consult_rounds_used = 1
        current.career_state.consult_transcript.append(
            {
                "round": 1,
                "user_message": message,
                "assistant_reply": "我理解你希望从数据分析开始。",
                "next_question": "你优先考虑哪个工作地点？",
                "phase": "template",
            }
        )
        return ConsultTurn(
            assistant_reply="我理解你希望从数据分析开始。",
            next_question="你优先考虑哪个工作地点？",
            phase="template",
            completeness=0.2,
            can_finalize=False,
            round=1,
            profile_draft={
                "current_goal": ["Data analyst"],
                "long_term_goal": [],
                "hard_constraints": {},
                "soft_preferences": {},
                "avoid_roles": [],
            },
        )

    async def mutate(*, session_id: str, mutator, status: str):
        assert session_id == "session-1"
        assert status == "intent_consulting"
        latest = state.model_copy(deep=True)
        result = mutator(latest)
        persisted.append(latest)
        return result

    monkeypatch.setattr(sessions, "load_state", load)
    monkeypatch.setattr(sessions, "run_consult_round", run, raising=False)
    monkeypatch.setattr(sessions, "mutate_state_atomically", mutate)

    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/sessions/session-1/consult",
            json={
                "mode": "targeted",
                "message": "我想做数据分析。",
                "expected_round": 0,
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "assistant_reply": "我理解你希望从数据分析开始。",
        "next_question": "你优先考虑哪个工作地点？",
        "phase": "template",
        "completeness": 0.2,
        "can_finalize": False,
        "round": 1,
        "profile_draft": {
            "current_goal": ["Data analyst"],
            "long_term_goal": [],
            "hard_constraints": {},
            "soft_preferences": {},
            "avoid_roles": [],
        },
    }
    assert persisted[0].career_state.consult_rounds_used == 1
    assert persisted[0].career_state.consult_transcript[0]["round"] == 1


def test_authenticated_first_consult_round_receives_remembered_profile(
    monkeypatch,
) -> None:
    from app.agents.consult_engine import ConsultTurn
    from app.api.v1 import sessions

    state = SharedState(session_id="session-1", user_id="private-user")
    remembered = {"current_goal": ["Data analyst"]}
    captured = {}

    async def load(_session_id: str):
        return state.model_copy(deep=True)

    async def load_profile(user_id: str):
        assert user_id == _authed_user().user_id
        return {
            "profile": remembered,
            "updated_at": datetime.now(UTC),
        }

    async def run(current, *, remembered_profile, **_kwargs):
        captured["remembered_profile"] = remembered_profile
        current.career_state.consult_rounds_used = 1
        return ConsultTurn(
            assistant_reply="我找到了你上次确认过的画像。",
            next_question="这些信息仍然适用吗？",
            phase="template",
            completeness=0.0,
            can_finalize=False,
            round=1,
            profile_draft={
                "current_goal": [],
                "long_term_goal": [],
                "hard_constraints": {},
                "soft_preferences": {},
                "avoid_roles": [],
            },
        )

    async def mutate(*, mutator, **_kwargs):
        return mutator(state.model_copy(deep=True))

    monkeypatch.setattr(sessions, "load_state", load)
    monkeypatch.setattr(sessions, "load_profile", load_profile, raising=False)
    monkeypatch.setattr(sessions, "run_consult_round", run)
    monkeypatch.setattr(sessions, "mutate_state_atomically", mutate)

    with TestClient(_app(user=_authed_user())) as client:
        response = client.post(
            "/api/v1/sessions/session-1/consult",
            json={
                "mode": "targeted",
                "message": "开始咨询",
                "expected_round": 0,
            },
        )

    assert response.status_code == 200
    assert captured["remembered_profile"] == remembered


def test_post_consult_returns_409_before_llm_for_stale_expected_round(
    monkeypatch,
) -> None:
    from app.api.v1 import sessions

    async def load(_session_id: str):
        return _complete_state(rounds=2)

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("stale request must not call the LLM")

    monkeypatch.setattr(sessions, "load_state", load)
    monkeypatch.setattr(sessions, "run_consult_round", forbidden, raising=False)

    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/sessions/session-1/consult",
            json={"mode": "targeted", "message": "继续", "expected_round": 1},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "consultation round conflict"


def test_post_consult_rechecks_cas_inside_locked_mutation(monkeypatch) -> None:
    from app.agents.consult_engine import ConsultTurn
    from app.api.v1 import sessions

    async def load(_session_id: str):
        return _complete_state(rounds=0)

    async def run(current, **_kwargs):
        current.career_state.consult_rounds_used = 1
        return ConsultTurn(
            assistant_reply="收到。",
            next_question="下一步你更看重什么？",
            phase="deepen",
            completeness=0.8,
            can_finalize=True,
            round=1,
            profile_draft={},
        )

    async def mutate(*, mutator, **_kwargs):
        concurrent = _complete_state(rounds=1)
        return mutator(concurrent)

    monkeypatch.setattr(sessions, "load_state", load)
    monkeypatch.setattr(sessions, "run_consult_round", run, raising=False)
    monkeypatch.setattr(sessions, "mutate_state_atomically", mutate)

    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/sessions/session-1/consult",
            json={"mode": "targeted", "message": "继续", "expected_round": 0},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "consultation round conflict"


def test_post_consult_cannot_overwrite_concurrent_brief_confirmation(
    monkeypatch,
) -> None:
    from app.agents.consult_engine import ConsultTurn
    from app.api.v1 import sessions

    async def load(_session_id: str):
        return _complete_state(rounds=0)

    async def run(current, **_kwargs):
        current.career_state.consult_rounds_used = 1
        current.career_state.intent_consulted = False
        return ConsultTurn(
            assistant_reply="收到。",
            next_question="下一步你更看重什么？",
            phase="deepen",
            completeness=0.8,
            can_finalize=True,
            round=1,
            profile_draft={},
        )

    confirmed = _complete_state(rounds=0)
    confirmed.career_state.intent_consulted = True

    async def mutate(*, mutator, **_kwargs):
        return mutator(confirmed)

    monkeypatch.setattr(sessions, "load_state", load)
    monkeypatch.setattr(sessions, "run_consult_round", run)
    monkeypatch.setattr(sessions, "mutate_state_atomically", mutate)

    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/sessions/session-1/consult",
            json={"mode": "targeted", "message": "继续", "expected_round": 0},
        )

    assert response.status_code == 409
    assert confirmed.career_state.intent_consulted is True


def test_get_consult_replays_transcript_and_current_profile(monkeypatch) -> None:
    from app.api.v1 import sessions

    state = _complete_state(rounds=2)
    state.career_state.intent_mode = "targeted"
    state.career_state.consult_transcript = [
        {
            "round": 1,
            "user_message": "数据分析",
            "assistant_reply": "明白。",
            "next_question": "地点呢？",
            "phase": "template",
        },
        {
            "round": 2,
            "user_message": "伯明翰",
            "assistant_reply": "收到。",
            "next_question": "需要签证担保吗？",
            "phase": "template",
        },
    ]

    async def load(_session_id: str):
        return state

    monkeypatch.setattr(sessions, "load_state", load)

    with TestClient(_app()) as client:
        response = client.get("/api/v1/sessions/session-1/consult")

    assert response.status_code == 200
    body = response.json()
    assert [entry["round"] for entry in body["transcript"]] == [1, 2]
    assert body["profile_draft"]["current_goal"] == ["Data analyst"]
    assert body["round"] == 2
    assert body["phase"] == "deepen"
    assert body["completeness"] == 0.7
    assert body["can_finalize"] is True


def test_finalize_requires_complete_profile_and_is_idempotent(monkeypatch) -> None:
    from app.api.v1 import sessions

    current = SharedState(session_id="session-1", user_id="private-user")

    async def load(_session_id: str):
        return current.model_copy(deep=True)

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("finalize must not create or persist a run")

    monkeypatch.setattr(sessions, "load_state", load)
    monkeypatch.setattr(sessions, "create_run", forbidden)
    monkeypatch.setattr(sessions, "save_match_brief", forbidden)

    with TestClient(_app()) as client:
        incomplete = client.post("/api/v1/sessions/session-1/consult/finalize")
        current = _complete_state(rounds=3)
        first = client.post("/api/v1/sessions/session-1/consult/finalize")
        second = client.post("/api/v1/sessions/session-1/consult/finalize")

    assert incomplete.status_code == 409
    assert incomplete.json()["detail"] == "consultation profile is incomplete"
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert first.json() == {
        "career_goal": "希望匹配的职业方向：Data analyst",
        "hard_constraints": {
            "locations": ["Birmingham"],
            "need_visa_sponsor": False,
        },
        "soft_preferences": {"title_keywords": ["data"]},
        "avoid_roles": ["Sales"],
        "result_count": 5,
    }


def test_match_brief_confirmation_writes_authenticated_profile(monkeypatch) -> None:
    from app.api.v1 import sessions

    state = _complete_state(rounds=3)
    state.career_state.long_term_goal = ["Lead an analytics team"]
    captured = {}

    async def metadata(_session_id: str):
        return {
            "exists": True,
            "resume_version": 1,
            "confirmed_resume_version": 1,
        }

    async def mutate(*, mutator, **_kwargs):
        latest = state.model_copy(deep=True)
        result = mutator(latest)
        captured["state"] = latest
        return result

    async def create_run(*, session_id: str):
        assert session_id == "session-1"
        return SimpleNamespace(run_id="run-1")

    async def save_brief(**_kwargs):
        return None

    async def merge_profile(user_id: str, updates: dict):
        captured["profile"] = (user_id, updates)
        return {"profile": updates, "updated_at": datetime.now(UTC)}

    monkeypatch.setattr(sessions, "get_resume_metadata", metadata)
    monkeypatch.setattr(sessions, "mutate_state_atomically", mutate)
    monkeypatch.setattr(sessions, "create_run", create_run)
    monkeypatch.setattr(sessions, "save_match_brief", save_brief)
    monkeypatch.setattr(sessions, "merge_profile", merge_profile, raising=False)

    with TestClient(_app(user=_authed_user())) as client:
        response = client.post(
            "/api/v1/sessions/session-1/match-brief",
            json={
                "career_goal": "Find evidence-grounded analytics engineering roles",
                "hard_constraints": {"locations": ["London"]},
                "soft_preferences": {"title_keywords": ["analytics"]},
                "avoid_roles": ["Sales"],
                "result_count": 5,
            },
        )

    assert response.status_code == 201
    assert captured["state"].career_state.intent_consulted is True
    user_id, profile = captured["profile"]
    assert user_id == _authed_user().user_id
    assert profile == {
        "current_goal": ["Find evidence-grounded analytics engineering roles"],
        "long_term_goal": ["Lead an analytics team"],
        "hard_constraints": {"locations": ["London"]},
        "soft_preferences": {"title_keywords": ["analytics"]},
        "avoid_roles": ["Sales"],
    }


def test_match_brief_confirmation_skips_profile_for_legacy_session(
    monkeypatch,
) -> None:
    from app.api.v1 import sessions

    state = _complete_state()

    async def metadata(_session_id: str):
        return {
            "exists": True,
            "resume_version": 1,
            "confirmed_resume_version": 1,
        }

    async def mutate(*, mutator, **_kwargs):
        return mutator(state.model_copy(deep=True))

    async def create_run(**_kwargs):
        return SimpleNamespace(run_id="run-1")

    async def save_brief(**_kwargs):
        return None

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("legacy confirmation must not write user_profiles")

    monkeypatch.setattr(sessions, "get_resume_metadata", metadata)
    monkeypatch.setattr(sessions, "mutate_state_atomically", mutate)
    monkeypatch.setattr(sessions, "create_run", create_run)
    monkeypatch.setattr(sessions, "save_match_brief", save_brief)
    monkeypatch.setattr(sessions, "merge_profile", forbidden, raising=False)

    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/sessions/session-1/match-brief",
            json={
                "career_goal": "Find evidence-grounded data analyst roles",
                "result_count": 5,
            },
        )

    assert response.status_code == 201


def test_intent_career_persistence_allow_list_includes_consult_fields() -> None:
    from app.api.v1.sessions import _INTENT_CAREER_FIELDS

    assert "consult_transcript" in _INTENT_CAREER_FIELDS
    assert "consult_rounds_used" in _INTENT_CAREER_FIELDS
