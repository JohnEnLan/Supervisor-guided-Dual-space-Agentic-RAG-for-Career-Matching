from datetime import UTC, datetime

import pytest

from app.domain.match_brief import create_match_brief
from app.domain.run import MatchRun, RunStage, RunStatus
from app.state.schema import CareerState, ResumeState, SharedState


@pytest.mark.asyncio
async def test_supervisor_harness_surrounds_all_agents_and_publication(monkeypatch) -> None:
    from app.agents import orchestrator

    state = SharedState(
        session_id="session-harness",
        user_id="private-user",
        resume_state=ResumeState(
            normalized_base_resume="Python data analyst",
            original_evidence_spans=[
                {"span_id": "R001", "text": "Built a Python dashboard."}
            ],
        ),
    )
    calls: list[str] = []

    async def intent(current, goal):
        calls.append("intent")
        current.career_state.current_goal = [goal]
        return current

    async def planning(
        current, *, user_goal_text, default_top_k, include_raptor
    ):
        del current, user_goal_text, include_raptor
        calls.append("planning")
        return {
            "hard_constraints": {},
            "soft_prefs": {},
            "top_k": default_top_k,
            "include_raptor": False,
        }

    async def matching(current, *, retrieval_plan, search_fn):
        del retrieval_plan, search_fn
        calls.append("matching")
        current.retrieval_state.candidate_job_ids = ["job-1"]
        current.retrieval_state.evidence_span_ids = ["job-1:required_skills:1"]
        current.retrieval_state.ranking_scores = [
            {
                "job_id": "job-1",
                "evidence_span_ids": ["job-1:required_skills:1"],
                "evidence_spans": [
                    {
                        "evidence_span_id": "job-1:required_skills:1",
                        "content": "Python required",
                    }
                ],
            }
        ]
        current.strategy_state.recommended_roles = [
            {
                "job_id": "job-1",
                "tier": "now_fit",
                "evidence_span_ids": ["job-1:required_skills:1"],
            }
        ]
        return current

    async def strategy(current):
        calls.append("strategy")
        return current

    async def verify(_current):
        calls.append("verification")
        return {
            "hard_filter_violations": [],
            "missing_evidence": [],
            "fabrication_risks": [],
            "reretrieval_loop_requested": False,
        }

    monkeypatch.setattr(orchestrator, "run_intent_agent", intent)
    monkeypatch.setattr(orchestrator, "plan_retrieval", planning)
    monkeypatch.setattr(orchestrator, "run_matching_agent", matching)
    monkeypatch.setattr(orchestrator, "run_strategy_agent", strategy)
    monkeypatch.setattr(orchestrator, "final_verification", verify)

    result = await orchestrator.run_agentic_match_from_state(
        state,
        user_goal_text="Find data analyst roles",
        top_k=5,
    )

    checkpoints = [
        entry["checkpoint"]
        for entry in result.state.supervisor_log
        if entry.get("stage") == "supervisor_checkpoint"
    ]
    assert checkpoints == [
        "intent_input",
        "intent_output",
        "matching_input",
        "matching_output",
        "strategy_input",
        "strategy_output",
        "publication_gate",
    ]
    assert calls == ["intent", "planning", "matching", "strategy", "verification"]


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
    monkeypatch.setattr(orchestrator, "save_run_metrics", no_op)

    await orchestrator.run_persisted_agentic_match_run(run_id="run-1")

    assert captured["retrieval_plan"]["hard_constraints"] == brief.hard_constraints
    assert captured["state_snapshot"]["career_state"]["hard_constraints"] == (
        brief.hard_constraints
    )


@pytest.mark.asyncio
async def test_consulted_run_skips_duplicate_intent_agent(monkeypatch) -> None:
    from app.agents import orchestrator

    brief = create_match_brief(
        career_goal="Find evidence-grounded data analyst roles",
        hard_constraints={"locations": ["Birmingham"]},
        soft_preferences={},
        avoid_roles=[],
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
        career_state=CareerState(intent_consulted=True),
    )
    transitions: list[RunStage | None] = []
    stages: list[RunStage] = []
    captured_metrics = []

    async def fake_get_run(**_kwargs):
        return run

    async def transition(*, stage=None, **_kwargs):
        transitions.append(stage)
        return run

    async def update(*, stage, **_kwargs):
        stages.append(stage)

    async def load_snapshot(**_kwargs):
        return state.model_dump(mode="json")

    async def forbidden_intent(*_args, **_kwargs):
        raise AssertionError("consulted run called Intent Agent twice")

    async def same_state(current, **_kwargs):
        return current

    async def verify(_current):
        return {"reretrieval_loop_requested": False}

    async def no_op(*_args, **_kwargs):
        return None

    async def capture_metrics(*, run_id, metrics):
        assert run_id == "run-1"
        captured_metrics.append(metrics)
        raise RuntimeError("monitoring table unavailable")

    monkeypatch.setattr(orchestrator, "get_run", fake_get_run)
    monkeypatch.setattr(orchestrator, "transition_run", transition)
    monkeypatch.setattr(orchestrator, "update_run_stage", update)
    monkeypatch.setattr(orchestrator, "append_event", no_op)
    monkeypatch.setattr(orchestrator, "load_state_snapshot", load_snapshot)
    monkeypatch.setattr(orchestrator, "run_intent_agent", forbidden_intent)
    monkeypatch.setattr(orchestrator, "run_matching_agent", same_state)
    monkeypatch.setattr(orchestrator, "run_strategy_agent", same_state)
    monkeypatch.setattr(orchestrator, "final_verification", verify)
    monkeypatch.setattr(orchestrator, "save_state", no_op)
    monkeypatch.setattr(orchestrator, "save_state_snapshot", no_op)
    monkeypatch.setattr(orchestrator, "save_run_result", no_op)
    monkeypatch.setattr(
        orchestrator,
        "save_run_metrics",
        capture_metrics,
        raising=False,
    )

    await orchestrator.run_persisted_agentic_match_run(run_id="run-1")

    assert transitions == [RunStage.INTENT]
    assert stages[0] is RunStage.RETRIEVAL
    assert len(captured_metrics) == 1
    assert "finalization" in captured_metrics[0].stage_durations_ms
