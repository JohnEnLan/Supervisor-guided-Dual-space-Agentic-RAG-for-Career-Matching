from __future__ import annotations

import asyncio
from typing import Any

from app.agents import orchestrator
from app.domain.match_brief import MatchBrief
from app.domain.monitoring import build_run_metrics
from app.domain.results import ProductResult
from app.domain.run import RunStage, RunStatus
from app.graph.build import build_graph
from app.graph.state import GraphState
from app.state.schema import SharedState


async def run_graph_match(
    *,
    run_id: str,
    checkpointer: Any = None,
) -> orchestrator.AgenticMatchResult:
    """Run one approved Match Brief through LangGraph and publish once."""
    run = await orchestrator.get_run(run_id=run_id)
    if run is None:
        raise KeyError(f"run_id not found: {run_id}")
    brief = MatchBrief.model_validate(run.approved_plan)
    await orchestrator.transition_run(
        run_id=run_id,
        current_status=RunStatus.QUEUED,
        target_status=RunStatus.RUNNING,
        stage=RunStage.INTENT,
    )
    try:
        await orchestrator.append_event(
            run_id=run_id,
            event_type="run_started",
            stage=RunStage.INTENT.value,
            status=RunStatus.RUNNING.value,
            public_payload={"message": "Matching run started"},
        )
        initial_snapshot = await orchestrator.load_state_snapshot(run_id=run_id)
        if initial_snapshot is None:
            raise RuntimeError("run is missing its confirmed state snapshot")
        initial_state = SharedState.model_validate(initial_snapshot)
        graph_input: GraphState = {
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
        return orchestrator.AgenticMatchResult(
            state=shared,
            retrieval_plan=retrieval_plan,
            final_verification=verification,
        )
    except asyncio.CancelledError:
        try:
            await orchestrator.transition_run(
                run_id=run_id,
                current_status=RunStatus.RUNNING,
                target_status=RunStatus.CANCELLED,
                error_code="run_cancelled",
            )
        except Exception:
            pass
        raise
    except Exception:
        try:
            await orchestrator.transition_run(
                run_id=run_id,
                current_status=RunStatus.RUNNING,
                target_status=RunStatus.FAILED,
                error_code="run_execution_failed",
            )
        except Exception:
            pass
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
        raise
