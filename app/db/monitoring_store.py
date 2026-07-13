from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from app.db.pool import get_pool
from app.domain.monitoring import (
    MonitoringOverviewSnapshot,
    RecentRunSnapshot,
    RunMetricSnapshot,
    StageLatencySnapshot,
)
from app.domain.run import RunStatus


async def save_run_metrics(
    *,
    run_id: str,
    metrics: RunMetricSnapshot,
) -> RunMetricSnapshot:
    pool = await get_pool()
    async with pool.acquire() as connection:
        row = await connection.fetchrow(
            """
            INSERT INTO run_metrics (
                run_id,
                recommendation_count,
                recommendations_with_jd_evidence,
                implicit_case_count,
                reordered_job_count,
                stage_durations_ms
            )
            VALUES ($1, $2, $3, $4, $5, $6::jsonb)
            ON CONFLICT (run_id) DO UPDATE
            SET recommendation_count = EXCLUDED.recommendation_count,
                recommendations_with_jd_evidence =
                    EXCLUDED.recommendations_with_jd_evidence,
                implicit_case_count = EXCLUDED.implicit_case_count,
                reordered_job_count = EXCLUDED.reordered_job_count,
                stage_durations_ms = EXCLUDED.stage_durations_ms
            RETURNING run_id,
                      recommendation_count,
                      recommendations_with_jd_evidence,
                      implicit_case_count,
                      reordered_job_count,
                      stage_durations_ms
            """,
            run_id,
            metrics.recommendation_count,
            metrics.recommendations_with_jd_evidence,
            metrics.implicit_case_count,
            metrics.reordered_job_count,
            json.dumps(metrics.stage_durations_ms),
        )
    if row is None:
        raise RuntimeError("database did not return saved run metrics")
    payload = dict(row)
    payload.pop("run_id", None)
    payload["stage_durations_ms"] = _json_object(
        payload.get("stage_durations_ms")
    )
    return RunMetricSnapshot.model_validate(payload)


async def get_monitoring_overview(
    *,
    window_hours: int,
) -> MonitoringOverviewSnapshot:
    window_hours = _bounded_window(window_hours)
    pool = await get_pool()
    async with pool.acquire() as connection:
        aggregate = await connection.fetchrow(
            """
            WITH windowed AS (
                SELECT r.*,
                       EXTRACT(EPOCH FROM (r.finished_at - r.started_at))
                           * 1000 AS duration_ms
                FROM match_runs AS r
                WHERE r.created_at >=
                      now() - make_interval(hours => $1::int)
            )
            SELECT COUNT(*) AS total_runs,
                   COUNT(*) FILTER (WHERE w.status = 'draft') AS draft_count,
                   COUNT(*) FILTER (WHERE w.status = 'plan_ready')
                       AS plan_ready_count,
                   COUNT(*) FILTER (WHERE w.status = 'queued') AS queued_count,
                   COUNT(*) FILTER (WHERE w.status = 'running') AS running_count,
                   COUNT(*) FILTER (WHERE w.status = 'completed')
                       AS completed_count,
                   COUNT(*) FILTER (
                       WHERE w.status = 'completed_with_warnings'
                   ) AS completed_with_warnings_count,
                   COUNT(*) FILTER (WHERE w.status = 'failed') AS failed_count,
                   COUNT(*) FILTER (WHERE w.status = 'cancelled')
                       AS cancelled_count,
                   COUNT(*) FILTER (WHERE w.status = 'stale') AS stale_count,
                   percentile_cont(0.5) WITHIN GROUP (
                       ORDER BY w.duration_ms
                   ) FILTER (WHERE w.duration_ms IS NOT NULL)
                       AS duration_p50_ms,
                   percentile_cont(0.95) WITHIN GROUP (
                       ORDER BY w.duration_ms
                   ) FILTER (WHERE w.duration_ms IS NOT NULL)
                       AS duration_p95_ms,
                   COALESCE(SUM(m.recommendation_count), 0)
                       AS recommendation_total,
                   COALESCE(SUM(m.recommendations_with_jd_evidence), 0)
                       AS recommendations_with_jd_evidence_total,
                   COUNT(m.run_id) AS metric_run_count,
                   COUNT(m.run_id) FILTER (WHERE m.implicit_case_count > 0)
                       AS implicit_run_count,
                   COUNT(m.run_id) FILTER (WHERE m.reordered_job_count > 0)
                       AS reordered_run_count,
                   COALESCE(AVG(m.recommendation_count), 0)
                       AS average_recommendation_count
            FROM windowed AS w
            LEFT JOIN run_metrics AS m ON m.run_id = w.run_id
            """,
            window_hours,
        )
        stage_rows = await connection.fetch(
            """
            SELECT stage.key AS stage,
                   percentile_cont(0.5) WITHIN GROUP (
                       ORDER BY (stage.value)::numeric
                   ) AS p50_ms,
                   percentile_cont(0.95) WITHIN GROUP (
                       ORDER BY (stage.value)::numeric
                   ) AS p95_ms
            FROM run_metrics AS m
            JOIN match_runs AS r ON r.run_id = m.run_id
            CROSS JOIN LATERAL jsonb_each_text(m.stage_durations_ms) AS stage
            WHERE r.created_at >= now() - make_interval(hours => $1::int)
            GROUP BY stage.key
            ORDER BY stage.key
            """,
            window_hours,
        )

    values = dict(aggregate or {})
    status_counts = {
        status.value: int(values.get(f"{status.value}_count") or 0)
        for status in RunStatus
    }
    total_runs = int(values.get("total_runs") or 0)
    completed = status_counts[RunStatus.COMPLETED.value]
    warnings = status_counts[RunStatus.COMPLETED_WITH_WARNINGS.value]
    failures = sum(
        status_counts[status.value]
        for status in (
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.STALE,
        )
    )
    recommendation_total = int(values.get("recommendation_total") or 0)
    metric_run_count = int(values.get("metric_run_count") or 0)
    return MonitoringOverviewSnapshot(
        window_hours=window_hours,
        generated_at=datetime.now(UTC),
        total_runs=total_runs,
        status_counts=status_counts,
        completion_rate=_rate(completed + warnings, total_runs),
        warning_rate=_rate(warnings, total_runs),
        failure_rate=_rate(failures, total_runs),
        duration_p50_ms=_rounded_optional(values.get("duration_p50_ms")),
        duration_p95_ms=_rounded_optional(values.get("duration_p95_ms")),
        stage_latencies=[
            StageLatencySnapshot(
                stage=str(row["stage"]),
                p50_ms=_rounded_optional(row.get("p50_ms")),
                p95_ms=_rounded_optional(row.get("p95_ms")),
            )
            for row in map(dict, stage_rows)
        ],
        average_recommendation_count=round(
            float(values.get("average_recommendation_count") or 0.0),
            3,
        ),
        jd_evidence_coverage_rate=_rate(
            int(values.get("recommendations_with_jd_evidence_total") or 0),
            recommendation_total,
        ),
        implicit_usage_rate=_rate(
            int(values.get("implicit_run_count") or 0),
            metric_run_count,
        ),
        reordered_run_count=int(values.get("reordered_run_count") or 0),
    )


async def list_recent_runs(
    *,
    window_hours: int,
    limit: int,
) -> list[RecentRunSnapshot]:
    window_hours = _bounded_window(window_hours)
    limit = max(1, min(int(limit), 100))
    pool = await get_pool()
    async with pool.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT r.run_id,
                   r.status,
                   r.stage,
                   r.created_at,
                   r.updated_at,
                   r.started_at,
                   r.finished_at,
                   EXTRACT(EPOCH FROM (r.finished_at - r.started_at))
                       * 1000 AS duration_ms,
                   COALESCE(m.recommendation_count, 0)
                       AS recommendation_count,
                   r.warning_codes,
                   r.error_code
            FROM match_runs AS r
            LEFT JOIN run_metrics AS m ON m.run_id = r.run_id
            WHERE r.created_at >= now() - make_interval(hours => $1::int)
            ORDER BY r.created_at DESC
            LIMIT $2
            """,
            window_hours,
            limit,
        )
    return [
        RecentRunSnapshot(
            **{
                **dict(row),
                "duration_ms": _rounded_optional(row.get("duration_ms")),
                "warning_codes": list(row.get("warning_codes") or []),
            }
        )
        for row in rows
    ]


def _bounded_window(value: int) -> int:
    return max(1, min(int(value), 720))


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _rounded_optional(value: Any) -> int | None:
    return int(round(float(value))) if value is not None else None


def _json_object(value: Any) -> dict[str, int]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        return {}
    return {str(key): int(item) for key, item in value.items()}
