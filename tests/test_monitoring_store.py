from datetime import UTC, datetime

import pytest

from app.domain.monitoring import RunMetricSnapshot


class Acquire:
    def __init__(self, connection) -> None:
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class Pool:
    def __init__(self, connection) -> None:
        self.connection = connection

    def acquire(self) -> Acquire:
        return Acquire(self.connection)


class Connection:
    def __init__(self, *, fetchrow_results=None, fetch_results=None) -> None:
        self.fetchrow_results = list(fetchrow_results or [])
        self.fetch_results = list(fetch_results or [])
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetchrow(self, sql: str, *args: object):
        self.calls.append((sql, args))
        return self.fetchrow_results.pop(0)

    async def fetch(self, sql: str, *args: object):
        self.calls.append((sql, args))
        return self.fetch_results.pop(0)


@pytest.mark.asyncio
async def test_save_run_metrics_upserts_allow_list_snapshot(monkeypatch) -> None:
    from app.db import monitoring_store

    connection = Connection(
        fetchrow_results=[
            {
                "run_id": "run-1",
                "recommendation_count": 2,
                "recommendations_with_jd_evidence": 2,
                "implicit_case_count": 1,
                "reordered_job_count": 1,
                "stage_durations_ms": {"retrieval": 90},
            }
        ]
    )

    async def fake_get_pool():
        return Pool(connection)

    monkeypatch.setattr(monitoring_store, "get_pool", fake_get_pool)
    metrics = RunMetricSnapshot(
        recommendation_count=2,
        recommendations_with_jd_evidence=2,
        implicit_case_count=1,
        reordered_job_count=1,
        stage_durations_ms={"retrieval": 90},
    )

    saved = await monitoring_store.save_run_metrics(
        run_id="run-1",
        metrics=metrics,
    )

    sql, args = connection.calls[0]
    assert "ON CONFLICT (run_id) DO UPDATE" in sql
    assert "state_snapshot" not in sql
    assert args[0] == "run-1"
    assert saved == metrics


@pytest.mark.asyncio
async def test_monitoring_overview_computes_safe_rates_and_latencies(
    monkeypatch,
) -> None:
    from app.db import monitoring_store

    aggregate = {
        "total_runs": 10,
        "draft_count": 0,
        "plan_ready_count": 0,
        "queued_count": 1,
        "running_count": 1,
        "completed_count": 5,
        "completed_with_warnings_count": 2,
        "failed_count": 1,
        "cancelled_count": 0,
        "stale_count": 0,
        "duration_p50_ms": 1200.4,
        "duration_p95_ms": 3200.8,
        "recommendation_total": 20,
        "recommendations_with_jd_evidence_total": 18,
        "metric_run_count": 7,
        "implicit_run_count": 4,
        "reordered_run_count": 3,
        "average_recommendation_count": 2.857,
    }
    stage_rows = [
        {"stage": "retrieval", "p50_ms": 300.2, "p95_ms": 600.9},
        {"stage": "strategy", "p50_ms": 500.0, "p95_ms": 900.0},
    ]
    connection = Connection(
        fetchrow_results=[aggregate],
        fetch_results=[stage_rows],
    )

    async def fake_get_pool():
        return Pool(connection)

    monkeypatch.setattr(monitoring_store, "get_pool", fake_get_pool)

    overview = await monitoring_store.get_monitoring_overview(window_hours=24)

    assert overview.total_runs == 10
    assert overview.completion_rate == 0.7
    assert overview.warning_rate == 0.2
    assert overview.failure_rate == 0.1
    assert overview.duration_p50_ms == 1200
    assert overview.duration_p95_ms == 3201
    assert overview.jd_evidence_coverage_rate == 0.9
    assert overview.implicit_usage_rate == pytest.approx(4 / 7, abs=0.0001)
    assert overview.reordered_run_count == 3
    assert overview.stage_latencies[0].stage == "retrieval"
    assert overview.stage_latencies[0].p95_ms == 601
    assert all("state_snapshot" not in sql for sql, _args in connection.calls)


@pytest.mark.asyncio
async def test_recent_runs_returns_only_safe_fields(monkeypatch) -> None:
    from app.db import monitoring_store

    now = datetime.now(UTC)
    rows = [
        {
            "run_id": "run-1",
            "status": "completed",
            "stage": "finalization",
            "created_at": now,
            "updated_at": now,
            "started_at": now,
            "finished_at": now,
            "duration_ms": 1000.0,
            "recommendation_count": 3,
            "warning_codes": [],
            "error_code": None,
        }
    ]
    connection = Connection(fetch_results=[rows])

    async def fake_get_pool():
        return Pool(connection)

    monkeypatch.setattr(monitoring_store, "get_pool", fake_get_pool)

    recent = await monitoring_store.list_recent_runs(
        window_hours=24,
        limit=20,
    )

    assert recent[0].run_id == "run-1"
    assert recent[0].recommendation_count == 3
    sql, args = connection.calls[0]
    assert "state_snapshot" not in sql
    assert "user_id" not in sql
    assert args == (24, 20)
