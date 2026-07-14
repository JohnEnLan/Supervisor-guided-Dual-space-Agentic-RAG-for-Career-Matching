import asyncio
import json
import os
from time import perf_counter

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


@pytest.mark.asyncio
async def test_twenty_v1_runs_keep_snapshots_and_results_isolated(
    monkeypatch,
):
    from datetime import UTC, datetime

    from app.agents import orchestrator
    from app.domain.match_brief import create_match_brief
    from app.domain.run import MatchRun, RunStatus
    from app.state.schema import ResumeState, SharedState

    from app.evaluation.load_validation import summarize_latencies

    run_specs = {
        f"run-{index:02d}": (
            f"session-{index % 10:02d}",
            (
                f"Target Data Analyst at Company {index}"
                if index % 2 == 0
                else f"Explore evidence-backed direction {index}"
            ),
        )
        for index in range(20)
    }
    now = datetime.now(UTC)
    runs = {}
    snapshots = {}
    results = {}
    for run_id, (session_id, goal) in run_specs.items():
        brief = create_match_brief(
            career_goal=goal,
            hard_constraints={"run_scope": run_id},
            soft_preferences={},
            avoid_roles=[],
            result_count=5,
            plan_version=1,
        )
        runs[run_id] = MatchRun(
            run_id=run_id,
            session_id=session_id,
            status=RunStatus.QUEUED,
            approved_plan=brief.model_dump(mode="json"),
            plan_version=1,
            created_at=now,
            updated_at=now,
        )
        snapshots[run_id] = SharedState(
            session_id=session_id,
            user_id=f"user-{session_id}",
            resume_state=ResumeState(
                normalized_base_resume=f"resume for {session_id}"
            ),
        ).model_dump(mode="json")

    async def get_run(*, run_id):
        return runs[run_id].model_copy(deep=True)

    async def load_snapshot(*, run_id):
        return snapshots[run_id]

    async def no_op(*_args, **_kwargs):
        await asyncio.sleep(0)

    async def fail_shared_session_save(*_args, **_kwargs):
        raise AssertionError(
            "run-scoped execution must not overwrite shared session state"
        )

    async def intent(state, _goal):
        await asyncio.sleep(0)
        return state

    async def matching(state, *, retrieval_plan, search_fn):
        run_id = retrieval_plan["hard_constraints"]["run_scope"]
        state.strategy_state.recommended_roles = [
            {
                "job_id": f"job-{run_id}",
                "tier": "now_fit",
                "match_explanation": f"evidence for {run_id}",
                "evidence_span_ids": [f"{run_id}:skills:1"],
                "evidence_spans": [
                    {
                        "evidence_span_id": f"{run_id}:skills:1",
                        "content": f"JD evidence for {run_id}",
                    }
                ],
            }
        ]
        await asyncio.sleep(0)
        return state

    async def strategy(state):
        return state

    async def verify(_state):
        return {"reretrieval_loop_requested": False}

    async def save_snapshot(*, run_id, state_snapshot):
        snapshots[run_id] = state_snapshot

    async def save_result(*, run_id, result_snapshot, warning_codes):
        results[run_id] = result_snapshot

    monkeypatch.setattr(orchestrator, "get_run", get_run)
    monkeypatch.setattr(orchestrator, "load_state_snapshot", load_snapshot)
    monkeypatch.setattr(orchestrator, "transition_run", no_op)
    monkeypatch.setattr(orchestrator, "update_run_stage", no_op)
    monkeypatch.setattr(orchestrator, "append_event", no_op)
    monkeypatch.setattr(orchestrator, "run_intent_agent", intent)
    monkeypatch.setattr(orchestrator, "run_matching_agent", matching)
    monkeypatch.setattr(orchestrator, "run_strategy_agent", strategy)
    monkeypatch.setattr(orchestrator, "final_verification", verify)
    monkeypatch.setattr(orchestrator, "save_state", fail_shared_session_save)
    monkeypatch.setattr(orchestrator, "save_state_snapshot", save_snapshot)
    monkeypatch.setattr(orchestrator, "save_run_result", save_result)
    monkeypatch.setattr(orchestrator, "save_run_metrics", no_op)

    active = 0
    peak_active = 0
    active_lock = asyncio.Lock()

    async def timed_run(run_id: str) -> float:
        nonlocal active, peak_active
        async with active_lock:
            active += 1
            peak_active = max(peak_active, active)
        started = perf_counter()
        try:
            await orchestrator.run_persisted_agentic_match_run(run_id=run_id)
            return (perf_counter() - started) * 1000
        finally:
            async with active_lock:
                active -= 1

    batch_started = perf_counter()
    latencies_ms = await asyncio.gather(
        *[timed_run(run_id) for run_id in run_specs]
    )
    batch_elapsed_ms = (perf_counter() - batch_started) * 1000
    summary = summarize_latencies(
        list(latencies_ms),
        success_count=len(results),
        elapsed_ms=batch_elapsed_ms,
        peak_concurrency=peak_active,
    )

    assert set(results) == set(run_specs)
    assert summary.request_count == 20
    assert summary.success_count == 20
    assert summary.failure_count == 0
    assert summary.peak_concurrency == 20
    for run_id, (session_id, _goal) in run_specs.items():
        assert snapshots[run_id]["session_id"] == session_id
        assert results[run_id]["recommended_roles"][0]["job_id"] == f"job-{run_id}"
        assert run_id in results[run_id]["recommended_roles"][0][
            "concise_explanation"
        ]

    print("RUN_LOAD_SUMMARY " + json.dumps(summary.as_public_dict(), sort_keys=True))


@pytest.mark.asyncio
async def test_two_hundred_status_reads_have_no_server_errors(monkeypatch):
    from datetime import UTC, datetime

    from app.api.main import app
    from app.api.v1 import runs as run_routes
    from app.domain.run import MatchRun, RunStage, RunStatus
    from app.evaluation.load_validation import summarize_latencies

    now = datetime.now(UTC)

    async def get_run(*, run_id: str):
        await asyncio.sleep(0.005)
        return MatchRun(
            run_id=run_id,
            session_id=f"session-{run_id}",
            status=RunStatus.COMPLETED,
            stage=RunStage.FINALIZATION,
            plan_version=1,
            plan_hash="a" * 64,
            created_at=now,
            updated_at=now,
            started_at=now,
            finished_at=now,
        )

    monkeypatch.setattr(run_routes, "get_run", get_run)

    limit = asyncio.Semaphore(20)
    active = 0
    peak_active = 0
    active_lock = asyncio.Lock()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:

        async def timed_status(index: int):
            nonlocal active, peak_active
            async with limit:
                async with active_lock:
                    active += 1
                    peak_active = max(peak_active, active)
                started = perf_counter()
                try:
                    response = await client.get(f"/api/v1/runs/load-{index}/status")
                    return response, (perf_counter() - started) * 1000
                finally:
                    async with active_lock:
                        active -= 1

        batch_started = perf_counter()
        measurements = await asyncio.gather(
            *[timed_status(index) for index in range(200)]
        )
        batch_elapsed_ms = (perf_counter() - batch_started) * 1000

    responses = [response for response, _latency in measurements]
    latencies_ms = [latency for _response, latency in measurements]
    summary = summarize_latencies(
        latencies_ms,
        success_count=sum(response.status_code == 200 for response in responses),
        elapsed_ms=batch_elapsed_ms,
        peak_concurrency=peak_active,
    )

    assert all(response.status_code == 200 for response in responses)
    assert {response.json()["run_id"] for response in responses} == {
        f"load-{index}" for index in range(200)
    }
    assert summary.request_count == 200
    assert summary.failure_count == 0
    assert 1 < summary.peak_concurrency <= 20
    print("READ_LOAD_SUMMARY " + json.dumps(summary.as_public_dict(), sort_keys=True))


@pytest.mark.asyncio
async def test_twenty_competing_executes_queue_a_run_once(monkeypatch):
    from datetime import UTC, datetime

    from app.api.main import app
    from app.api.v1 import runs as run_routes
    from app.db.run_store import RunConflict
    from app.domain.run import MatchRun, RunStatus

    now = datetime.now(UTC)
    queue_lock = asyncio.Lock()
    queued = False
    queue_successes = 0

    async def queue_run(*, run_id: str, plan_version: int, plan_hash: str):
        nonlocal queued, queue_successes
        assert run_id == "run-race"
        assert plan_version == 1
        assert plan_hash == "b" * 64
        await asyncio.sleep(0)
        async with queue_lock:
            if queued:
                raise RunConflict("run must be plan_ready with a matching plan")
            queued = True
            queue_successes += 1
            return MatchRun(
                run_id=run_id,
                session_id="session-race",
                status=RunStatus.QUEUED,
                plan_version=plan_version,
                plan_hash=plan_hash,
                created_at=now,
                updated_at=now,
            )

    async def no_op_execution(*, run_id: str):
        assert run_id == "run-race"

    monkeypatch.setattr(run_routes, "queue_run", queue_run)
    monkeypatch.setattr(
        run_routes,
        "run_persisted_agentic_match_run",
        no_op_execution,
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        responses = await asyncio.gather(
            *[
                client.post(
                    "/api/v1/runs/run-race/execute",
                    json={"plan_version": 1, "plan_hash": "b" * 64},
                )
                for _index in range(20)
            ]
        )

    assert [response.status_code for response in responses].count(202) == 1
    assert [response.status_code for response in responses].count(409) == 19
    assert queue_successes == 1
