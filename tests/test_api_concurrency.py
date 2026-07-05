import asyncio
import os

import httpx
import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")
os.environ.setdefault("QWEN_API_KEY", "sk-test")


@pytest.mark.asyncio
async def test_concurrent_match_sessions_keep_state_and_status_isolated(monkeypatch):
    from app.api.main import app
    from app.api import routes
    from app.state.schema import ResumeState, SharedState, StrategyState

    session_ids = ("day14-a", "day14-b", "day14-c")
    store = {
        session_id: SharedState(
            session_id=session_id,
            user_id=f"user-{session_id}",
            resume_state=ResumeState(
                normalized_base_resume=f"{session_id} Python analyst resume",
                original_evidence_spans=[
                    {"span_id": f"{session_id}-R001", "text": "Python analyst"}
                ],
            ),
        )
        for session_id in session_ids
    }
    statuses = {session_id: "resume_ready" for session_id in session_ids}
    save_events = []
    lock = asyncio.Lock()

    async def fake_load_state_with_status(session_id):
        async with lock:
            state = store.get(session_id)
            if state is None:
                return None
            return state.model_copy(deep=True), statuses[session_id]

    async def fake_load_state(session_id):
        async with lock:
            state = store.get(session_id)
            return None if state is None else state.model_copy(deep=True)

    async def fake_save_state(state, status):
        await asyncio.sleep(0)
        async with lock:
            store[state.session_id] = state.model_copy(deep=True)
            statuses[state.session_id] = status
            save_events.append((state.session_id, status))

    async def fake_run_persisted_agentic_match_from_session(**kwargs):
        session_id = kwargs["session_id"]
        await asyncio.sleep(0)
        state = await fake_load_state(session_id)
        assert state is not None
        assert state.session_id == session_id
        state.strategy_state = StrategyState(
            recommended_roles=[
                {
                    "job_id": f"{session_id}-job",
                    "tier": "now_fit",
                    "match_evidence": [f"{session_id}-evidence"],
                    "evidence_span_ids": [f"{session_id}:skills:1"],
                }
            ]
        )
        state.supervisor_log.append(
            {"stage": "day14_concurrency_self_test", "session_id": session_id}
        )
        await fake_save_state(state, "agentic_done")

    monkeypatch.setattr(routes, "load_state_with_status", fake_load_state_with_status)
    monkeypatch.setattr(routes, "load_state", fake_load_state)
    monkeypatch.setattr(routes, "save_state", fake_save_state)
    monkeypatch.setattr(
        routes,
        "run_persisted_agentic_match_from_session",
        fake_run_persisted_agentic_match_from_session,
        raising=False,
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        responses = await asyncio.gather(
            *[
                client.post(
                    "/match",
                    json={
                        "session_id": session_id,
                        "user_goal_text": f"Find roles for {session_id}",
                        "top_k": 3,
                    },
                )
                for session_id in session_ids
            ]
        )
        status_responses = await asyncio.gather(
            *[client.get(f"/status/{session_id}") for session_id in session_ids]
        )

    assert [response.status_code for response in responses] == [202, 202, 202]
    assert {response.json()["session_id"] for response in responses} == set(session_ids)

    for session_id in session_ids:
        assert (session_id, "match_queued") in save_events
        assert (session_id, "match_running") in save_events
        assert statuses[session_id] == "agentic_done"

    seen_jobs = set()
    for response in status_responses:
        assert response.status_code == 200
        payload = response.json()
        session_id = payload["session_id"]
        role = payload["state"]["strategy_state"]["recommended_roles"][0]
        assert payload["status"] == "agentic_done"
        assert payload["result_ready"] is True
        assert payload["state"]["session_id"] == session_id
        assert role["job_id"] == f"{session_id}-job"
        assert role["match_evidence"] == [f"{session_id}-evidence"]
        seen_jobs.add(role["job_id"])

    assert seen_jobs == {f"{session_id}-job" for session_id in session_ids}
