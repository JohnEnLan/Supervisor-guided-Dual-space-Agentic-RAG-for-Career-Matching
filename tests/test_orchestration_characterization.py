from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime
import json
from typing import Any

import pytest

from app.domain.match_brief import MatchBrief, create_match_brief
from app.domain.run import MatchRun, RunStage, RunStatus
from app.state.schema import CareerState, ResumeState, SharedState


CHECKPOINT_ORDER = [
    "intent_input",
    "intent_output",
    "matching_input",
    "matching_output",
    "strategy_input",
    "strategy_output",
    "publication_gate",
]


@pytest.fixture(params=["legacy", "langgraph"], ids=["legacy", "langgraph"])
def orchestration_implementation(request) -> str:
    return str(request.param)


async def _run_characterized_implementation(
    implementation: str,
    monkeypatch,
    *,
    run_id: str,
):
    from app.agents import orchestrator

    if implementation == "legacy":
        return await orchestrator.run_persisted_agentic_match_run(run_id=run_id)

    from langgraph.checkpoint.memory import MemorySaver

    from app.api.v1 import runs
    from app.graph.runner import run_graph_match

    async def graph_with_memory(*, run_id: str):
        return await run_graph_match(
            run_id=run_id,
            checkpointer=MemorySaver(),
        )

    monkeypatch.setattr(runs, "run_graph_match", graph_with_memory)
    monkeypatch.setattr(
        runs.settings,
        "langgraph_orchestrator_enabled",
        True,
    )
    executor = runs._select_run_executor()
    assert executor is graph_with_memory
    return await executor(run_id=run_id)


def _brief(*, soft_preferences: dict[str, Any] | None = None) -> MatchBrief:
    return create_match_brief(
        career_goal="Find evidence-grounded data analyst roles in Birmingham",
        hard_constraints={"locations": ["Birmingham"], "is_open": True},
        soft_preferences=soft_preferences or {},
        avoid_roles=["sales"],
        result_count=3,
        plan_version=2,
    )


def _run(brief: MatchBrief) -> MatchRun:
    now = datetime.now(UTC)
    return MatchRun(
        run_id="characterization-run",
        session_id="characterization-session",
        status=RunStatus.QUEUED,
        approved_plan=brief.model_dump(mode="json"),
        plan_version=brief.plan_version,
        plan_hash=brief.plan_hash,
        created_at=now,
        updated_at=now,
    )


def _state(*, intent_consulted: bool = False) -> SharedState:
    return SharedState(
        session_id="characterization-session",
        user_id="private-characterization-user",
        resume_state=ResumeState(
            skills=["Python", "SQL"],
            normalized_base_resume="Python data analyst in Birmingham.",
            original_evidence_spans=[
                {
                    "span_id": "R-001",
                    "text": "Built a Python hiring dashboard.",
                }
            ],
        ),
        career_state=CareerState(intent_consulted=intent_consulted),
    )


def _populate_matching_state(
    state: SharedState,
    *,
    candidate_count: int = 1,
) -> SharedState:
    job_ids = [f"job-{index}" for index in range(1, candidate_count + 1)]
    state.retrieval_state.candidate_job_ids = job_ids
    state.retrieval_state.evidence_span_ids = [
        f"{job_id}:required_skills:1" for job_id in job_ids
    ]
    state.retrieval_state.ranking_scores = [
        {
            "job_id": job_id,
            "score": 1 - index / 100,
            "evidence_span_ids": [f"{job_id}:required_skills:1"],
            "evidence_spans": [
                {
                    "evidence_span_id": f"{job_id}:required_skills:1",
                    "field": "required_skills",
                    "content": "Python and SQL required.",
                }
            ],
        }
        for index, job_id in enumerate(job_ids)
    ]
    return state


def _populate_strategy_state(state: SharedState) -> SharedState:
    state.strategy_state.recommended_roles = [
        {
            "job_id": "job-1",
            "title": "Data Analyst",
            "location": "Birmingham",
            "tier": "now_fit",
            "hard_constraint_passed": True,
            "evidence_span_ids": ["job-1:required_skills:1"],
            "resume_evidence_span_ids": ["R-001"],
            "explicit_explanation": "Python and SQL align with the JD.",
        }
    ]
    return state


def _verification_payload(
    *,
    hard_filter_violations: list[dict[str, Any]] | None = None,
    needs_reretrieval: bool = False,
) -> str:
    return json.dumps(
        {
            "hard_filter_violations": hard_filter_violations or [],
            "missing_evidence": [],
            "fabrication_risks": [],
            "too_few_results": {},
            "needs_reretrieval": needs_reretrieval,
            "needs_repair": False,
        }
    )


def _checkpoint_entries(state: SharedState) -> list[dict[str, Any]]:
    return [
        entry
        for entry in state.supervisor_log
        if entry.get("stage") == "supervisor_checkpoint"
    ]


def _snapshot_delta_tokens(snapshots: list[dict[str, Any]]) -> list[list[str]]:
    previous_length = 0
    deltas: list[list[str]] = []
    for snapshot in snapshots:
        log = snapshot["supervisor_log"]
        entries = log[previous_length:]
        previous_length = len(log)
        tokens = []
        for entry in entries:
            if entry.get("stage") == "supervisor_checkpoint":
                tokens.append(f"checkpoint:{entry['checkpoint']}")
            elif entry.get("stage") == "public_stage_duration":
                tokens.append(f"duration:{entry['stage_name']}")
            else:
                tokens.append(str(entry.get("stage")))
        deltas.append(tokens)
    return deltas


class PersistedRunRecorder:
    def __init__(self, run: MatchRun, initial_state: SharedState) -> None:
        self.run = run
        self.initial_state = initial_state
        self.status = run.status
        self.stage = run.stage
        self.status_history = [run.status]
        self.stage_history: list[RunStage] = []
        self.timeline: list[str] = []
        self.snapshots: list[dict[str, Any]] = []
        self.save_result_statuses: list[RunStatus] = []
        self.saved_metrics = []
        self.transition_error_codes: list[str | None] = []

    def install(self, monkeypatch, orchestrator) -> None:
        monkeypatch.setattr(orchestrator, "get_run", self.get_run)
        monkeypatch.setattr(orchestrator, "transition_run", self.transition_run)
        monkeypatch.setattr(orchestrator, "update_run_stage", self.update_run_stage)
        monkeypatch.setattr(orchestrator, "append_event", self.append_event)
        monkeypatch.setattr(
            orchestrator,
            "load_state_snapshot",
            self.load_state_snapshot,
        )
        monkeypatch.setattr(
            orchestrator,
            "save_state_snapshot",
            self.save_state_snapshot,
        )
        monkeypatch.setattr(orchestrator, "save_run_result", self.save_run_result)
        monkeypatch.setattr(orchestrator, "save_run_metrics", self.save_run_metrics)

    async def get_run(self, *, run_id: str) -> MatchRun:
        assert run_id == self.run.run_id
        return self.run

    async def transition_run(
        self,
        *,
        run_id: str,
        current_status: RunStatus,
        target_status: RunStatus,
        stage: RunStage | None = None,
        error_code: str | None = None,
    ) -> MatchRun:
        assert run_id == self.run.run_id
        assert self.status is current_status
        self.transition_error_codes.append(error_code)
        self.timeline.append(
            f"transition:{current_status.value}->{target_status.value}"
        )
        self.status = target_status
        self.status_history.append(target_status)
        if stage is not None:
            self.stage = stage
            self.stage_history.append(stage)
        return self.run.model_copy(
            update={"status": target_status, "stage": stage},
        )

    async def update_run_stage(self, *, run_id: str, stage: RunStage) -> None:
        assert run_id == self.run.run_id
        assert self.status is RunStatus.RUNNING
        self.timeline.append(f"stage:{stage.value}")
        self.stage = stage
        self.stage_history.append(stage)

    async def append_event(self, *, event_type: str, **_kwargs) -> None:
        self.timeline.append(f"event:{event_type}")

    async def load_state_snapshot(self, *, run_id: str) -> dict[str, Any]:
        assert run_id == self.run.run_id
        self.timeline.append("load:initial_snapshot")
        return self.initial_state.model_dump(mode="json")

    async def save_state_snapshot(
        self,
        *,
        run_id: str,
        state_snapshot: dict[str, Any],
    ) -> None:
        assert run_id == self.run.run_id
        assert self.status is RunStatus.RUNNING
        self.timeline.append("snapshot")
        self.snapshots.append(deepcopy(state_snapshot))

    async def save_run_result(
        self,
        *,
        run_id: str,
        result_snapshot: dict[str, Any],
        warning_codes: list[str],
    ) -> MatchRun:
        del result_snapshot
        assert run_id == self.run.run_id
        self.timeline.append("save_result")
        self.save_result_statuses.append(self.status)
        assert self.status is RunStatus.RUNNING
        self.status = (
            RunStatus.COMPLETED_WITH_WARNINGS
            if warning_codes
            else RunStatus.COMPLETED
        )
        self.status_history.append(self.status)
        return self.run.model_copy(
            update={"status": self.status, "stage": RunStage.FINALIZATION},
        )

    async def save_run_metrics(self, *, run_id: str, metrics) -> None:
        assert run_id == self.run.run_id
        self.timeline.append("metrics")
        self.saved_metrics.append(metrics)


@pytest.mark.asyncio
async def test_persisted_run_preserves_checkpoint_stage_snapshot_and_terminal_order(
    monkeypatch,
    orchestration_implementation,
) -> None:
    from app.agents import orchestrator
    from app.agents import supervisor

    brief = _brief()
    recorder = PersistedRunRecorder(_run(brief), _state())
    recorder.install(monkeypatch, orchestrator)

    async def intent(state: SharedState, goal: str) -> SharedState:
        recorder.timeline.append("node:intent")
        state.career_state.current_goal = [goal]
        return state

    async def matching(
        state: SharedState,
        *,
        retrieval_plan,
        search_fn,
    ) -> SharedState:
        del retrieval_plan, search_fn
        recorder.timeline.append("node:matching")
        return _populate_matching_state(state)

    async def strategy(state: SharedState) -> SharedState:
        recorder.timeline.append("node:strategy")
        return _populate_strategy_state(state)

    async def chat(*_args, **_kwargs) -> str:
        recorder.timeline.append("node:verification")
        return _verification_payload()

    monkeypatch.setattr(orchestrator, "run_intent_agent", intent)
    monkeypatch.setattr(orchestrator, "run_matching_agent", matching)
    monkeypatch.setattr(orchestrator, "run_strategy_agent", strategy)
    monkeypatch.setattr(supervisor.deepseek, "chat", chat)

    result = await _run_characterized_implementation(
        orchestration_implementation,
        monkeypatch,
        run_id=recorder.run.run_id,
    )

    checkpoints = _checkpoint_entries(result.state)
    assert [entry["checkpoint"] for entry in checkpoints] == CHECKPOINT_ORDER
    assert [entry["attempt"] for entry in checkpoints] == [1] * 7

    assert recorder.status_history == [
        RunStatus.QUEUED,
        RunStatus.RUNNING,
        RunStatus.COMPLETED,
    ]
    assert recorder.stage_history == [
        RunStage.INTENT,
        RunStage.RETRIEVAL,
        RunStage.STRATEGY,
        RunStage.VERIFICATION,
        RunStage.FINALIZATION,
    ]
    assert recorder.timeline.index("transition:queued->running") < (
        recorder.timeline.index("node:intent")
    )
    assert recorder.timeline.index("stage:retrieval") < recorder.timeline.index(
        "node:matching"
    )
    assert recorder.timeline.index("stage:strategy") < recorder.timeline.index(
        "node:strategy"
    )
    assert recorder.timeline.index("stage:verification") < (
        recorder.timeline.index("node:verification")
    )
    assert recorder.timeline.index("stage:finalization") < (
        recorder.timeline.index("save_result")
    )

    assert len(recorder.snapshots) == 5
    assert _snapshot_delta_tokens(recorder.snapshots) == [
        [
            "checkpoint:intent_input",
            "checkpoint:intent_output",
            "duration:intent",
            "approved_match_brief",
            "planning",
        ],
        [
            "checkpoint:matching_input",
            "checkpoint:matching_output",
            "duration:retrieval",
        ],
        [
            "checkpoint:strategy_input",
            "checkpoint:strategy_output",
            "duration:strategy",
        ],
        [
            "final_verification",
            "duration:verification",
            "checkpoint:publication_gate",
        ],
        ["duration:finalization"],
    ]

    approved_log = next(
        entry
        for entry in result.state.supervisor_log
        if entry.get("stage") == "approved_match_brief"
    )
    planning_log = next(
        entry
        for entry in result.state.supervisor_log
        if entry.get("stage") == "planning"
    )
    assert approved_log == {
        "stage": "approved_match_brief",
        "plan_version": brief.plan_version,
        "plan_hash": brief.plan_hash,
        "hard_constraints_locked": True,
    }
    assert planning_log == {
        "stage": "planning",
        "source": "approved_match_brief",
        "needs_clarification": False,
        "clarification_loop_used": 0,
        "retrieval_plan": {
            "hard_constraints": brief.hard_constraints,
            "soft_prefs": brief.soft_preferences,
            "top_k": brief.result_count,
            "include_raptor": False,
        },
    }

    assert recorder.save_result_statuses == [RunStatus.RUNNING]
    assert recorder.timeline.count("save_result") == 1
    assert len(recorder.saved_metrics) == 1


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


@pytest.mark.asyncio
async def test_reretrieval_work_is_charged_to_verification_and_logs_stay_ordered(
    monkeypatch,
    orchestration_implementation,
) -> None:
    from app.agents import orchestrator
    from app.agents import supervisor

    brief = _brief(soft_preferences={"work_mode": "hybrid"})
    recorder = PersistedRunRecorder(_run(brief), _state())
    recorder.install(monkeypatch, orchestrator)
    clock = FakeClock()
    monkeypatch.setattr(orchestrator, "perf_counter", clock)
    matching_calls = 0
    strategy_calls = 0
    verification_calls = 0

    async def intent(state: SharedState, goal: str) -> SharedState:
        state.career_state.current_goal = [goal]
        clock.advance(1)
        return state

    async def matching(
        state: SharedState,
        *,
        retrieval_plan,
        search_fn,
    ) -> SharedState:
        nonlocal matching_calls
        del retrieval_plan, search_fn
        matching_calls += 1
        clock.advance(2 if matching_calls == 1 else 7)
        return _populate_matching_state(state, candidate_count=3)

    async def strategy(state: SharedState) -> SharedState:
        nonlocal strategy_calls
        strategy_calls += 1
        clock.advance(3 if strategy_calls == 1 else 11)
        _populate_strategy_state(state)
        state.strategy_state.resume_revision_plan = [
            {
                "section": "experience",
                "suggestion": "Invent an unsupported achievement.",
                "evidence_span_ids": ["R-missing"],
            }
        ]
        return state

    async def chat(*_args, **_kwargs) -> str:
        nonlocal verification_calls
        verification_calls += 1
        clock.advance(5 if verification_calls == 1 else 13)
        if verification_calls == 1:
            return _verification_payload(
                hard_filter_violations=[
                    {
                        "job_id": "job-1",
                        "field": "visa",
                        "expected": "eligible",
                        "actual": "unknown",
                    }
                ],
                needs_reretrieval=True,
            )
        return _verification_payload()

    monkeypatch.setattr(orchestrator, "run_intent_agent", intent)
    monkeypatch.setattr(orchestrator, "run_matching_agent", matching)
    monkeypatch.setattr(orchestrator, "run_strategy_agent", strategy)
    monkeypatch.setattr(supervisor.deepseek, "chat", chat)

    result = await _run_characterized_implementation(
        orchestration_implementation,
        monkeypatch,
        run_id=recorder.run.run_id,
    )

    assert matching_calls == 2
    assert strategy_calls == 2
    assert verification_calls == 2
    assert len(recorder.snapshots) == 5

    durations = [
        entry
        for entry in result.state.supervisor_log
        if entry.get("stage") == "public_stage_duration"
    ]
    assert [entry["stage_name"] for entry in durations] == [
        "intent",
        "retrieval",
        "strategy",
        "verification",
        "finalization",
    ]
    assert [entry["duration_ms"] for entry in durations] == [
        1000,
        2000,
        3000,
        36000,
        0,
    ]

    audit_stages = [
        entry["stage"]
        for entry in result.state.supervisor_log
        if entry.get("stage")
        in {
            "approved_match_brief",
            "planning",
            "repair_loop",
            "final_verification",
            "reretrieval_loop",
        }
    ]
    assert audit_stages == [
        "approved_match_brief",
        "planning",
        "repair_loop",
        "final_verification",
        "reretrieval_loop",
        "final_verification",
    ]

    repair_log = next(
        entry
        for entry in result.state.supervisor_log
        if entry.get("stage") == "repair_loop"
    )
    reretrieval_log = next(
        entry
        for entry in result.state.supervisor_log
        if entry.get("stage") == "reretrieval_loop"
    )
    final_logs = [
        entry
        for entry in result.state.supervisor_log
        if entry.get("stage") == "final_verification"
    ]
    assert repair_log == {
        "stage": "repair_loop",
        "trigger": "final_verification",
        "reason": "unsupported_resume_advice",
        "max_loops": 1,
        "loop_used": 1,
        "repaired_resume_advice": 1,
        "repaired_implicit_claims": 0,
    }
    assert reretrieval_log["trigger"] == "final_verification"
    assert reretrieval_log["reason"] == "verification_requested"
    assert reretrieval_log["max_loops"] == 1
    assert reretrieval_log["loop_used"] == 1
    assert reretrieval_log["reretrieval_plan"] == {
        "hard_constraints": brief.hard_constraints,
        "soft_prefs": brief.soft_preferences,
        "top_k": brief.result_count,
        "include_raptor": False,
    }
    assert final_logs[0]["hard_filter_violations"] == [
        {
            "job_id": "job-1",
            "field": "visa",
            "expected": "eligible",
            "actual": "unknown",
        }
    ]
    assert final_logs[0]["repair_loop_used"] == 1
    assert final_logs[0]["reretrieval_loop_requested"] is True
    assert final_logs[0]["reretrieval_loop_used"] == 0
    assert final_logs[1]["hard_filter_violations"] == []
    assert final_logs[1]["repair_loop_used"] == 0
    assert final_logs[1]["reretrieval_loop_requested"] is False
    assert final_logs[1]["reretrieval_loop_used"] == 1

    checkpoint_attempts = [
        (entry["checkpoint"], entry["attempt"])
        for entry in _checkpoint_entries(result.state)
    ]
    assert checkpoint_attempts == [
        ("intent_input", 1),
        ("intent_output", 1),
        ("matching_input", 1),
        ("matching_output", 1),
        ("strategy_input", 1),
        ("strategy_output", 1),
        ("matching_input", 2),
        ("matching_output", 2),
        ("strategy_input", 2),
        ("strategy_output", 2),
        ("publication_gate", 2),
    ]


@pytest.mark.asyncio
async def test_consulted_intent_skips_llm_but_keeps_checkpoint_and_reuse_log(
    monkeypatch,
    orchestration_implementation,
) -> None:
    from app.agents import orchestrator
    from app.agents import supervisor

    brief = _brief()
    recorder = PersistedRunRecorder(
        _run(brief),
        _state(intent_consulted=True),
    )
    recorder.install(monkeypatch, orchestrator)

    async def forbidden_intent(*_args, **_kwargs):
        raise AssertionError("consulted intent must not call the Intent LLM")

    async def matching(
        state: SharedState,
        *,
        retrieval_plan,
        search_fn,
    ) -> SharedState:
        del retrieval_plan, search_fn
        return _populate_matching_state(state)

    async def strategy(state: SharedState) -> SharedState:
        return _populate_strategy_state(state)

    async def chat(*_args, **_kwargs) -> str:
        return _verification_payload()

    monkeypatch.setattr(orchestrator, "run_intent_agent", forbidden_intent)
    monkeypatch.setattr(orchestrator, "run_matching_agent", matching)
    monkeypatch.setattr(orchestrator, "run_strategy_agent", strategy)
    monkeypatch.setattr(supervisor.deepseek, "chat", chat)

    result = await _run_characterized_implementation(
        orchestration_implementation,
        monkeypatch,
        run_id=recorder.run.run_id,
    )

    assert [
        entry["checkpoint"] for entry in _checkpoint_entries(result.state)
    ] == CHECKPOINT_ORDER
    intent_audit = [
        entry
        for entry in result.state.supervisor_log
        if entry.get("checkpoint") in {"intent_input", "intent_output"}
        or entry.get("stage") == "intent_consultation_reused"
    ]
    assert [
        entry.get("checkpoint") or entry.get("stage") for entry in intent_audit
    ] == [
        "intent_input",
        "intent_consultation_reused",
        "intent_output",
    ]
    assert intent_audit[1] == {
        "stage": "intent_consultation_reused",
        "reason": "approved_visible_consultation",
    }
    assert recorder.save_result_statuses == [RunStatus.RUNNING]
    assert recorder.timeline.count("save_result") == 1


@pytest.mark.asyncio
async def test_graph_reretrieval_condition_caps_loop_after_second_verify(
    monkeypatch,
) -> None:
    from langgraph.checkpoint.memory import MemorySaver

    from app.agents import orchestrator
    from app.agents import supervisor
    from app.graph.build import build_graph

    brief = _brief()
    initial_state = _state()
    recorder = PersistedRunRecorder(_run(brief), initial_state)
    recorder.status = RunStatus.RUNNING
    recorder.install(monkeypatch, orchestrator)
    matching_calls = 0
    strategy_calls = 0
    verification_calls = 0

    async def intent(state: SharedState, goal: str) -> SharedState:
        state.career_state.current_goal = [goal]
        return state

    async def matching(
        state: SharedState,
        *,
        retrieval_plan,
        search_fn,
    ) -> SharedState:
        nonlocal matching_calls
        del retrieval_plan, search_fn
        matching_calls += 1
        return _populate_matching_state(state, candidate_count=3)

    async def strategy(state: SharedState) -> SharedState:
        nonlocal strategy_calls
        strategy_calls += 1
        return _populate_strategy_state(state)

    async def chat(*_args, **_kwargs) -> str:
        nonlocal verification_calls
        verification_calls += 1
        return _verification_payload(needs_reretrieval=True)

    monkeypatch.setattr(orchestrator, "run_intent_agent", intent)
    monkeypatch.setattr(orchestrator, "run_matching_agent", matching)
    monkeypatch.setattr(orchestrator, "run_strategy_agent", strategy)
    monkeypatch.setattr(supervisor.deepseek, "chat", chat)

    graph = build_graph(checkpointer=MemorySaver())
    output = await graph.ainvoke(
        {
            "shared": initial_state,
            "brief": brief,
            "retrieval_plan": {},
            "verification": {},
            "product_result": None,
            "attempt": 1,
            "loops": {"reretrieval": 0, "repair": 0},
            "run_id": recorder.run.run_id,
            "stage_timing": {},
        },
        config={
            "configurable": {"thread_id": recorder.run.run_id},
            "recursion_limit": 12,
        },
        durability="sync",
    )

    assert matching_calls == 2
    assert strategy_calls == 2
    assert verification_calls == 2
    assert output["attempt"] == 2
    assert output["loops"]["reretrieval"] == 1
    assert output["verification"]["reretrieval_loop_requested"] is True
    assert output["verification"]["reretrieval_loop_used"] == 1
    assert recorder.timeline.count("save_result") == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("outcome", "terminal_status", "error_code", "expected_events"),
    [
        (
            "failure",
            RunStatus.FAILED,
            "run_execution_failed",
            ["event:run_started", "event:run_failed"],
        ),
        (
            "cancelled",
            RunStatus.CANCELLED,
            "run_cancelled",
            ["event:run_started"],
        ),
    ],
)
async def test_graph_runner_maps_failure_and_cancellation_like_legacy(
    monkeypatch,
    outcome,
    terminal_status,
    error_code,
    expected_events,
) -> None:
    from app.agents import orchestrator
    from app.graph import runner

    brief = _brief()
    recorder = PersistedRunRecorder(_run(brief), _state())
    recorder.install(monkeypatch, orchestrator)

    class InterruptingGraph:
        async def ainvoke(self, _state, config, *, durability):
            assert config == {
                "configurable": {"thread_id": recorder.run.run_id},
                "recursion_limit": 12,
            }
            assert durability == "sync"
            if outcome == "cancelled":
                raise asyncio.CancelledError
            raise RuntimeError("injected graph failure")

    monkeypatch.setattr(
        runner,
        "build_graph",
        lambda **_kwargs: InterruptingGraph(),
    )

    expected_error = (
        asyncio.CancelledError if outcome == "cancelled" else RuntimeError
    )
    with pytest.raises(expected_error):
        await runner.run_graph_match(run_id=recorder.run.run_id)

    assert recorder.status_history == [
        RunStatus.QUEUED,
        RunStatus.RUNNING,
        terminal_status,
    ]
    assert recorder.transition_error_codes == [None, error_code]
    assert [
        event for event in recorder.timeline if event.startswith("event:")
    ] == expected_events
    assert recorder.timeline.count("save_result") == 0
