from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.results import ProductResult
from app.state.schema import SharedState


MONITORED_STAGES = frozenset(
    {"intent", "retrieval", "strategy", "verification", "finalization"}
)


class RunMetricSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation_count: int = Field(ge=0)
    recommendations_with_jd_evidence: int = Field(ge=0)
    implicit_case_count: int = Field(ge=0)
    reordered_job_count: int = Field(ge=0)
    stage_durations_ms: dict[str, int] = Field(default_factory=dict)


class StageLatencySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str
    p50_ms: int | None = None
    p95_ms: int | None = None


class MonitoringOverviewSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_hours: int
    generated_at: datetime
    total_runs: int
    status_counts: dict[str, int] = Field(default_factory=dict)
    completion_rate: float
    warning_rate: float
    failure_rate: float
    duration_p50_ms: int | None = None
    duration_p95_ms: int | None = None
    stage_latencies: list[StageLatencySnapshot] = Field(default_factory=list)
    average_recommendation_count: float
    jd_evidence_coverage_rate: float
    implicit_usage_rate: float
    reordered_run_count: int


class RecentRunSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: str
    stage: str | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    recommendation_count: int = 0
    warning_codes: list[str] = Field(default_factory=list)
    error_code: str | None = None


def build_run_metrics(
    state: SharedState,
    result: ProductResult,
) -> RunMetricSnapshot:
    case_ids = {
        str(evidence["case_id"])
        for row in state.retrieval_state.ranking_scores
        for evidence in row.get("implicit_evidence") or []
        if isinstance(evidence, dict) and evidence.get("case_id")
    }
    reordered_job_count = sum(
        1
        for final_rank, row in enumerate(
            state.retrieval_state.ranking_scores,
            start=1,
        )
        if row.get("explicit_rank") is not None
        and int(row["explicit_rank"]) != final_rank
    )
    stage_durations_ms = {
        str(entry["stage_name"]): max(0, int(entry["duration_ms"]))
        for entry in state.supervisor_log
        if entry.get("stage") == "public_stage_duration"
        and entry.get("stage_name") in MONITORED_STAGES
        and entry.get("duration_ms") is not None
    }
    return RunMetricSnapshot(
        recommendation_count=len(result.recommended_roles),
        recommendations_with_jd_evidence=sum(
            1 for role in result.recommended_roles if role.evidence
        ),
        implicit_case_count=len(case_ids),
        reordered_job_count=reordered_job_count,
        stage_durations_ms=stage_durations_ms,
    )
