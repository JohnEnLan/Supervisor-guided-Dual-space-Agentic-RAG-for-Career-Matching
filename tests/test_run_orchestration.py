from datetime import UTC, datetime

import pytest

from app.domain.match_brief import create_match_brief
from app.domain.run import MatchRun, RunStatus
from app.state.schema import ResumeState, SharedState


@pytest.mark.asyncio
async def test_run_orchestrator_keeps_approved_hard_constraints_locked(monkeypatch) -> None:
    from app.agents import orchestrator

    brief = create_match_brief(
        career_goal="Find evidence-grounded data analyst roles",
        hard_constraints={"locations": ["Birmingham"], "is_open": True},
        soft_preferences={"preferred_role_clusters": ["data"]},
        avoid_roles=["sales"],
        result_count=5,
        plan_version=1,
    )
    now = datetime.now(UTC)
    run = MatchRun(
        run_id="run-1",
        session_id="session-1",
        status=RunStatus.QUEUED,
        approved_plan=brief.model_dump(mode="json"),
        plan_version=1,
        created_at=now,
        updated_at=now,
    )
    state = SharedState(
        session_id="session-1",
        user_id="private-user",
        resume_state=ResumeState(
            skills=["Python"], normalized_base_resume="Python analyst"
        ),
    )
    captured: dict = {}

    async def fake_get_run(**_kwargs):
        return run

    async def no_op(*_args, **_kwargs):
        return None

    async def load_snapshot(**_kwargs):
        return state.model_dump(mode="json")

    async def intent(current, _goal):
        current.career_state.hard_constraints = {"locations": ["London"]}
        return current

    async def matching(current, *, retrieval_plan, search_fn):
        captured["retrieval_plan"] = retrieval_plan
        return current

    async def strategy(current):
        return current

    async def verify(_current):
        return {"reretrieval_loop_requested": False}

    async def snapshot(*, state_snapshot, **_kwargs):
        captured["state_snapshot"] = state_snapshot

    monkeypatch.setattr(orchestrator, "get_run", fake_get_run)
    monkeypatch.setattr(orchestrator, "transition_run", no_op)
    monkeypatch.setattr(orchestrator, "update_run_stage", no_op)
    monkeypatch.setattr(orchestrator, "append_event", no_op)
    monkeypatch.setattr(orchestrator, "load_state_snapshot", load_snapshot)
    monkeypatch.setattr(orchestrator, "run_intent_agent", intent)
    monkeypatch.setattr(orchestrator, "run_matching_agent", matching)
    monkeypatch.setattr(orchestrator, "run_strategy_agent", strategy)
    monkeypatch.setattr(orchestrator, "final_verification", verify)
    monkeypatch.setattr(orchestrator, "save_state", no_op)
    monkeypatch.setattr(orchestrator, "save_state_snapshot", snapshot)
    monkeypatch.setattr(orchestrator, "save_run_result", no_op)

    await orchestrator.run_persisted_agentic_match_run(run_id="run-1")

    assert captured["retrieval_plan"]["hard_constraints"] == brief.hard_constraints
    assert captured["state_snapshot"]["career_state"]["hard_constraints"] == (
        brief.hard_constraints
    )
