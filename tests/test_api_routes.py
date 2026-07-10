import os

import httpx
import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")
os.environ.setdefault("QWEN_API_KEY", "sk-test")


@pytest.mark.asyncio
async def test_post_resume_persists_upload_and_queues_background_task(
    monkeypatch, tmp_path
):
    from app.api.main import app
    from app.api import routes

    calls = []

    async def fake_save_state(state, status):
        calls.append(("save_state", state.session_id, state.user_id, status))

    async def fake_run_resume_task(*, session_id, user_id, resume_path):
        calls.append(("resume_task", session_id, user_id, resume_path.name))

    monkeypatch.setattr(routes, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(routes, "save_state", fake_save_state)
    monkeypatch.setattr(routes, "_run_resume_task", fake_run_resume_task)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/resume",
            data={"session_id": "s1", "user_id": "u1"},
            files={"file": ("resume.txt", b"hello resume", "text/plain")},
        )

    assert response.status_code == 202
    assert response.json() == {"session_id": "s1", "status": "resume_queued"}
    assert ("save_state", "s1", "u1", "resume_queued") in calls
    assert ("resume_task", "s1", "u1", "s1.txt") in calls
    assert (tmp_path / "s1.txt").read_bytes() == b"hello resume"


@pytest.mark.asyncio
async def test_post_match_requires_existing_session_and_queues_task(monkeypatch):
    from app.api.main import app
    from app.api import routes
    from app.state.schema import ResumeState, SharedState

    calls = []
    state = SharedState(
        session_id="s1",
        user_id="u1",
        resume_state=ResumeState(
            normalized_base_resume="Python analyst resume",
            original_evidence_spans=[{"span_id": "R001", "text": "Python"}],
        ),
    )

    async def fake_load_state_with_status(session_id):
        calls.append(("load_state_with_status", session_id))
        return state, "resume_ready"

    async def fake_save_state(saved_state, status):
        calls.append(("save_state", saved_state.session_id, status))

    async def fake_run_match_task(*, session_id, user_goal_text, top_k, include_raptor):
        calls.append(("match_task", session_id, user_goal_text, top_k, include_raptor))

    monkeypatch.setattr(routes, "load_state_with_status", fake_load_state_with_status)
    monkeypatch.setattr(routes, "save_state", fake_save_state)
    monkeypatch.setattr(routes, "_run_match_task", fake_run_match_task)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/match",
            json={
                "session_id": "s1",
                "user_goal_text": "Find analyst roles in Birmingham",
                "top_k": 3,
                "include_raptor": True,
            },
        )

    assert response.status_code == 202
    assert response.json() == {"session_id": "s1", "status": "match_queued"}
    assert ("load_state_with_status", "s1") in calls
    assert ("save_state", "s1", "match_queued") in calls
    assert (
        "match_task",
        "s1",
        "Find analyst roles in Birmingham",
        3,
        True,
    ) in calls


@pytest.mark.asyncio
async def test_post_match_unknown_session_returns_404(monkeypatch):
    from app.api.main import app
    from app.api import routes

    async def fake_load_state_with_status(session_id):
        return None

    monkeypatch.setattr(routes, "load_state_with_status", fake_load_state_with_status)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/match",
            json={"session_id": "missing", "user_goal_text": "anything"},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_post_match_rejects_session_before_resume_is_ready(monkeypatch):
    from app.api.main import app
    from app.api import routes
    from app.state.schema import SharedState

    calls = []
    state = SharedState(session_id="s1", user_id="u1")

    async def fake_load_state(session_id):
        return state

    async def fake_load_state_with_status(session_id):
        return state, "resume_running"

    async def fake_save_state(saved_state, status):
        calls.append(("save_state", saved_state.session_id, status))

    async def fake_run_match_task(*, session_id, user_goal_text, top_k, include_raptor):
        calls.append(("match_task", session_id, user_goal_text, top_k, include_raptor))

    monkeypatch.setattr(routes, "load_state", fake_load_state)
    monkeypatch.setattr(routes, "load_state_with_status", fake_load_state_with_status)
    monkeypatch.setattr(routes, "save_state", fake_save_state)
    monkeypatch.setattr(routes, "_run_match_task", fake_run_match_task)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/match",
            json={"session_id": "s1", "user_goal_text": "Find analyst roles"},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "resume is not ready for matching"
    assert calls == []


@pytest.mark.asyncio
async def test_status_and_result_are_read_from_state_store(monkeypatch):
    from app.api.main import app
    from app.api import routes
    from app.state.schema import ResumeState, SharedState, StrategyState

    async def fake_load_state_with_status(session_id):
        return (
            SharedState(
                session_id=session_id,
                user_id="u1",
                resume_state=ResumeState(normalized_base_resume="base resume"),
                strategy_state=StrategyState(
                    recommended_roles=[
                        {
                            "job_id": "job-1",
                            "tier": "now_fit",
                            "evidence_span_ids": ["job-1:skills:1"],
                        }
                    ]
                ),
            ),
            "agentic_done",
        )

    monkeypatch.setattr(routes, "load_state_with_status", fake_load_state_with_status)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        status_response = await client.get("/status/s1")
        result_response = await client.get("/result/s1")

    assert status_response.json()["session_id"] == "s1"
    assert status_response.json()["status"] == "agentic_done"
    assert status_response.json()["result_ready"] is True
    assert status_response.json()["state"]["strategy_state"]["recommended_roles"] == [
        {
            "job_id": "job-1",
            "tier": "now_fit",
            "evidence_span_ids": ["job-1:skills:1"],
        }
    ]
    assert result_response.status_code == 200
    assert result_response.json()["state"]["session_id"] == "s1"
    assert result_response.json()["status"] == "agentic_done"


@pytest.mark.asyncio
async def test_run_match_task_uses_persisted_session_orchestrator(monkeypatch):
    from app.api import routes
    from app.state.schema import ResumeState, SharedState

    calls = []
    state = SharedState(
        session_id="s1",
        user_id="u1",
        resume_state=ResumeState(
            normalized_base_resume="Python analyst resume",
            original_evidence_spans=[{"span_id": "R001", "text": "Python"}],
        ),
    )

    async def fake_load_state(session_id):
        calls.append(("load_state", session_id))
        return state

    async def fake_save_state(saved_state, status):
        calls.append(("save_state", saved_state.session_id, status))

    async def fake_run_persisted_agentic_match_from_session(**kwargs):
        calls.append(("persisted_orchestrator", kwargs))

    monkeypatch.setattr(routes, "load_state", fake_load_state)
    monkeypatch.setattr(routes, "save_state", fake_save_state)
    monkeypatch.setattr(
        routes,
        "run_persisted_agentic_match_from_session",
        fake_run_persisted_agentic_match_from_session,
        raising=False,
    )

    await routes._run_match_task(
        session_id="s1",
        user_goal_text="Find analyst roles",
        top_k=3,
        include_raptor=True,
    )

    assert calls == [
        ("load_state", "s1"),
        ("save_state", "s1", "match_running"),
        (
            "persisted_orchestrator",
            {
                "session_id": "s1",
                "user_goal_text": "Find analyst roles",
                "top_k": 3,
                "include_raptor": True,
            },
        ),
    ]


@pytest.mark.asyncio
async def test_feedback_is_written_by_session_id(monkeypatch):
    from app.api.main import app
    from app.api import routes

    calls = []

    async def fake_add_feedback(**kwargs):
        calls.append(kwargs)
        return 42

    async def fake_process_feedback_closure_for_session(*, session_id, feedback):
        calls.append(("closure", session_id, feedback))
        return {
            "case_written": True,
            "soft_preference_updates": {"case_target_roles": ["Data Analyst"]},
        }

    monkeypatch.setattr(routes, "add_feedback", fake_add_feedback)
    monkeypatch.setattr(
        routes,
        "process_feedback_closure_for_session",
        fake_process_feedback_closure_for_session,
        raising=False,
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/feedback",
            json={
                "session_id": "s1",
                "job_id": "job-1",
                "outcome": "interview",
                "reason": "good match",
                "user_rating": 5,
                "idempotency_key": "feedback-request-1",
            },
        )

    assert response.status_code == 202
    assert response.json() == {
        "session_id": "s1",
        "feedback_id": 42,
        "status": "feedback_recorded",
        "closure_status": "processed",
        "case_written": True,
        "case_id": None,
        "soft_preference_updates": {"case_target_roles": ["Data Analyst"]},
    }
    assert calls == [
        {
            "session_id": "s1",
            "job_id": "job-1",
            "outcome": "interview",
            "reason": "good match",
            "user_rating": 5,
            "idempotency_key": "feedback-request-1",
        },
        (
            "closure",
            "s1",
            {
                "feedback_id": 42,
                "job_id": "job-1",
                "outcome": "interview",
                "reason": "good match",
                "user_rating": 5,
                "idempotency_key": "feedback-request-1",
            },
        ),
    ]


@pytest.mark.asyncio
async def test_feedback_returns_skipped_when_closure_rejects_feedback(monkeypatch):
    from app.api.main import app
    from app.api import routes

    async def fake_add_feedback(**kwargs):
        return 43

    async def fake_process_feedback_closure_for_session(*, session_id, feedback):
        assert session_id == "s1"
        assert feedback["feedback_id"] == 43
        return {"case_written": False, "soft_preference_updates": {}}

    monkeypatch.setattr(routes, "add_feedback", fake_add_feedback)
    monkeypatch.setattr(
        routes,
        "process_feedback_closure_for_session",
        fake_process_feedback_closure_for_session,
        raising=False,
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/feedback",
            json={"session_id": "s1", "job_id": "job-1", "outcome": "rejected"},
        )

    assert response.status_code == 202
    assert response.json() == {
        "session_id": "s1",
        "feedback_id": 43,
        "status": "feedback_recorded",
        "closure_status": "skipped",
        "case_written": False,
        "case_id": None,
        "soft_preference_updates": {},
    }


@pytest.mark.asyncio
async def test_feedback_rejects_invalid_outcome_with_422(monkeypatch):
    from app.api.main import app
    from app.api import routes

    async def fail_add_feedback(**kwargs):
        raise AssertionError("invalid outcome must fail request validation")

    monkeypatch.setattr(routes, "add_feedback", fail_add_feedback)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/feedback",
            json={"session_id": "s1", "job_id": "job-1", "outcome": "maybe"},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_feedback_response_preserves_partial_case_write_truth(monkeypatch):
    from app.api.main import app
    from app.api import routes

    async def fake_add_feedback(**kwargs):
        return 45

    async def fake_process_feedback_closure_for_session(*, session_id, feedback):
        return {
            "closure_status": "error",
            "error_code": "similar_case_search_failed",
            "case_written": True,
            "case": {"case_id": "feedback-case-45"},
            "soft_preference_updates": {},
        }

    monkeypatch.setattr(routes, "add_feedback", fake_add_feedback)
    monkeypatch.setattr(
        routes,
        "process_feedback_closure_for_session",
        fake_process_feedback_closure_for_session,
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/feedback",
            json={"session_id": "s1", "job_id": "job-1", "outcome": "offer"},
        )

    assert response.status_code == 202
    assert response.json() == {
        "session_id": "s1",
        "feedback_id": 45,
        "status": "feedback_recorded",
        "closure_status": "error",
        "case_written": True,
        "case_id": "feedback-case-45",
        "soft_preference_updates": {},
        "error_code": "similar_case_search_failed",
    }


@pytest.mark.asyncio
async def test_feedback_returns_error_after_durable_write_when_closure_fails(monkeypatch):
    from app.api.main import app
    from app.api import routes
    from app.state.schema import SharedState

    state = SharedState(session_id="s1", user_id="u1")
    state.feedback_state.user_feedback = [
        {"feedback_id": 44, "job_id": "job-1", "outcome": "offer"}
    ]
    atomic_mutations = []

    async def fake_add_feedback(**kwargs):
        return 44

    async def fake_process_feedback_closure_for_session(*, session_id, feedback):
        raise RuntimeError("case storage unavailable")

    async def fake_mutate_state_atomically(*, session_id, mutator):
        assert session_id == "s1"
        atomic_mutations.append(mutator)
        mutator(state)

    monkeypatch.setattr(routes, "add_feedback", fake_add_feedback)
    monkeypatch.setattr(
        routes,
        "process_feedback_closure_for_session",
        fake_process_feedback_closure_for_session,
        raising=False,
    )
    monkeypatch.setattr(
        routes,
        "mutate_state_atomically",
        fake_mutate_state_atomically,
        raising=False,
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/feedback",
            json={"session_id": "s1", "job_id": "job-1", "outcome": "offer"},
        )

    assert response.status_code == 202
    assert response.json() == {
        "session_id": "s1",
        "feedback_id": 44,
        "status": "feedback_recorded",
        "closure_status": "error",
        "case_written": False,
        "case_id": None,
        "soft_preference_updates": {},
        "error_code": "feedback_closure_failed",
    }
    assert len(atomic_mutations) == 1
    assert state.supervisor_log[-1]["stage"] == "feedback_closure_error"
    assert "case storage unavailable" not in str(state.model_dump())
    assert state.feedback_state.user_feedback[0]["closure_status"] == "error"
