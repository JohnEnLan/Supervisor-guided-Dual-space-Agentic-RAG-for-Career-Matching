from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domain.monitoring import (
    MonitoringOverviewSnapshot,
    RecentRunSnapshot,
    StageLatencySnapshot,
)


def _client() -> TestClient:
    from app.api.v1.router import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_monitoring_routes_are_hidden_when_capability_is_disabled(
    monkeypatch,
) -> None:
    from app.api.v1 import monitoring

    monkeypatch.setattr(monitoring.settings, "monitoring_enabled", False)

    with _client() as client:
        overview = client.get("/api/v1/monitoring/overview")
        recent = client.get("/api/v1/monitoring/runs")

    assert overview.status_code == 404
    assert recent.status_code == 404


def test_monitoring_overview_returns_typed_safe_projection(monkeypatch) -> None:
    from app.api.v1 import monitoring

    now = datetime.now(UTC)

    async def overview(*, window_hours: int):
        assert window_hours == 24
        return MonitoringOverviewSnapshot(
            window_hours=24,
            generated_at=now,
            total_runs=5,
            status_counts={"completed": 4, "failed": 1},
            completion_rate=0.8,
            warning_rate=0.0,
            failure_rate=0.2,
            duration_p50_ms=1000,
            duration_p95_ms=2000,
            stage_latencies=[
                StageLatencySnapshot(stage="retrieval", p50_ms=300, p95_ms=600)
            ],
            average_recommendation_count=3.0,
            jd_evidence_coverage_rate=1.0,
            implicit_usage_rate=0.5,
            reordered_run_count=2,
        )

    monkeypatch.setattr(monitoring.settings, "monitoring_enabled", True)
    monkeypatch.setattr(monitoring, "get_monitoring_overview", overview)

    with _client() as client:
        response = client.get("/api/v1/monitoring/overview?window_hours=24")

    assert response.status_code == 200
    assert response.json()["stage_latencies"][0]["stage"] == "retrieval"
    for private_name in (
        "user_id",
        "state_snapshot",
        "resume",
        "prompt",
        "provider_error",
    ):
        assert private_name not in response.text.casefold()


def test_monitoring_recent_runs_returns_only_allow_list_fields(monkeypatch) -> None:
    from app.api.v1 import monitoring

    now = datetime.now(UTC)

    async def recent(*, window_hours: int, limit: int):
        assert (window_hours, limit) == (24, 20)
        return [
            RecentRunSnapshot(
                run_id="run-1",
                status="completed",
                stage="finalization",
                created_at=now,
                updated_at=now,
                started_at=now,
                finished_at=now,
                duration_ms=1200,
                recommendation_count=3,
                warning_codes=[],
            )
        ]

    monkeypatch.setattr(monitoring.settings, "monitoring_enabled", True)
    monkeypatch.setattr(monitoring, "list_recent_runs", recent)

    with _client() as client:
        response = client.get(
            "/api/v1/monitoring/runs?window_hours=24&limit=20"
        )

    assert response.status_code == 200
    assert response.json()["runs"][0]["run_id"] == "run-1"
    assert set(response.json()["runs"][0]) == {
        "run_id",
        "status",
        "stage",
        "created_at",
        "updated_at",
        "started_at",
        "finished_at",
        "duration_ms",
        "recommendation_count",
        "warning_codes",
        "error_code",
    }
