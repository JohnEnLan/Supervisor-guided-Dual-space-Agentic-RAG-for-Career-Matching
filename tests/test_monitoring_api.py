from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.domain.monitoring import (
    MonitoringOverviewSnapshot,
    RecentRunSnapshot,
    StageLatencySnapshot,
)


def _client(*, admin_dependency=None) -> TestClient:
    from app.api.auth.deps import require_admin
    from app.api.v1.router import router

    app = FastAPI()
    app.include_router(router)
    if admin_dependency is not None:
        app.dependency_overrides[require_admin] = admin_dependency
    return TestClient(app)


def test_monitoring_routes_are_hidden_when_capability_is_disabled(
    monkeypatch,
) -> None:
    from app.api.auth import deps
    from app.api.auth.sessions import session_cookie_name

    monkeypatch.setattr(deps.settings, "monitoring_enabled", False)
    admin_calls = 0

    async def forbidden_admin():
        nonlocal admin_calls
        admin_calls += 1
        raise AssertionError("disabled monitoring must not resolve identity")

    with _client(admin_dependency=forbidden_admin) as client:
        responses = []
        for cookie in (None, "bad-cookie", "non-admin-cookie", "admin-cookie"):
            headers = (
                {}
                if cookie is None
                else {"Cookie": f"{session_cookie_name()}={cookie}"}
            )
            responses.extend(
                [
                    client.get("/api/v1/monitoring/overview", headers=headers),
                    client.get("/api/v1/monitoring/runs", headers=headers),
                ]
            )

    assert {response.status_code for response in responses} == {404}
    assert admin_calls == 0


def test_monitoring_overview_returns_typed_safe_projection(monkeypatch) -> None:
    from app.api.auth import deps
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

    monkeypatch.setattr(deps.settings, "monitoring_enabled", True)
    monkeypatch.setattr(monitoring, "get_monitoring_overview", overview)

    with _client(admin_dependency=lambda: None) as client:
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
    from app.api.auth import deps
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

    monkeypatch.setattr(deps.settings, "monitoring_enabled", True)
    monkeypatch.setattr(monitoring, "list_recent_runs", recent)

    with _client(admin_dependency=lambda: None) as client:
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


def test_monitoring_dependency_chain_is_capability_then_admin() -> None:
    from fastapi.routing import APIRoute

    from app.api.auth.deps import require_admin, require_monitoring_enabled
    from app.api.v1 import monitoring

    for route in monitoring.router.routes:
        assert isinstance(route, APIRoute)
        dependencies = route.dependant.dependencies
        assert [dependency.call for dependency in dependencies] == [
            require_monitoring_enabled,
            require_admin,
        ]
        assert dependencies[0].dependencies == []


@pytest.mark.parametrize("status_code", [401, 403, 200])
def test_monitoring_enabled_preserves_admin_dependency_status(
    monkeypatch, status_code
) -> None:
    from fastapi import HTTPException
    from app.api.auth import deps
    from app.api.v1 import monitoring

    monkeypatch.setattr(deps.settings, "monitoring_enabled", True)

    async def admin_result():
        if status_code != 200:
            raise HTTPException(status_code=status_code)

    async def overview(*, window_hours: int):
        now = datetime.now(UTC)
        return MonitoringOverviewSnapshot(
            window_hours=window_hours,
            generated_at=now,
            total_runs=0,
            status_counts={},
            completion_rate=0.0,
            warning_rate=0.0,
            failure_rate=0.0,
            duration_p50_ms=None,
            duration_p95_ms=None,
            stage_latencies=[],
            average_recommendation_count=0.0,
            jd_evidence_coverage_rate=0.0,
            implicit_usage_rate=0.0,
            reordered_run_count=0,
        )

    monkeypatch.setattr(monitoring, "get_monitoring_overview", overview)

    with _client(admin_dependency=admin_result) as client:
        response = client.get("/api/v1/monitoring/overview")

    assert response.status_code == status_code
