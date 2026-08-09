from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
import pytest

from app.domain.run import MatchRun, RunStatus
from app.state.schema import SharedState


class _Acquire:
    def __init__(self, connection) -> None:
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _Transaction:
    def __init__(self, outcomes: list[str] | None = None) -> None:
        self.outcomes = outcomes

    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, traceback):
        if self.outcomes is not None:
            self.outcomes.append("rollback" if exc_type else "commit")
        return False


class _Connection:
    def __init__(
        self,
        *,
        fetchrow_results=None,
        fetch_results=None,
        execute_error_at: int | None = None,
        transaction_outcomes: list[str] | None = None,
    ) -> None:
        self.fetchrow_results = list(fetchrow_results or [])
        self.fetch_results = list(fetch_results or [])
        self.execute_error_at = execute_error_at
        self.transaction_outcomes = transaction_outcomes
        self.calls: list[tuple[str, str, tuple[object, ...]]] = []
        self.execute_count = 0

    def transaction(self):
        return _Transaction(self.transaction_outcomes)

    async def fetchrow(self, sql: str, *args: object):
        self.calls.append(("fetchrow", " ".join(sql.split()), args))
        return self.fetchrow_results.pop(0)

    async def fetch(self, sql: str, *args: object):
        self.calls.append(("fetch", " ".join(sql.split()), args))
        return self.fetch_results.pop(0)

    async def execute(self, sql: str, *args: object):
        self.execute_count += 1
        self.calls.append(("execute", " ".join(sql.split()), args))
        if self.execute_error_at == self.execute_count:
            raise RuntimeError("simulated database failure")
        return "UPDATE 1"


class _Pool:
    def __init__(self, connection) -> None:
        self.connection = connection

    def acquire(self):
        return _Acquire(self.connection)


def _install_pool(monkeypatch, module, connection) -> None:
    async def get_pool():
        return _Pool(connection)

    monkeypatch.setattr(module, "get_pool", get_pool)


def _client(*, admin_dependency=None) -> TestClient:
    from app.api.auth.deps import require_admin
    from app.api.v1.router import router

    app = FastAPI()
    app.include_router(router)
    if admin_dependency is not None:
        app.dependency_overrides[require_admin] = admin_dependency
    return TestClient(app)


def _run(status: RunStatus) -> MatchRun:
    now = datetime(2026, 8, 9, tzinfo=UTC)
    return MatchRun(
        run_id="run-cross-user",
        session_id="session-other-owner",
        confirmed_resume_version=1,
        status=status,
        created_at=now,
        updated_at=now,
    )


def test_admin_dto_fields_are_required_even_when_nullable() -> None:
    from app.api.v1.schemas import (
        AdminOverviewResponse,
        AdminTokensByModelRow,
        AdminUserResumeResponse,
        AdminUserRow,
        AdminUsersPageResponse,
    )

    assert set(AdminOverviewResponse.model_json_schema()["required"]) == {
        "users_total",
        "logins_today",
        "logins_7d",
        "logins_30d",
        "sessions_total",
        "consult_turns_total",
        "runs_total",
        "tokens_by_day",
        "tokens_by_model",
    }
    assert set(AdminTokensByModelRow.model_json_schema()["required"]) == {
        "model",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
    }
    assert set(AdminUserRow.model_json_schema()["required"]) == {
        "user_id",
        "email",
        "created_at",
        "last_login_at",
        "session_count",
        "resume_name",
        "resume_phone",
        "resume_school",
        "resume_degree",
    }
    assert set(AdminUsersPageResponse.model_json_schema()["required"]) == {
        "items",
        "page",
        "has_more",
    }
    assert set(AdminUserResumeResponse.model_json_schema()["required"]) == {
        "user_id",
        "session_id",
        "resume_state",
        "reset_session_id",
    }


@pytest.mark.asyncio
async def test_admin_overview_uses_utc_day_boundaries_and_nullable_sums(
    monkeypatch,
) -> None:
    from app.db import admin_store

    connection = _Connection(
        fetchrow_results=[
            {
                "users_total": 4,
                "logins_today": 1,
                "logins_7d": 3,
                "logins_30d": 8,
                "sessions_total": 6,
                "consult_turns_total": 9,
                "runs_total": 5,
            }
        ],
        fetch_results=[
            [{"date": "2026-08-09", "total_tokens": 120}],
            [
                {
                    "model": "reranker-v1",
                    "prompt_tokens": None,
                    "completion_tokens": None,
                    "total_tokens": 44,
                }
            ],
        ],
    )
    _install_pool(monkeypatch, admin_store, connection)

    result = await admin_store.get_admin_overview()

    assert result == {
        "users_total": 4,
        "logins_today": 1,
        "logins_7d": 3,
        "logins_30d": 8,
        "sessions_total": 6,
        "consult_turns_total": 9,
        "runs_total": 5,
        "tokens_by_day": [{"date": "2026-08-09", "total_tokens": 120}],
        "tokens_by_model": [
            {
                "model": "reranker-v1",
                "prompt_tokens": None,
                "completion_tokens": None,
                "total_tokens": 44,
            }
        ],
    }
    aggregate_sql = connection.calls[0][1]
    by_day_sql = connection.calls[1][1]
    by_model_sql = connection.calls[2][1]
    assert aggregate_sql.count("AT TIME ZONE 'UTC'") >= 3
    assert "interval '6 days'" in aggregate_sql
    assert "interval '29 days'" in aggregate_sql
    assert "kind = 'login'" in aggregate_sql
    assert "kind = 'consult_turn'" in aggregate_sql
    assert "AT TIME ZONE 'UTC'" in by_day_sql
    assert "interval '29 days'" in by_day_sql
    assert "created_at >=" in by_day_sql
    assert "WITH usage_by_day AS" in by_day_sql
    assert "GROUP BY day" in by_day_sql
    assert "SUM(prompt_tokens)" in by_model_sql
    assert "SUM(completion_tokens)" in by_model_sql
    assert "COALESCE(SUM(prompt_tokens), 0)" not in by_model_sql
    assert "COALESCE(SUM(completion_tokens), 0)" not in by_model_sql


@pytest.mark.asyncio
async def test_admin_overview_empty_database_returns_zero_counts(
    monkeypatch,
) -> None:
    from app.db import admin_store

    connection = _Connection(
        fetchrow_results=[
            {
                "users_total": 0,
                "logins_today": 0,
                "logins_7d": 0,
                "logins_30d": 0,
                "sessions_total": 0,
                "consult_turns_total": 0,
                "runs_total": 0,
            }
        ],
        fetch_results=[[], []],
    )
    _install_pool(monkeypatch, admin_store, connection)

    result = await admin_store.get_admin_overview()

    assert result["users_total"] == 0
    assert result["logins_today"] == 0
    assert result["tokens_by_day"] == []
    assert result["tokens_by_model"] == []


@pytest.mark.asyncio
async def test_admin_users_query_has_stable_latest_resume_and_email_ordering(
    monkeypatch,
) -> None:
    from app.db import admin_store

    now = datetime(2026, 8, 9, tzinfo=UTC)
    rows = [
        {
            "user_id": f"00000000-0000-0000-0000-{index:012d}",
            "email": "first@example.com",
            "created_at": now,
            "last_login_at": now,
            "session_count": 3,
            "resume_name": "Ada Lovelace",
            "resume_phone": "+44 7700 900123",
            "resume_school": "University of Birmingham",
            "resume_degree": "MSc",
        }
        for index in range(21)
    ]
    connection = _Connection(fetch_results=[rows])
    _install_pool(monkeypatch, admin_store, connection)

    result = await admin_store.list_admin_users(page=2)

    assert result["page"] == 2
    assert result["page_size"] == 20
    assert result["has_more"] is True
    assert len(result["items"]) == 20
    assert result["items"][0]["email"] == "first@example.com"
    assert result["items"][0]["session_count"] == 3
    sql = connection.calls[0][1]
    assert "ORDER BY identity.created_at ASC, identity.identity_id ASC" in sql
    assert "session.resume_confirmed_at DESC NULLS LAST" in sql
    assert "session.resume_version DESC" in sql
    assert "session.session_id ASC" in sql
    assert "SELECT COUNT(*) FROM session_state AS counted_session" in sql
    assert "education,0,institution" in sql
    assert "education,0,degree" in sql
    assert connection.calls[0][2] == (21, 20)


@pytest.mark.asyncio
async def test_admin_users_resume_paths_resolve_against_real_state_shape(
    monkeypatch,
) -> None:
    import re

    from app.db import admin_store

    connection = _Connection(fetch_results=[[]])
    _install_pool(monkeypatch, admin_store, connection)

    await admin_store.list_admin_users(page=1)

    sql = connection.calls[0][1]
    paths = re.findall(r"#>> '\{([^}]*)\}'", sql)
    assert paths

    # 与 resume_intake SYSTEM_PROMPT 输出 shape 一致的最小真实 state。
    real_shape_state = {
        "resume_state": {
            "contact": {
                "name": "Ada Lovelace",
                "phone": "+44 7700 900123",
                "email": "ada@example.com",
                "evidence_span_ids": ["s1"],
            },
            "education": [
                {
                    "institution": "University of Birmingham",
                    "degree": "MSc",
                    "field": "Computer Science",
                    "dates": "2024 - 2025",
                    "details": [],
                    "evidence_span_ids": ["s2"],
                }
            ],
        }
    }
    for path in paths:
        value: object = real_shape_state
        for segment in path.split(","):
            if isinstance(value, list):
                index = int(segment)
                value = value[index] if index < len(value) else None
            elif isinstance(value, dict):
                value = value.get(segment)
            else:
                value = None
            if value is None:
                break
        assert isinstance(value, str) and value, (
            f"SQL JSON path {{{path}}} does not resolve on the real "
            "resume_state shape"
        )


@pytest.mark.asyncio
async def test_admin_user_resume_distinguishes_no_resume_from_missing_user(
    monkeypatch,
) -> None:
    from app.db import admin_store

    user_id = "11111111-1111-1111-1111-111111111111"
    connection = _Connection(
        fetchrow_results=[
            {
                "user_id": user_id,
                "session_id": None,
                "resume_state": None,
                "reset_session_id": None,
            },
            None,
        ]
    )
    _install_pool(monkeypatch, admin_store, connection)

    no_resume = await admin_store.get_admin_user_resume(user_id=user_id)
    missing = await admin_store.get_admin_user_resume(
        user_id="22222222-2222-2222-2222-222222222222"
    )

    assert no_resume == {
        "user_id": user_id,
        "session_id": None,
        "resume_state": None,
        "reset_session_id": None,
    }
    assert missing is None
    sql = connection.calls[0][1]
    assert "LEFT JOIN LATERAL" in sql
    assert "resume_confirmed_at DESC NULLS LAST" in sql
    assert "resume_version DESC" in sql
    assert "session_id ASC" in sql


@pytest.mark.asyncio
async def test_admin_user_resume_reset_target_prefers_active_parse_session(
    monkeypatch,
) -> None:
    """首解析卡 queued（v0）时 resume LATERAL 无行，reset 靶仍可见；
    旧 ready + 新 queued 时两列必须指向不同会话。"""
    from app.db import admin_store

    user_id = "11111111-1111-1111-1111-111111111111"
    connection = _Connection(
        fetchrow_results=[
            {
                "user_id": user_id,
                "session_id": None,
                "resume_state": None,
                "reset_session_id": "sess-queued-v0",
            },
            {
                "user_id": user_id,
                "session_id": "sess-old-ready",
                "resume_state": None,
                "reset_session_id": "sess-new-queued",
            },
        ]
    )
    _install_pool(monkeypatch, admin_store, connection)

    first_parse_stuck = await admin_store.get_admin_user_resume(user_id=user_id)
    old_ready_new_queued = await admin_store.get_admin_user_resume(
        user_id=user_id
    )

    assert first_parse_stuck["session_id"] is None
    assert first_parse_stuck["reset_session_id"] == "sess-queued-v0"
    assert old_ready_new_queued["session_id"] == "sess-old-ready"
    assert old_ready_new_queued["reset_session_id"] == "sess-new-queued"

    sql = connection.calls[0][1]
    assert "reset_target.session_id AS reset_session_id" in sql
    assert "COALESCE(target.resume_parse_count, 0) > 0" in sql
    assert "target.status = 'resume_queued'" in sql
    # queued 优先于 updated_at：旧 ready 会话被普通状态写入刷新
    # updated_at 时也不得压过新卡住的 queued 会话；status 列可空，
    # NULLS LAST 防 NULL-status 行越过 queued（DESC 默认 NULLS FIRST）。
    normalized_sql = " ".join(sql.split())
    assert (
        "ORDER BY (target.status = 'resume_queued') DESC NULLS LAST,"
        " target.updated_at DESC, target.session_id DESC"
    ) in normalized_sql


def test_admin_overview_and_users_endpoints_return_typed_payloads(
    monkeypatch,
) -> None:
    from app.api.v1 import admin

    now = datetime(2026, 8, 9, tzinfo=UTC)

    async def overview():
        return {
            "users_total": 1,
            "logins_today": 1,
            "logins_7d": 1,
            "logins_30d": 1,
            "sessions_total": 2,
            "consult_turns_total": 3,
            "runs_total": 4,
            "tokens_by_day": [{"date": "2026-08-09", "total_tokens": 10}],
            "tokens_by_model": [
                {
                    "model": "deepseek",
                    "prompt_tokens": 4,
                    "completion_tokens": 6,
                    "total_tokens": 10,
                }
            ],
        }

    async def users(*, page: int):
        assert page == 3
        return {
            "items": [
                {
                    "user_id": "11111111-1111-1111-1111-111111111111",
                    "email": None,
                    "created_at": now,
                    "last_login_at": None,
                    "session_count": 0,
                    "resume_name": None,
                    "resume_phone": None,
                    "resume_school": None,
                    "resume_degree": None,
                }
            ],
            "page": 3,
            "page_size": 20,
            "has_more": False,
        }

    monkeypatch.setattr(admin, "get_admin_overview", overview)
    monkeypatch.setattr(admin, "list_admin_users", users)
    with _client(admin_dependency=lambda: None) as client:
        overview_response = client.get("/api/v1/admin/overview")
        users_response = client.get("/api/v1/admin/users?page=3")

    assert overview_response.status_code == 200
    assert overview_response.json()["tokens_by_model"][0]["prompt_tokens"] == 4
    assert users_response.status_code == 200
    assert users_response.json()["page_size"] == 20


@pytest.mark.parametrize(
    ("stored", "status_code", "expected_session"),
    [
        (
            {
                "user_id": "11111111-1111-1111-1111-111111111111",
                "session_id": None,
                "resume_state": None,
                "reset_session_id": None,
            },
            200,
            None,
        ),
        (None, 404, None),
    ],
)
def test_admin_user_resume_endpoint_has_200_null_and_404_states(
    monkeypatch, stored, status_code, expected_session
) -> None:
    from app.api.v1 import admin

    async def load(*, user_id: str):
        assert user_id == "11111111-1111-1111-1111-111111111111"
        return stored

    monkeypatch.setattr(admin, "get_admin_user_resume", load)
    with _client(admin_dependency=lambda: None) as client:
        response = client.get(
            "/api/v1/admin/users/11111111-1111-1111-1111-111111111111/resume"
        )

    assert response.status_code == status_code
    if status_code == 200:
        assert response.json() == {
            "user_id": "11111111-1111-1111-1111-111111111111",
            "session_id": expected_session,
            "resume_state": None,
            "reset_session_id": None,
        }


def test_admin_user_resume_endpoint_rejects_malformed_user_id_with_404(
    monkeypatch,
) -> None:
    from app.api.v1 import admin

    store_calls: list[str] = []

    async def load(*, user_id: str):
        store_calls.append(user_id)
        return None

    monkeypatch.setattr(admin, "get_admin_user_resume", load)
    with _client(admin_dependency=lambda: None) as client:
        response = client.get("/api/v1/admin/users/not-a-uuid/resume")

    assert response.status_code == 404
    assert store_calls == []


def test_admin_user_resume_endpoint_normalizes_uuid_variants_for_store(
    monkeypatch,
) -> None:
    """uuid.UUID 接受 urn:uuid: 等变体，但 asyncpg 编码器不收——
    进 store 的必须是规范化字符串。"""
    from app.api.v1 import admin

    received: list[str] = []

    async def load(*, user_id: str):
        received.append(user_id)
        return None

    monkeypatch.setattr(admin, "get_admin_user_resume", load)
    with _client(admin_dependency=lambda: None) as client:
        response = client.get(
            "/api/v1/admin/users/"
            "urn:uuid:11111111-1111-1111-1111-111111111111/resume"
        )

    assert response.status_code == 404
    assert received == ["11111111-1111-1111-1111-111111111111"]


@pytest.mark.parametrize(
    ("run", "snapshot", "status_code"),
    [
        (None, None, 404),
        (_run(RunStatus.RUNNING), None, 409),
        (_run(RunStatus.COMPLETED), None, 404),
    ],
)
def test_admin_explain_error_states(monkeypatch, run, snapshot, status_code) -> None:
    from app.api.v1 import admin

    async def load_run(*, run_id: str):
        assert run_id == "run-cross-user"
        return run

    async def load_snapshot(*, run_id: str):
        assert run_id == "run-cross-user"
        return snapshot

    monkeypatch.setattr(admin, "get_run", load_run)
    monkeypatch.setattr(admin, "load_state_snapshot", load_snapshot)
    with _client(admin_dependency=lambda: None) as client:
        response = client.get("/api/v1/admin/runs/run-cross-user/explain")

    assert response.status_code == status_code


def test_admin_explain_cross_user_bypasses_evaluation_flag(monkeypatch) -> None:
    from app.api.v1 import admin

    async def completed(*, run_id: str):
        assert run_id == "run-cross-user"
        return _run(RunStatus.COMPLETED_WITH_WARNINGS)

    async def snapshot(*, run_id: str):
        assert run_id == "run-cross-user"
        return SharedState(
            session_id="session-other-owner",
            user_id="other-user",
        ).model_dump(mode="json")

    monkeypatch.setattr(admin, "get_run", completed)
    monkeypatch.setattr(admin, "load_state_snapshot", snapshot)
    monkeypatch.setattr(admin.settings, "evaluation_capability_enabled", False)
    with _client(admin_dependency=lambda: None) as client:
        response = client.get("/api/v1/admin/runs/run-cross-user/explain")

    assert response.status_code == 200
    assert response.json()["run_id"] == "run-cross-user"
    assert response.json()["fusion"]["implicit_max_weight"] == pytest.approx(
        admin.settings.implicit_max_weight
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "count", "expected_status", "execute_count"),
    [
        # queued 遗留清理不以计数为前提（§5.3 字面；count=0+queued 是
        # refund 成功但 mark 失败的双故障孤儿，短路会让它永卡——协调者
        # 验收修正）
        ("resume_queued", 0, "resume_error", 2),
        ("resume_queued", 2, "resume_error", 2),
        ("resume_uploaded", 2, "resume_uploaded", 1),
        ("resume_ready", 2, "resume_ready", 1),
        ("resume_ready", 0, "resume_ready", 0),
    ],
)
async def test_reset_parse_count_three_state_semantics(
    monkeypatch, status, count, expected_status, execute_count
) -> None:
    from app.db import admin_store

    connection = _Connection(
        fetchrow_results=[
            {
                "session_id": "session-1",
                "status": status,
                "resume_parse_count": count,
                "resume_upload_generation": 7,
            }
        ]
    )
    _install_pool(monkeypatch, admin_store, connection)

    result = await admin_store.reset_resume_parse_count(session_id="session-1")

    assert result == {
        "session_id": "session-1",
        "resume_parse_count": 0,
        "status": expected_status,
    }
    assert connection.calls[0][0] == "fetchrow"
    assert "FOR UPDATE" in connection.calls[0][1]
    assert connection.execute_count == execute_count
    executed_sql = [sql for method, sql, _args in connection.calls if method == "execute"]
    assert all("resume_intake_progress" not in sql for sql in executed_sql)
    if status == "resume_queued":
        assert "status = 'resume_error'" in executed_sql[0]
        assert "resume_queued" not in executed_sql[0].split("SET", 1)[1]
        assert "content = NULL" in executed_sql[1]
        assert "extracted_text = NULL" in executed_sql[1]
    elif count > 0:
        assert "status =" not in executed_sql[0].split("SET", 1)[1]
        assert all("resume_uploads" not in sql for sql in executed_sql)


@pytest.mark.asyncio
async def test_reset_parse_count_missing_session_raises_key_error(
    monkeypatch,
) -> None:
    from app.db import admin_store

    connection = _Connection(fetchrow_results=[None])
    _install_pool(monkeypatch, admin_store, connection)

    with pytest.raises(KeyError, match="missing"):
        await admin_store.reset_resume_parse_count(session_id="missing")


@pytest.mark.asyncio
async def test_reset_parse_count_rolls_back_if_upload_clear_fails(
    monkeypatch,
) -> None:
    from app.db import admin_store

    outcomes: list[str] = []
    connection = _Connection(
        fetchrow_results=[
            {
                "session_id": "session-1",
                "status": "resume_queued",
                "resume_parse_count": 2,
                "resume_upload_generation": 7,
            }
        ],
        execute_error_at=2,
        transaction_outcomes=outcomes,
    )
    _install_pool(monkeypatch, admin_store, connection)

    with pytest.raises(RuntimeError, match="simulated database failure"):
        await admin_store.reset_resume_parse_count(session_id="session-1")

    assert outcomes == ["rollback"]


@pytest.mark.asyncio
async def test_reset_serializes_with_inflight_normalization(monkeypatch) -> None:
    from app.db import admin_store, state_store
    from app.state.schema import ResumeState

    class Database:
        def __init__(self) -> None:
            self.lock = asyncio.Lock()
            self.reset_updated = asyncio.Event()
            self.normalization_waiting = asyncio.Event()
            self.allow_reset_finish = asyncio.Event()
            self.events: list[str] = []
            self.upload_cleared = False
            self.row = {
                "session_id": "session-1",
                "state": SharedState(
                    session_id="session-1",
                    user_id="user-1",
                ).model_dump_json(),
                "status": "resume_queued",
                "resume_parse_count": 1,
                "resume_upload_generation": 7,
                "resume_version": 0,
                "confirmed_resume_version": None,
            }

    class Transaction:
        def __init__(self, connection) -> None:
            self.connection = connection

        async def __aenter__(self):
            return None

        async def __aexit__(self, exc_type, exc, traceback):
            if self.connection.locked:
                self.connection.database.events.append(
                    f"{self.connection.operation}_unlock"
                )
                self.connection.database.lock.release()
                self.connection.locked = False
            return False

    class Connection:
        def __init__(self, database: Database) -> None:
            self.database = database
            self.locked = False
            self.operation = "unknown"

        def transaction(self):
            return Transaction(self)

        async def fetchrow(self, sql: str, *_args: object):
            assert "FOR UPDATE" in sql
            self.operation = (
                "normalization" if "SELECT state, status" in sql else "reset"
            )
            if self.operation == "normalization" and self.database.lock.locked():
                self.database.events.append("normalization_waiting")
                self.database.normalization_waiting.set()
            await self.database.lock.acquire()
            self.locked = True
            self.database.events.append(f"{self.operation}_locked")
            return dict(self.database.row)

        async def execute(self, sql: str, *_args: object):
            if "UPDATE session_state" in sql:
                assert self.operation == "reset"
                self.database.row["resume_parse_count"] = 0
                self.database.row["status"] = "resume_error"
                self.database.events.append("reset_state_updated")
                self.database.reset_updated.set()
                await self.database.allow_reset_finish.wait()
                return "UPDATE 1"
            if "UPDATE resume_uploads" in sql:
                self.database.upload_cleared = True
                self.database.events.append("upload_cleared")
                return "UPDATE 1"
            raise AssertionError(sql)

    class Pool:
        def __init__(self, database: Database) -> None:
            self.database = database

        def acquire(self):
            return _Acquire(Connection(self.database))

    database = Database()

    async def get_pool():
        return Pool(database)

    monkeypatch.setattr(admin_store, "get_pool", get_pool)
    monkeypatch.setattr(state_store, "get_pool", get_pool)

    reset_task = asyncio.create_task(
        admin_store.reset_resume_parse_count(session_id="session-1")
    )
    await database.reset_updated.wait()
    normalization_task = asyncio.create_task(
        state_store.save_normalized_resume(
            session_id="session-1",
            resume_state=ResumeState(skills=["Python"]),
            content_hash="a" * 64,
            expected_generation=7,
        )
    )
    await database.normalization_waiting.wait()
    database.allow_reset_finish.set()

    reset_result, normalization_result = await asyncio.gather(
        reset_task,
        normalization_task,
    )

    assert reset_result["status"] == "resume_error"
    assert normalization_result is None
    assert database.row["status"] == "resume_error"
    assert database.row["resume_version"] == 0
    assert database.upload_cleared is True
    assert database.events == [
        "reset_locked",
        "reset_state_updated",
        "normalization_waiting",
        "upload_cleared",
        "reset_unlock",
        "normalization_locked",
        "normalization_unlock",
    ]


def test_reset_endpoint_maps_missing_session_and_preserves_status(
    monkeypatch,
) -> None:
    from app.api.v1 import admin

    async def reset(*, session_id: str):
        if session_id == "missing":
            raise KeyError(session_id)
        return {
            "session_id": session_id,
            "resume_parse_count": 0,
            "status": "resume_error",
        }

    monkeypatch.setattr(admin, "reset_resume_parse_count", reset)
    with _client(admin_dependency=lambda: None) as client:
        success = client.post(
            "/api/v1/admin/sessions/session-1/reset-parse-count"
        )
        missing = client.post(
            "/api/v1/admin/sessions/missing/reset-parse-count"
        )

    assert success.status_code == 200
    assert success.json() == {
        "session_id": "session-1",
        "resume_parse_count": 0,
        "status": "resume_error",
    }
    assert missing.status_code == 404


def test_reset_store_docstring_pins_same_generation_requeue_redline() -> None:
    from app.db.admin_store import reset_resume_parse_count

    doc = reset_resume_parse_count.__doc__ or ""
    assert "resume_queued" in doc
    assert "resume_intake_progress" in doc


def test_all_admin_routes_require_admin() -> None:
    from app.api.auth.deps import require_admin
    from app.api.v1 import admin

    assert len(admin.router.routes) == 5
    for route in admin.router.routes:
        assert isinstance(route, APIRoute)
        assert [dependency.call for dependency in route.dependant.dependencies] == [
            require_admin
        ]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/admin/overview"),
        ("get", "/api/v1/admin/users"),
        (
            "get",
            "/api/v1/admin/users/11111111-1111-1111-1111-111111111111/resume",
        ),
        ("get", "/api/v1/admin/runs/run-1/explain"),
        ("post", "/api/v1/admin/sessions/session-1/reset-parse-count"),
    ],
)
def test_each_admin_endpoint_rejects_non_admin(method, path) -> None:
    async def forbidden():
        raise HTTPException(status_code=403, detail="administrator required")

    with _client(admin_dependency=forbidden) as client:
        response = getattr(client, method)(path)

    assert response.status_code == 403
