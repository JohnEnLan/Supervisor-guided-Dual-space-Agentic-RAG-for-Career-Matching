from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domain.match_brief import create_match_brief
from app.domain.run import MatchRun, RunStatus
from app.domain.results import ProductResult


PUBLIC_PATHS = {
    "/api/v1/capabilities",
    "/api/v1/sessions",
    "/api/v1/sessions/{session_id}/resume",
    "/api/v1/sessions/{session_id}/resume-preview",
    "/api/v1/sessions/{session_id}/resume-confirm",
    "/api/v1/sessions/{session_id}/intent-consult",
    "/api/v1/sessions/{session_id}/match-brief",
    "/api/v1/runs/{run_id}/execute",
    "/api/v1/runs/{run_id}/status",
    "/api/v1/runs/{run_id}/result",
    "/api/v1/runs/{run_id}/explain",
    "/api/v1/runs/{run_id}/reaction",
}


def _app() -> FastAPI:
    from app.api.v1.router import router

    app = FastAPI()
    app.include_router(router)
    return app


def _run(*, status: RunStatus, result=None) -> MatchRun:
    now = datetime.now(UTC)
    return MatchRun(
        run_id="run-1",
        session_id="session-1",
        status=status,
        stage=None,
        plan_version=1,
        approved_plan={},
        result_snapshot=result,
        created_at=now,
        updated_at=now,
    )


def test_all_public_routes_have_response_models() -> None:
    app = _app()
    public_routes = app.openapi()["paths"]

    assert PUBLIC_PATHS <= set(public_routes)
    for path in PUBLIC_PATHS:
        for operation in public_routes[path].values():
            success = next(
                response
                for code, response in operation["responses"].items()
                if code.startswith("2")
            )
            assert "schema" in success["content"]["application/json"]


def test_match_brief_requires_confirmed_resume(monkeypatch) -> None:
    from app.api.v1 import sessions

    async def not_confirmed(_session_id: str):
        return {"exists": True, "resume_version": 1, "confirmed_resume_version": None}

    monkeypatch.setattr(sessions, "get_resume_metadata", not_confirmed)

    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/sessions/session-1/match-brief",
            json={
                "career_goal": "Find evidence-grounded analyst roles",
                "hard_constraints": {"locations": ["Birmingham"]},
                "soft_preferences": {},
                "avoid_roles": [],
                "result_count": 5,
            },
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "resume must be confirmed"


def test_match_brief_persists_approved_career_state_before_run_snapshot(
    monkeypatch,
) -> None:
    from app.api.v1 import sessions
    from app.state.schema import SharedState

    state = SharedState(session_id="session-1", user_id="private-user")
    call_order: list[str] = []

    async def confirmed(_session_id: str):
        return {
            "exists": True,
            "resume_version": 1,
            "confirmed_resume_version": 1,
        }

    async def load(_session_id: str):
        return state

    async def save(current: SharedState, status: str):
        call_order.append("save_state")
        assert status == "match_brief_approved"
        assert current.career_state.current_goal == [
            "Find evidence-grounded platform engineering roles"
        ]
        assert current.career_state.hard_constraints == {
            "companies": ["OpenAI"]
        }
        assert current.career_state.soft_preferences == {
            "preferred_companies": ["DeepMind"]
        }
        assert current.career_state.avoid_roles == ["sales"]

    async def create(*, session_id: str):
        call_order.append("create_run")
        assert session_id == "session-1"
        assert call_order == ["save_state", "create_run"]
        return _run(status=RunStatus.DRAFT)

    async def save_brief(**_kwargs):
        return _run(status=RunStatus.PLAN_READY)

    monkeypatch.setattr(sessions, "get_resume_metadata", confirmed)
    monkeypatch.setattr(sessions, "load_state", load)
    monkeypatch.setattr(sessions, "save_state", save)
    monkeypatch.setattr(sessions, "create_run", create)
    monkeypatch.setattr(sessions, "save_match_brief", save_brief)

    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/sessions/session-1/match-brief",
            json={
                "career_goal": "Find evidence-grounded platform engineering roles",
                "hard_constraints": {"companies": ["OpenAI"]},
                "soft_preferences": {"preferred_companies": ["DeepMind"]},
                "avoid_roles": ["sales"],
                "result_count": 5,
            },
        )

    assert response.status_code == 201
    assert call_order == ["save_state", "create_run"]


def test_execute_rejects_stale_plan(monkeypatch) -> None:
    from app.api.v1 import runs
    from app.db.run_store import RunConflict

    async def conflict(**_kwargs):
        raise RunConflict("run must be plan_ready")

    monkeypatch.setattr(runs, "queue_run", conflict)

    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/runs/run-1/execute",
            json={"plan_version": 1, "plan_hash": "a" * 64},
        )

    assert response.status_code == 409


def test_resume_confirm_distinguishes_missing_session(monkeypatch) -> None:
    from app.api.v1 import sessions

    async def missing(_session_id: str):
        return {"exists": False}

    monkeypatch.setattr(sessions, "get_resume_metadata", missing)

    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/sessions/missing/resume-confirm"
        )

    assert response.status_code == 404


def test_result_endpoint_returns_only_product_snapshot(monkeypatch) -> None:
    from app.api.v1 import runs

    result = ProductResult(summary="No safe roles").model_dump(mode="json")

    async def completed(**_kwargs):
        return _run(status=RunStatus.COMPLETED, result=result)

    monkeypatch.setattr(runs, "get_run", completed)

    with TestClient(_app()) as client:
        response = client.get("/api/v1/runs/run-1/result")

    assert response.status_code == 200
    payload = response.json()
    assert payload["result"] == result
    assert "state" not in payload
    assert "user_id" not in str(payload)


def test_completed_with_warnings_result_is_readable(monkeypatch) -> None:
    from app.api.v1 import runs

    result = ProductResult(
        summary="Partial result", warnings=["implicit_space_unavailable"]
    ).model_dump(mode="json")

    async def completed(**_kwargs):
        return _run(status=RunStatus.COMPLETED_WITH_WARNINGS, result=result)

    monkeypatch.setattr(runs, "get_run", completed)

    with TestClient(_app()) as client:
        response = client.get("/api/v1/runs/run-1/result")

    assert response.status_code == 200
    assert response.json()["status"] == "completed_with_warnings"


def test_nonterminal_result_returns_recovery_hint(monkeypatch) -> None:
    from app.api.v1 import runs

    async def running(**_kwargs):
        return _run(status=RunStatus.RUNNING)

    monkeypatch.setattr(runs, "get_run", running)

    with TestClient(_app()) as client:
        response = client.get("/api/v1/runs/run-1/result")

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "message": "run result is not ready",
        "recovery": {
            "action": "poll_status",
            "status_url": "/api/v1/runs/run-1/status",
        },
    }


def test_explain_endpoint_allow_list_blocks_private_and_provider_data(monkeypatch) -> None:
    from app.api.v1 import runs
    from app.state.schema import ResumeState, SharedState

    state = SharedState(
        session_id="session-1",
        user_id="private-user",
        resume_state=ResumeState(normalized_base_resume="full private resume"),
        supervisor_log=[
            {
                "stage": "final_verification",
                "prompt": "private prompt",
                "provider_error": "private provider error",
            }
        ],
    )

    async def completed(**_kwargs):
        return _run(
            status=RunStatus.COMPLETED,
            result=ProductResult(summary="Done").model_dump(mode="json"),
        )

    async def snapshot(**_kwargs):
        return state.model_dump(mode="json")

    monkeypatch.setattr(runs, "get_run", completed)
    monkeypatch.setattr(runs, "load_state_snapshot", snapshot)
    monkeypatch.setattr(runs.settings, "evaluation_capability_enabled", True)

    with TestClient(_app()) as client:
        response = client.get("/api/v1/runs/run-1/explain")

    assert response.status_code == 200
    serialized = response.text
    for private_value in (
        "private-user",
        "full private resume",
        "supervisor_log",
        "private prompt",
        "private provider error",
    ):
        assert private_value not in serialized


def test_explain_is_hidden_when_evaluation_capability_is_disabled(monkeypatch) -> None:
    from app.api.v1 import runs

    monkeypatch.setattr(runs.settings, "evaluation_capability_enabled", False)

    with TestClient(_app()) as client:
        response = client.get("/api/v1/runs/run-1/explain")

    assert response.status_code == 404


def test_openapi_v1_snapshot_is_current() -> None:
    from scripts.export_openapi import build_openapi_v1

    snapshot_path = Path("tests/snapshots/openapi_v1.json")
    assert json.loads(snapshot_path.read_text(encoding="utf-8")) == build_openapi_v1()
