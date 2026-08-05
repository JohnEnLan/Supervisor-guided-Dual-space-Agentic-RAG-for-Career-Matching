from __future__ import annotations

from datetime import UTC, datetime
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
import pytest


def _user(user_id: str):
    from app.api.auth.sessions import AuthedUser

    return AuthedUser(
        user_id=user_id,
        display_name=None,
        avatar_url=None,
        status="active",
        token_version=0,
        is_admin=False,
        created_at=datetime(2026, 8, 5, tzinfo=UTC),
        last_login_at=None,
    )


def _dependency_calls(dependant) -> set[object]:
    calls = {dependency.call for dependency in dependant.dependencies}
    for dependency in dependant.dependencies:
        calls.update(_dependency_calls(dependency))
    return calls


def _api_routes(routes):
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, "original_router"):
            yield from _api_routes(route.original_router.routes)


def test_every_v1_resource_id_route_has_the_matching_ownership_dependency() -> None:
    from app.api.auth.deps import require_owned_run, require_owned_session
    from app.api.v1.router import router

    app = FastAPI()
    app.include_router(router)
    checked = []
    for route in _api_routes(app.routes):
        path_parameters = set(route.param_convertors)
        expected = None
        if "session_id" in path_parameters:
            expected = require_owned_session
        if "run_id" in path_parameters:
            expected = require_owned_run
        if expected is None:
            continue
        checked.append(route.path)
        assert expected in _dependency_calls(route.dependant), route.path

    assert len(checked) == 12


class _Acquire:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _Connection:
    def __init__(self, owner_user_id: str):
        self.owner_user_id = owner_user_id
        self.queries = []

    async def fetchrow(self, sql: str, resource_id: str):
        self.queries.append((" ".join(sql.split()), resource_id))
        return {"owner_user_id": self.owner_user_id}


class _Pool:
    def __init__(self, owner_user_id: str):
        self.connection = _Connection(owner_user_id)

    def acquire(self):
        return _Acquire(self.connection)


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        (
            "post",
            "/api/v1/sessions/session-b/resume",
            {"files": {"file": ("resume.pdf", b"pdf", "application/pdf")}},
        ),
        ("get", "/api/v1/sessions/session-b/resume-preview", {}),
        ("post", "/api/v1/sessions/session-b/resume-confirm", {}),
        ("get", "/api/v1/sessions/session-b/intent-consult", {}),
        (
            "post",
            "/api/v1/sessions/session-b/intent-consult",
            {"json": {"mode": "targeted"}},
        ),
        (
            "post",
            "/api/v1/sessions/session-b/match-brief",
            {
                "json": {
                    "career_goal": "Find evidence-grounded analyst roles",
                    "result_count": 5,
                }
            },
        ),
        (
            "post",
            "/api/v1/runs/run-b/execute",
            {"json": {"plan_version": 1, "plan_hash": "a" * 64}},
        ),
        ("get", "/api/v1/runs/run-b/status", {}),
        ("get", "/api/v1/runs/run-b/conversation", {}),
        ("get", "/api/v1/runs/run-b/result", {}),
        ("get", "/api/v1/runs/run-b/explain", {}),
        (
            "post",
            "/api/v1/runs/run-b/reaction",
            {"json": {"job_id": "job-1", "outcome": "applied"}},
        ),
    ],
)
def test_cross_user_resource_matrix_returns_404(
    monkeypatch, method, path, kwargs
) -> None:
    from app.api.auth import deps
    from app.api.auth.deps import optional_current_user
    from app.api.v1.router import router

    user_a = _user("11111111-1111-1111-1111-111111111111")
    user_b = "22222222-2222-2222-2222-222222222222"
    pool = _Pool(user_b)

    async def get_pool():
        return pool

    monkeypatch.setattr(deps, "get_pool", get_pool)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[optional_current_user] = lambda: user_a

    with TestClient(app) as client:
        response = getattr(client, method)(path, **kwargs)

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_compatibility_without_cookie_does_not_query_ownership(
    monkeypatch,
) -> None:
    from app.api.auth import deps

    async def forbidden_pool():
        raise AssertionError("legacy compatibility must not query ownership")

    monkeypatch.setattr(deps, "get_pool", forbidden_pool)
    assert await deps.require_owned_session("legacy-session", None) is None
    assert await deps.require_owned_run("legacy-run", None) is None


def test_authenticated_session_creation_ignores_legacy_body_user_id(
    monkeypatch,
) -> None:
    from app.api.auth.deps import optional_current_user
    from app.api.v1 import sessions
    from app.api.v1.router import router

    saved = []

    async def save(state, *, status: str, owner_user_id: str | None = None):
        saved.append((state, status, owner_user_id))

    monkeypatch.setattr(sessions, "save_state", save)
    app = FastAPI()
    app.include_router(router)
    user = _user("11111111-1111-1111-1111-111111111111")
    app.dependency_overrides[optional_current_user] = lambda: user

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/sessions",
            json={"user_id": "attacker-controlled-legacy-id"},
        )

    assert response.status_code == 201
    state, status, owner_user_id = saved[0]
    assert state.user_id == user.user_id
    assert owner_user_id == user.user_id
    assert status == "awaiting_resume"


def test_compatibility_session_creation_still_accepts_legacy_user_id(
    monkeypatch,
) -> None:
    from app.api.v1 import sessions
    from app.api.v1.router import router

    saved = []

    async def save(state, *, status: str, owner_user_id: str | None = None):
        saved.append((state, owner_user_id))

    monkeypatch.setattr(sessions, "save_state", save)
    app = FastAPI()
    app.include_router(router)

    with TestClient(app) as client:
        accepted = client.post(
            "/api/v1/sessions", json={"user_id": "legacy-user"}
        )
        missing = client.post("/api/v1/sessions", json={})

    assert accepted.status_code == 201
    assert saved[0][0].user_id == "legacy-user"
    assert saved[0][1] is None
    assert missing.status_code == 422
