from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.agents.orchestrator import run_persisted_agentic_match_run
from app.agents.trace import build_public_explain
from app.api.v1.schemas import (
    ExecuteRunRequest,
    RunExplainResponse,
    RunResultResponse,
    RunStatusResponse,
)
from app.config import settings
from app.db.run_store import (
    RunConflict,
    get_run,
    load_state_snapshot,
    queue_run,
)
from app.domain.run import RunStatus
from app.domain.results import ProductResult
from app.state.schema import SharedState


router = APIRouter()


@router.post(
    "/runs/{run_id}/execute",
    response_model=RunStatusResponse,
    status_code=202,
)
async def execute_run(
    run_id: str,
    request: ExecuteRunRequest,
    background_tasks: BackgroundTasks,
) -> RunStatusResponse:
    try:
        run = await queue_run(
            run_id=run_id,
            plan_version=request.plan_version,
            plan_hash=request.plan_hash,
        )
    except RunConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    background_tasks.add_task(run_persisted_agentic_match_run, run_id=run_id)
    return _status_response(run)


@router.get("/runs/{run_id}/status", response_model=RunStatusResponse)
async def run_status(run_id: str) -> RunStatusResponse:
    run = await get_run(run_id=run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run_id not found")
    return _status_response(run)


@router.get("/runs/{run_id}/result", response_model=RunResultResponse)
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


@router.get("/runs/{run_id}/explain", response_model=RunExplainResponse)
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
        updated_at=run.updated_at,
    )
