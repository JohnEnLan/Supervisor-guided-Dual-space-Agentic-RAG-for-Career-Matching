from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from fastapi import FastAPI, HTTPException
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


def _api_routes(routes, prefix=""):
    for route in routes:
        if isinstance(route, APIRoute):
            yield route, f"{prefix}{route.path}"
        elif hasattr(route, "original_router"):
            nested_prefix = f"{prefix}{route.include_context.prefix}"
            yield from _api_routes(
                route.original_router.routes,
                nested_prefix,
            )


def test_every_v1_resource_id_route_has_the_matching_ownership_dependency() -> None:
    from app.api.auth.deps import require_owned_run, require_owned_session
    from app.api.v1.router import router

    app = FastAPI()
    app.include_router(router)
    checked = []
    for route, path in _api_routes(app.routes):
        if path.startswith("/api/v1/admin/"):
            continue
        path_parameters = set(route.param_convertors)
        expected = None
        if "session_id" in path_parameters:
            expected = require_owned_session
        if "run_id" in path_parameters:
            expected = require_owned_run
        if expected is None:
            continue
        checked.append(path)
        assert expected in _dependency_calls(route.dependant), path

    # B2 新增 GET /resume-upload 与 POST /resume/parse（13→15）；
    # B3 新增 GET /resume-progress（15→16）
    # B5 admin paths are checked separately below and do not change this 16.
    assert len(checked) == 16


def test_every_admin_route_has_admin_dependency() -> None:
    from app.api.auth.deps import require_admin
    from app.api.v1.router import router

    app = FastAPI()
    app.include_router(router)
    checked = []
    for route, path in _api_routes(app.routes):
        if not path.startswith("/api/v1/admin/"):
            continue
        checked.append(path)
        assert require_admin in _dependency_calls(route.dependant), path

    assert len(checked) == 5


class _Acquire:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _Connection:
    def __init__(self, owner_user_id: str | None):
        self.owner_user_id = owner_user_id
        self.queries = []

    async def fetchrow(self, sql: str, resource_id: str):
        self.queries.append((" ".join(sql.split()), resource_id))
        return {"owner_user_id": self.owner_user_id}


class _Pool:
    def __init__(self, owner_user_id: str | None):
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
        ("get", "/api/v1/sessions/session-b/consult", {}),
        (
            "post",
            "/api/v1/sessions/session-b/consult",
            {
                "json": {
                    "mode": "targeted",
                    "message": "继续",
                    "expected_round": 0,
                }
            },
        ),
        ("post", "/api/v1/sessions/session-b/consult/finalize", {}),
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


@pytest.mark.asyncio
async def test_authenticated_user_cannot_claim_ownerless_session(
    monkeypatch,
) -> None:
    from app.api.auth import deps

    pool = _Pool(None)

    async def get_pool():
        return pool

    monkeypatch.setattr(deps, "get_pool", get_pool)

    with pytest.raises(HTTPException) as exc_info:
        await deps.require_owned_session(
            "ownerless-session",
            _user("11111111-1111-1111-1111-111111111111"),
        )

    assert exc_info.value.status_code == 404


def test_authenticated_session_creation_uses_cookie_owner_and_rejects_legacy_field(
    monkeypatch,
) -> None:
    from app.api.auth.deps import optional_current_user
    from app.api.v1 import sessions
    from app.api.v1.router import router

    saved = []

    async def create_owned(state, *, owner_user_id: str, quota: int):
        saved.append((state, "awaiting_resume", owner_user_id, quota))
        return True

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("authenticated creation must use the atomic quota store")

    monkeypatch.setattr(sessions, "create_owned_session_with_quota", create_owned, raising=False)
    monkeypatch.setattr(sessions, "save_state", forbidden)
    app = FastAPI()
    app.include_router(router)
    user = _user("11111111-1111-1111-1111-111111111111")
    app.dependency_overrides[optional_current_user] = lambda: user

    with TestClient(app) as client:
        response = client.post("/api/v1/sessions")
        legacy = client.post(
            "/api/v1/sessions",
            json={"user_id": "attacker-controlled-legacy-id"},
        )

    assert response.status_code == 201
    assert legacy.status_code == 422
    state, status, owner_user_id, quota = saved[0]
    assert state.user_id == user.user_id
    assert owner_user_id == user.user_id
    assert status == "awaiting_resume"
    assert quota == sessions.settings.session_quota_per_user


def test_compatibility_session_creation_without_cookie_is_ownerless(
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
        accepted = client.post("/api/v1/sessions")

    assert accepted.status_code == 201
    assert saved[0][0].user_id == accepted.json()["session_id"]
    assert saved[0][1] is None


def test_session_quota_returns_402_paywall_and_anonymous_is_exempt(
    monkeypatch,
) -> None:
    # B.2 付费墙：每账号默认 3 个会话额度，超出 402；兼容模式匿名不计额度
    from app.api.auth.deps import optional_current_user
    from app.api.v1 import sessions
    from app.api.v1.router import router

    saved = []

    async def save(state, *, status: str, owner_user_id: str | None = None):
        saved.append(owner_user_id)

    async def create_owned(*_args, **_kwargs) -> bool:
        return False

    monkeypatch.setattr(sessions, "save_state", save)
    monkeypatch.setattr(sessions, "create_owned_session_with_quota", create_owned, raising=False)
    app = FastAPI()
    app.include_router(router)
    user = _user("11111111-1111-1111-1111-111111111111")
    app.dependency_overrides[optional_current_user] = lambda: user

    with TestClient(app) as client:
        blocked = client.post("/api/v1/sessions")

    assert blocked.status_code == 402
    assert blocked.json()["detail"] == "session_quota_exceeded"
    assert saved == []

    # 匿名（兼容模式）不查额度也不该被挡
    app.dependency_overrides[optional_current_user] = lambda: None
    with TestClient(app) as client:
        anonymous = client.post("/api/v1/sessions")
    assert anonymous.status_code == 201


def test_session_quota_allows_creation_below_limit(monkeypatch) -> None:
    from app.api.auth.deps import optional_current_user
    from app.api.v1 import sessions
    from app.api.v1.router import router

    async def create_owned(*_args, **_kwargs) -> bool:
        return True

    monkeypatch.setattr(sessions, "create_owned_session_with_quota", create_owned, raising=False)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[optional_current_user] = lambda: _user(
        "11111111-1111-1111-1111-111111111111"
    )

    with TestClient(app) as client:
        response = client.post("/api/v1/sessions")

    assert response.status_code == 201


@pytest.mark.asyncio
async def test_concurrent_session_quota_count_and_insert_are_atomic(monkeypatch) -> None:
    from app.db import state_store
    from app.state.schema import SharedState

    class Database:
        def __init__(self) -> None:
            self.lock = asyncio.Lock()
            self.rows: list[str] = []
            self.events: list[str] = []

    class Transaction:
        def __init__(self, connection) -> None:
            self.connection = connection

        async def __aenter__(self):
            self.connection.database.events.append("begin")

        async def __aexit__(self, exc_type, exc, traceback):
            if self.connection.locked:
                self.connection.database.lock.release()
                self.connection.locked = False
            self.connection.database.events.append("end")
            return False

    class Connection:
        def __init__(self, database: Database) -> None:
            self.database = database
            self.locked = False

        def transaction(self):
            return Transaction(self)

        async def execute(self, sql, *args):
            if "pg_advisory_xact_lock" in sql:
                await self.database.lock.acquire()
                self.locked = True
                self.database.events.append("lock")
                return "SELECT 1"
            if "INSERT INTO session_state" in sql:
                self.database.rows.append(str(args[0]))
                self.database.events.append("insert")
                return "INSERT 0 1"
            raise AssertionError(sql)

        async def fetchval(self, sql, *_args):
            assert "SELECT count(*)" in sql
            self.database.events.append("count")
            await asyncio.sleep(0)
            return len(self.database.rows)

    class Acquire:
        def __init__(self, database: Database) -> None:
            self.connection = Connection(database)

        async def __aenter__(self):
            return self.connection

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    class Pool:
        def __init__(self, database: Database) -> None:
            self.database = database

        def acquire(self):
            return Acquire(self.database)

    database = Database()

    async def get_pool():
        return Pool(database)

    monkeypatch.setattr(state_store, "get_pool", get_pool)
    owner = "11111111-1111-1111-1111-111111111111"
    states = [
        SharedState(session_id=f"session-{index}", user_id=owner)
        for index in range(2)
    ]

    accepted = await asyncio.gather(
        *(
            state_store.create_owned_session_with_quota(
                state,
                owner_user_id=owner,
                quota=1,
            )
            for state in states
        )
    )

    assert sorted(accepted) == [False, True]
    assert len(database.rows) == 1
    assert database.events[:3] == ["begin", "lock", "count"]
