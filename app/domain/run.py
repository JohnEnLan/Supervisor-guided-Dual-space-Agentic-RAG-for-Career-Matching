from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RunStatus(StrEnum):
    DRAFT = "draft"
    PLAN_READY = "plan_ready"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"
    CANCELLED = "cancelled"
    STALE = "stale"


class RunStage(StrEnum):
    PLAN = "plan"
    INTENT = "intent"
    RETRIEVAL = "retrieval"
    STRATEGY = "strategy"
    VERIFICATION = "verification"
    FINALIZATION = "finalization"


TERMINAL_STATUSES = frozenset(
    {
        RunStatus.COMPLETED,
        RunStatus.COMPLETED_WITH_WARNINGS,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.STALE,
    }
)

ALLOWED_TRANSITIONS = {
    RunStatus.DRAFT: {
        RunStatus.PLAN_READY,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    },
    RunStatus.PLAN_READY: {RunStatus.QUEUED, RunStatus.CANCELLED},
    RunStatus.QUEUED: {
        RunStatus.RUNNING,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.STALE,
    },
    RunStatus.RUNNING: {
        RunStatus.COMPLETED,
        RunStatus.COMPLETED_WITH_WARNINGS,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.STALE,
    },
}


def can_transition(current: RunStatus, target: RunStatus) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, set())


class MatchRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    session_id: str
    confirmed_resume_version: int | None = None
    status: RunStatus
    stage: RunStage | None = None
    plan_version: int = 0
    plan_hash: str | None = None
    approved_plan: dict[str, Any] = Field(default_factory=dict)
    result_snapshot: dict[str, Any] | None = None
    warning_codes: list[str] = Field(default_factory=list)
    error_code: str | None = None
    execution_durability: str = "process_local"
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
