from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from app.api.auth.deps import optional_current_user, require_owned_run
from app.api.auth.sessions import AuthedUser
from app.agents.orchestrator import run_persisted_agentic_match_run
from app.agents.trace import (
    build_public_explain,
    build_public_recovery_events,
)
from app.api.conversation_projector import (
    ConversationProjectionContext,
    project_run_conversation,
)
from app.api.v1.schemas import (
    ExecuteRunRequest,
    RunConversationResponse,
    RunExplainResponse,
    RunResultResponse,
    RunStatusResponse,
)
from app.config import settings
from app.db.pool import get_pool
from app.db.run_store import (
    RunConflict,
    get_run,
    load_state_snapshot,
    queue_run,
)
from app.domain.run import RunStage, RunStatus, TERMINAL_STATUSES
from app.domain.results import ProductResult
from app.graph.runner import run_graph_match
from app.llm import usage_context
from app.state.schema import SharedState


router = APIRouter()
logger = logging.getLogger(__name__)

PUBLIC_STAGE_ORDER = (
    "resume",
    "intent",
    "retrieval",
    "strategy",
    "verification",
    "finalization",
    "result",
)


@router.post(
    "/runs/{run_id}/execute",
    response_model=RunStatusResponse,
    status_code=202,
    dependencies=[Depends(require_owned_run)],
)
async def execute_run(
    run_id: str,
    request: ExecuteRunRequest,
    background_tasks: BackgroundTasks,
    http_request: Request,
    user: Annotated[AuthedUser | None, Depends(optional_current_user)] = None,
) -> RunStatusResponse:
    try:
        run = await queue_run(
            run_id=run_id,
            plan_version=request.plan_version,
            plan_hash=request.plan_hash,
        )
    except RunConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    await usage_context.record_product_event(
        "run_started",
        user.user_id if user is not None else None,
    )
    executor = _select_run_executor()
    execution_kwargs = {"run_id": run_id}
    if settings.langgraph_orchestrator_enabled:
        execution_kwargs["checkpointer"] = (
            http_request.app.state.langgraph_checkpointer
        )
    background_tasks.add_task(
        _run_with_usage_scope,
        run_id,
        executor,
        **execution_kwargs,
    )
    return _status_response(run)


@router.get(
    "/runs/{run_id}/status",
    response_model=RunStatusResponse,
    dependencies=[Depends(require_owned_run)],
)
async def run_status(run_id: str) -> RunStatusResponse:
    run = await get_run(run_id=run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run_id not found")
    return _status_response(run)


@router.get(
    "/runs/{run_id}/conversation",
    response_model=RunConversationResponse,
    dependencies=[Depends(require_owned_run)],
)
async def run_conversation(run_id: str) -> RunConversationResponse:
    run = await get_run(run_id=run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run_id not found")

    snapshot = await load_state_snapshot(run_id=run_id)
    supervisor_log = (
        snapshot.get("supervisor_log", [])
        if isinstance(snapshot, dict)
        else []
    )
    public_log = [
        event for event in supervisor_log if isinstance(event, dict)
    ]
    recovery_events = build_public_recovery_events(public_log)
    projection_context = _projection_context_from_snapshot(snapshot)
    result = (
        ProductResult.model_validate(run.result_snapshot)
        if run.result_snapshot is not None
        else None
    )
    return RunConversationResponse(
        run_id=run.run_id,
        status=run.status.value,
        stage=run.stage.value if run.stage else None,
        next_poll_ms=(None if run.status in TERMINAL_STATUSES else 1500),
        messages=project_run_conversation(
            run=run,
            recovery_events=recovery_events,
            result=result,
            context=projection_context,
        ),
    )


@router.get(
    "/runs/{run_id}/result",
    response_model=RunResultResponse,
    dependencies=[Depends(require_owned_run)],
)
async def run_result(run_id: str) -> RunResultResponse:
    run = await get_run(run_id=run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run_id not found")
    if run.status not in {
        RunStatus.COMPLETED,
        RunStatus.COMPLETED_WITH_WARNINGS,
    } or run.result_snapshot is None:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "run result is not ready",
                "recovery": {
                    "action": "poll_status",
                    "status_url": f"/api/v1/runs/{run_id}/status",
                },
            },
        )
    return RunResultResponse(
        run_id=run_id,
        status=run.status.value,
        result=ProductResult.model_validate(run.result_snapshot),
    )


@router.get(
    "/runs/{run_id}/explain",
    response_model=RunExplainResponse,
    dependencies=[Depends(require_owned_run)],
)
async def run_explain(run_id: str) -> RunExplainResponse:
    if not settings.evaluation_capability_enabled:
        raise HTTPException(status_code=404, detail="explain capability disabled")
    run = await get_run(run_id=run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run_id not found")
    if run.status not in {
        RunStatus.COMPLETED,
        RunStatus.COMPLETED_WITH_WARNINGS,
    }:
        raise HTTPException(status_code=409, detail="run result is not ready")
    snapshot = await load_state_snapshot(run_id=run_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="run trace not found")
    state = SharedState.model_validate(snapshot)
    explain = build_public_explain(
        state,
        evaluation_enabled=True,
        implicit_max_weight=settings.implicit_max_weight,
    )
    return RunExplainResponse(run_id=run_id, **(explain or {}))


def _status_response(run) -> RunStatusResponse:
    return RunStatusResponse(
        run_id=run.run_id,
        session_id=run.session_id,
        status=run.status.value,
        stage=run.stage.value if run.stage else None,
        result_ready=run.status
        in {RunStatus.COMPLETED, RunStatus.COMPLETED_WITH_WARNINGS},
        warning_codes=run.warning_codes,
        error_code=run.error_code,
        execution_durability=run.execution_durability,
        retry_after_ms=(None if run.status in TERMINAL_STATUSES else 1500),
        completed_stages=public_progress(
            status=run.status,
            stage=run.stage,
        ),
        total_stages=len(PUBLIC_STAGE_ORDER),
        plan_version=run.plan_version,
        plan_hash=run.plan_hash,
        updated_at=run.updated_at,
    )


def _select_run_executor():
    if settings.langgraph_orchestrator_enabled:
        return run_graph_match
    return run_persisted_agentic_match_run


async def _run_with_usage_scope(scope_run_id: str, executor, **kwargs) -> None:
    try:
        pool = await get_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT run.session_id, session.owner_user_id
                FROM match_runs AS run
                INNER JOIN session_state AS session
                    ON session.session_id = run.session_id
                WHERE run.run_id = $1
                """,
                scope_run_id,
            )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning(
            "run usage attribution lookup failed for %s",
            scope_run_id,
            exc_info=True,
        )
        await executor(**kwargs)
        return
    if row is None:
        logger.warning("run usage attribution missing for %s", scope_run_id)
        await executor(**kwargs)
        return

    owner_user_id = row["owner_user_id"]
    async with usage_context.usage_scope(
        str(owner_user_id) if owner_user_id is not None else None,
        str(row["session_id"]),
        "run",
    ):
        await executor(**kwargs)


def _projection_context_from_snapshot(
    snapshot: object,
) -> ConversationProjectionContext:
    if not isinstance(snapshot, dict):
        return ConversationProjectionContext()
    raw_log = snapshot.get("supervisor_log")
    if not isinstance(raw_log, list):
        return ConversationProjectionContext()

    matching_input_status = None
    matching_output_status = None
    candidate_count = None
    ranking_count = None
    evidence_count = None
    input_found = False
    output_found = False

    for event in reversed(raw_log):
        if not isinstance(event, dict) or event.get("stage") != "supervisor_checkpoint":
            continue
        checkpoint = event.get("checkpoint")
        if checkpoint == "matching_input" and not input_found:
            matching_input_status = _checkpoint_status(event.get("status"))
            input_found = True
        elif checkpoint == "matching_output" and not output_found:
            matching_output_status = _checkpoint_status(event.get("status"))
            metrics = event.get("metrics")
            candidate_count = _checkpoint_count(metrics, "candidate_count")
            ranking_count = _checkpoint_count(metrics, "ranking_count")
            evidence_count = _checkpoint_count(metrics, "evidence_count")
            output_found = True
        if input_found and output_found:
            break

    return ConversationProjectionContext(
        matching_input_status=matching_input_status,
        matching_output_status=matching_output_status,
        candidate_count=candidate_count,
        ranking_count=ranking_count,
        evidence_count=evidence_count,
    )


def _checkpoint_status(value: object) -> str | None:
    return value if value in {"passed", "warning"} else None


def _checkpoint_count(metrics: object, key: str) -> int | None:
    if not isinstance(metrics, dict):
        return None
    value = metrics.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def public_progress(
    *,
    status: RunStatus,
    stage: RunStage | None,
) -> list[str]:
    if status in {RunStatus.COMPLETED, RunStatus.COMPLETED_WITH_WARNINGS}:
        return list(PUBLIC_STAGE_ORDER)
    active_stage = stage.value if stage is not None else "intent"
    try:
        active_index = PUBLIC_STAGE_ORDER.index(active_stage)
    except ValueError:
        active_index = 1
    return list(PUBLIC_STAGE_ORDER[:active_index])
