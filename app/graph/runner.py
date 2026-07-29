from __future__ import annotations

import asyncio
from typing import Any

from app.agents import orchestrator
from app.db.run_store import RunConflict
from app.domain.match_brief import MatchBrief
from app.domain.monitoring import build_run_metrics
from app.domain.results import ProductResult
from app.domain.run import MatchRun, RunStage, RunStatus
from app.graph.build import build_graph
from app.graph.state import GraphState
from app.state.schema import SharedState


SUCCESS_STATUSES = {
    RunStatus.COMPLETED,
    RunStatus.COMPLETED_WITH_WARNINGS,
}


async def run_graph_match(
    *,
    run_id: str,
    checkpointer: Any = None,
) -> orchestrator.AgenticMatchResult:
    """Start, resume, or idempotently read one LangGraph match run."""
    run = await orchestrator.get_run(run_id=run_id)
    if run is None:
        raise KeyError(f"run_id not found: {run_id}")
    if run.status in SUCCESS_STATUSES:
        result = await _load_terminal_result(run_id=run_id, run=run)
        await _delete_checkpoint_thread(checkpointer, run_id)
        return result
    if run.status not in {RunStatus.QUEUED, RunStatus.RUNNING}:
        raise RunConflict(
            "run must be queued, running, or successfully completed"
        )

    graph_input: GraphState | None = None
    if run.status is RunStatus.QUEUED:
        brief = MatchBrief.model_validate(run.approved_plan)
        await orchestrator.transition_run(
            run_id=run_id,
            current_status=RunStatus.QUEUED,
            target_status=RunStatus.RUNNING,
            stage=RunStage.INTENT,
        )
    try:
        if run.status is RunStatus.QUEUED:
            await orchestrator.append_event(
                run_id=run_id,
                event_type="run_started",
                stage=RunStage.INTENT.value,
                status=RunStatus.RUNNING.value,
                public_payload={"message": "Matching run started"},
            )
            initial_snapshot = await orchestrator.load_state_snapshot(
                run_id=run_id
            )
            if initial_snapshot is None:
                raise RuntimeError(
                    "run is missing its confirmed state snapshot"
                )
            initial_state = SharedState.model_validate(initial_snapshot)
            graph_input = {
                "shared": initial_state,
                "brief": brief,
                "retrieval_plan": {},
                "verification": {},
                "product_result": None,
                "attempt": 1,
                "loops": {"reretrieval": 0, "repair": 0},
                "run_id": run_id,
                "stage_timing": {},
            }
        output = await build_graph(checkpointer=checkpointer).ainvoke(
            graph_input,
            config={
                "configurable": {"thread_id": run_id},
                "recursion_limit": 12,
            },
            durability="sync",
        )
        shared = SharedState.model_validate(output["shared"])
        product_result = ProductResult.model_validate(output["product_result"])
        retrieval_plan = dict(output["retrieval_plan"])
        verification = dict(output["verification"])
        warning_codes = list(product_result.warnings)
        await orchestrator.save_run_result(
            run_id=run_id,
            result_snapshot=product_result.model_dump(mode="json"),
            warning_codes=warning_codes,
        )
        try:
            await orchestrator.save_run_metrics(
                run_id=run_id,
                metrics=build_run_metrics(shared, product_result),
            )
        except Exception:
            pass
        try:
            await orchestrator.append_event(
                run_id=run_id,
                event_type="run_completed",
                stage=RunStage.FINALIZATION.value,
                status=(
                    RunStatus.COMPLETED_WITH_WARNINGS.value
                    if warning_codes
                    else RunStatus.COMPLETED.value
                ),
                public_payload={
                    "message": "Matching run completed",
                    "count": len(product_result.recommended_roles),
                },
            )
        except Exception:
            pass
        result = orchestrator.AgenticMatchResult(
            state=shared,
            retrieval_plan=retrieval_plan,
            final_verification=verification,
        )
    except asyncio.CancelledError:
        terminalized = False
        try:
            await orchestrator.transition_run(
                run_id=run_id,
                current_status=RunStatus.RUNNING,
                target_status=RunStatus.CANCELLED,
                error_code="run_cancelled",
            )
            terminalized = True
        except Exception:
            pass
        if terminalized:
            await _best_effort_delete_checkpoint_thread(
                checkpointer,
                run_id,
            )
        raise
    except Exception:
        terminalized = False
        try:
            await orchestrator.transition_run(
                run_id=run_id,
                current_status=RunStatus.RUNNING,
                target_status=RunStatus.FAILED,
                error_code="run_execution_failed",
            )
            terminalized = True
        except Exception:
            pass
        if terminalized:
            try:
                await orchestrator.append_event(
                    run_id=run_id,
                    event_type="run_failed",
                    status=RunStatus.FAILED.value,
                    public_payload={
                        "message": "Matching run failed",
                        "reason_code": "run_execution_failed",
                    },
                )
            except Exception:
                pass
            await _best_effort_delete_checkpoint_thread(
                checkpointer,
                run_id,
            )
        raise
    await _delete_checkpoint_thread(checkpointer, run_id)
    return result


async def _delete_checkpoint_thread(checkpointer: Any, run_id: str) -> None:
    if checkpointer is not None:
        await checkpointer.adelete_thread(run_id)


async def _best_effort_delete_checkpoint_thread(
    checkpointer: Any,
    run_id: str,
) -> None:
    try:
        await _delete_checkpoint_thread(checkpointer, run_id)
    except Exception:
        pass


async def _load_terminal_result(
    *,
    run_id: str,
    run: MatchRun,
) -> orchestrator.AgenticMatchResult:
    if run.result_snapshot is None:
        raise RuntimeError("completed run is missing its result snapshot")
    ProductResult.model_validate(run.result_snapshot)
    snapshot = await orchestrator.load_state_snapshot(run_id=run_id)
    if snapshot is None:
        raise RuntimeError("completed run is missing its state snapshot")
    shared = SharedState.model_validate(snapshot)
    return orchestrator.AgenticMatchResult(
        state=shared,
        retrieval_plan=_latest_retrieval_plan(shared),
        final_verification=_latest_verification(shared),
    )


def _latest_retrieval_plan(state: SharedState) -> dict[str, Any]:
    for stage_name in ("reretrieval_loop", "planning"):
        for entry in reversed(state.supervisor_log):
            if entry.get("stage") != stage_name:
                continue
            plan = entry.get(
                "reretrieval_plan"
                if stage_name == "reretrieval_loop"
                else "retrieval_plan"
            )
            if isinstance(plan, dict):
                return dict(plan)
    raise RuntimeError("completed run is missing its retrieval plan")


def _latest_verification(state: SharedState) -> dict[str, Any]:
    for entry in reversed(state.supervisor_log):
        if entry.get("stage") == "final_verification":
            return {
                key: value for key, value in entry.items() if key != "stage"
            }
    raise RuntimeError("completed run is missing final verification")
