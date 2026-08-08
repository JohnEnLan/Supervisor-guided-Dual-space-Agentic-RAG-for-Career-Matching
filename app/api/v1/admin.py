from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.agents.trace import build_public_explain
from app.api.auth.deps import require_admin
from app.api.v1.schemas import (
    AdminOverviewResponse,
    AdminResetParseCountResponse,
    AdminUserResumeResponse,
    AdminUsersPageResponse,
    RunExplainResponse,
)
from app.config import settings
from app.db.admin_store import (
    get_admin_overview,
    get_admin_user_resume,
    list_admin_users,
    reset_resume_parse_count,
)
from app.db.run_store import get_run, load_state_snapshot
from app.domain.run import RunStatus
from app.state.schema import SharedState


router = APIRouter(
    prefix="/admin",
    dependencies=[Depends(require_admin)],
)


@router.get("/overview", response_model=AdminOverviewResponse)
async def admin_overview() -> AdminOverviewResponse:
    return AdminOverviewResponse.model_validate(await get_admin_overview())


@router.get("/users", response_model=AdminUsersPageResponse)
async def admin_users(
    page: int = Query(default=1, ge=1),
) -> AdminUsersPageResponse:
    return AdminUsersPageResponse.model_validate(
        await list_admin_users(page=page)
    )


@router.get(
    "/users/{user_id}/resume",
    response_model=AdminUserResumeResponse,
)
async def admin_user_resume(user_id: str) -> AdminUserResumeResponse:
    stored = await get_admin_user_resume(user_id=user_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="user_id not found")
    return AdminUserResumeResponse.model_validate(stored)


@router.get(
    "/runs/{run_id}/explain",
    response_model=RunExplainResponse,
)
async def admin_run_explain(run_id: str) -> RunExplainResponse:
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
    explain = build_public_explain(
        SharedState.model_validate(snapshot),
        evaluation_enabled=True,
        implicit_max_weight=settings.implicit_max_weight,
    )
    return RunExplainResponse(run_id=run_id, **(explain or {}))


@router.post(
    "/sessions/{session_id}/reset-parse-count",
    response_model=AdminResetParseCountResponse,
)
async def admin_reset_parse_count(
    session_id: str,
) -> AdminResetParseCountResponse:
    try:
        result = await reset_resume_parse_count(session_id=session_id)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail="session_id not found",
        ) from None
    return AdminResetParseCountResponse.model_validate(result)
