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

    monkeypatch.setattr(routes, "add_feedback", fake_add_feedback)

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
            },
        )

    assert response.status_code == 202
    assert response.json() == {
        "session_id": "s1",
        "feedback_id": 42,
        "status": "feedback_recorded",
    }
    assert calls == [
        {
            "session_id": "s1",
            "job_id": "job-1",
            "outcome": "interview",
            "reason": "good match",
            "user_rating": 5,
        }
    ]
