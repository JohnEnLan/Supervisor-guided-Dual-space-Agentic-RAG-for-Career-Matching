from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query

from app.api.v1.schemas import (
    MonitoringOverviewResponse,
    RecentRunsResponse,
)
from app.config import settings
from app.db.monitoring_store import (
    get_monitoring_overview,
    list_recent_runs,
)


router = APIRouter()


@router.get(
    "/monitoring/overview",
    response_model=MonitoringOverviewResponse,
)
async def monitoring_overview(
    window_hours: int = Query(default=24, ge=1, le=720),
) -> MonitoringOverviewResponse:
    _require_monitoring()
    overview = await get_monitoring_overview(window_hours=window_hours)
    return MonitoringOverviewResponse.model_validate(overview.model_dump())


@router.get(
    "/monitoring/runs",
    response_model=RecentRunsResponse,
)
async def monitoring_runs(
    window_hours: int = Query(default=24, ge=1, le=720),
    limit: int = Query(default=20, ge=1, le=100),
) -> RecentRunsResponse:
    _require_monitoring()
    runs = await list_recent_runs(
        window_hours=window_hours,
        limit=limit,
    )
    return RecentRunsResponse(
        window_hours=window_hours,
        generated_at=datetime.now(UTC),
        runs=[run.model_dump() for run in runs],
    )


def _require_monitoring() -> None:
    if not settings.monitoring_enabled:
        raise HTTPException(status_code=404, detail="monitoring capability disabled")
