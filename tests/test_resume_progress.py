"""B3 解析进度事件（v3 方案 §3.1）：存储层守卫语义 + 终态 CAS 绑定 + API。

覆盖：首事件事务的代数谓词 DELETE（迟到旧任务删不掉新代）、非终态 INSERT
的 resume_queued EXISTS 守卫、终态事件仅随 save/mark 的 CAS 命中写入
（miss 全程零事件）、GET /resume-progress 契约（当前代全量 / 未上传空态 /
done 停轮询语义、覆盖解析中重传交错）。
"""

from __future__ import annotations

from datetime import UTC, datetime
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest


class _Acquire:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Pool:
    def __init__(self, connection):
        self.connection = connection

    def acquire(self):
        return _Acquire(self.connection)


class _Transaction:
    def __init__(self, log=None):
        self._log = log

    async def __aenter__(self):
        if self._log is not None:
            self._log.append("tx-begin")
        return None

    async def __aexit__(self, exc_type, exc, tb):
        if self._log is not None:
            self._log.append("tx-end")
        return False


def _api_app() -> FastAPI:
    from app.api.v1.router import router

    app = FastAPI()
    app.include_router(router)
    return app


def _install_pool(monkeypatch, connection) -> None:
    from app.db import state_store

    async def fake_get_pool():
        return _Pool(connection)

    monkeypatch.setattr(state_store, "get_pool", fake_get_pool)


@pytest.mark.asyncio
async def test_first_event_deletes_only_older_generations_then_inserts(
    monkeypatch,
) -> None:
    from app.db import state_store

    calls = []

    class Connection:
        def transaction(self):
            return _Transaction(calls)

        async def execute(self, sql, *args):
            calls.append((sql, args))
            return "OK"

    _install_pool(monkeypatch, Connection())

    await state_store.record_intake_progress(
        session_id="session-1",
        generation=4,
        seq=1,
        step="received",
        text="收到！",
        elapsed_ms=12,
        first=True,
    )

    statements = [entry for entry in calls if isinstance(entry, tuple)]
    assert calls[0] == "tx-begin"
    assert len(statements) == 2
    delete_sql, delete_args = statements[0]
    assert "DELETE FROM resume_intake_progress" in delete_sql
    # 代数谓词：只清 generation < 本代——迟到旧任务永远删不掉新代事件
    assert "generation < $2" in delete_sql
    assert delete_args == ("session-1", 4)
    insert_sql, insert_args = statements[1]
    assert "INSERT INTO resume_intake_progress" in insert_sql
    # 守卫：仅当会话仍处本代 resume_queued 才落行
    assert "WHERE EXISTS" in insert_sql
    assert "resume_upload_generation = $2" in insert_sql
    assert "status = 'resume_queued'" in insert_sql
    assert "ON CONFLICT" in insert_sql
    assert insert_args == ("session-1", 4, 1, "received", "收到！", 12)
    assert calls[-1] == "tx-end"


@pytest.mark.asyncio
async def test_subsequent_events_insert_without_delete(monkeypatch) -> None:
    from app.db import state_store

    calls = []

    class Connection:
        def transaction(self):
            return _Transaction()

        async def execute(self, sql, *args):
            calls.append((sql, args))
            return "OK"

    _install_pool(monkeypatch, Connection())

    await state_store.record_intake_progress(
        session_id="session-1",
        generation=4,
        seq=3,
        step="normalizing",
        text="梳理中…",
        elapsed_ms=800,
    )

    assert len(calls) == 1
    sql, args = calls[0]
    assert "DELETE" not in sql
    assert "WHERE EXISTS" in sql
    assert args == ("session-1", 4, 3, "normalizing", "梳理中…", 800)


def _locked_row() -> dict:
    state = {
        "session_id": "session-1",
        "user_id": "user-1",
        "resume_state": {"skills": []},
    }
    return {
        "state": json.dumps(state),
        "status": "resume_queued",
        "resume_version": 1,
        "confirmed_resume_version": None,
        "resume_upload_generation": 4,
    }


@pytest.mark.asyncio
async def test_save_writes_terminal_done_event_only_on_cas_hit(
    monkeypatch,
) -> None:
    from app.db import state_store
    from app.state.schema import ResumeState

    calls = []

    class Connection:
        def transaction(self):
            return _Transaction(calls)

        async def fetchrow(self, sql, *args):
            calls.append((sql, args))
            if "FOR UPDATE" in sql:
                return _locked_row()
            assert "RETURNING" in sql
            return {
                "resume_version": 2,
                "confirmed_resume_version": None,
                "resume_content_hash": "x" * 64,
                "resume_confirmed_at": None,
                "resume_upload_generation": 4,
                "status": "resume_ready",
            }

        async def execute(self, sql, *args):
            calls.append((sql, args))
            return "OK"

    _install_pool(monkeypatch, Connection())

    saved = await state_store.save_normalized_resume(
        session_id="session-1",
        resume_state=ResumeState(skills=["Python"]),
        content_hash="x" * 64,
        expected_generation=4,
        terminal_event=state_store.TerminalEvent(
            step="done", text="档案生成完毕，用时 3.2 秒。", elapsed_ms=3200
        ),
    )

    assert saved is not None
    inserts = [
        entry
        for entry in calls
        if isinstance(entry, tuple)
        and "INSERT INTO resume_intake_progress" in entry[0]
    ]
    assert len(inserts) == 1
    assert inserts[0][1] == (
        "session-1", 4, 100, "done", "档案生成完毕，用时 3.2 秒。", 3200,
    )
    # 终态写入位于事务闭合之前（与状态翻转同事务，失败一起回滚）
    assert calls.index(inserts[0]) < calls.index("tx-end")


@pytest.mark.asyncio
async def test_save_cas_miss_writes_no_terminal_event(monkeypatch) -> None:
    from app.db import state_store
    from app.state.schema import ResumeState

    calls = []

    class Connection:
        def transaction(self):
            return _Transaction()

        async def fetchrow(self, sql, *args):
            calls.append((sql, args))
            if "FOR UPDATE" in sql:
                row = _locked_row()
                row["resume_upload_generation"] = 9  # 已重传换代
                return row
            raise AssertionError("CAS miss must short-circuit before UPDATE")

        async def execute(self, sql, *args):
            calls.append((sql, args))
            raise AssertionError("CAS miss must not write any progress event")

    _install_pool(monkeypatch, Connection())

    saved = await state_store.save_normalized_resume(
        session_id="session-1",
        resume_state=ResumeState(skills=["Python"]),
        content_hash="x" * 64,
        expected_generation=4,
        terminal_event=state_store.TerminalEvent(step="done", text="done"),
    )

    assert saved is None


@pytest.mark.asyncio
async def test_mark_error_terminal_event_follows_cas_hit_and_miss(
    monkeypatch,
) -> None:
    from app.db import state_store

    calls = []

    class Connection:
        def __init__(self):
            self.hit = True

        def transaction(self):
            return _Transaction()

        async def fetchrow(self, sql, *args):
            calls.append(("update", args))
            assert "RETURNING" in sql
            return {"session_id": "session-1"} if self.hit else None

        async def execute(self, sql, *args):
            calls.append(("insert", args))
            assert "INSERT INTO resume_intake_progress" in sql
            return "OK"

    connection = Connection()
    _install_pool(monkeypatch, connection)
    event = state_store.TerminalEvent(step="error", text="出了点问题", elapsed_ms=5)

    assert await state_store.mark_resume_error(
        session_id="session-1", expected_generation=4, terminal_event=event
    )
    assert calls == [
        ("update", ("session-1", 4)),
        ("insert", ("session-1", 4, 100, "error", "出了点问题", 5)),
    ]

    calls.clear()
    connection.hit = False
    assert not await state_store.mark_resume_error(
        session_id="session-1", expected_generation=4, terminal_event=event
    )
    # CAS miss：整体 no-op，零事件
    assert calls == [("update", ("session-1", 4))]


def test_progress_endpoint_returns_current_generation_events(monkeypatch) -> None:
    from app.api.v1 import sessions

    async def load(*, session_id: str):
        assert session_id == "session-1"
        return {
            "status": "resume_queued",
            "generation": 4,
            "events": [
                {
                    "seq": 1,
                    "step": "received",
                    "text": "收到！",
                    "elapsed_ms": 10,
                    "created_at": datetime(2026, 8, 9, tzinfo=UTC),
                },
                {
                    "seq": 3,
                    "step": "normalizing",
                    "text": "梳理中…",
                    "elapsed_ms": 900,
                    "created_at": datetime(2026, 8, 9, tzinfo=UTC),
                },
            ],
        }

    monkeypatch.setattr(sessions, "load_intake_progress", load)

    with TestClient(_api_app()) as client:
        response = client.get("/api/v1/sessions/session-1/resume-progress")

    assert response.status_code == 200
    payload = response.json()
    assert payload["generation"] == 4
    assert payload["status"] == "resume_queued"
    assert payload["done"] is False
    assert [event["seq"] for event in payload["events"]] == [1, 3]
    assert payload["events"][0]["text"] == "收到！"


def test_progress_endpoint_empty_and_done_semantics(monkeypatch) -> None:
    from app.api.v1 import sessions

    responses = {
        # 从未上传：generation=null + 空事件，done=true（pending 非 queued）
        "fresh": {"status": "pending", "generation": None, "events": []},
        # 解析中重传交错：新代回到 resume_uploaded → done=true 停轮询回落确认卡
        "reuploaded": {
            "status": "resume_uploaded",
            "generation": 5,
            "events": [],
        },
    }
    current = {"key": "fresh"}

    async def load(*, session_id: str):
        return responses[current["key"]]

    monkeypatch.setattr(sessions, "load_intake_progress", load)

    with TestClient(_api_app()) as client:
        fresh = client.get("/api/v1/sessions/session-1/resume-progress")
        current["key"] = "reuploaded"
        reuploaded = client.get("/api/v1/sessions/session-1/resume-progress")

    assert fresh.status_code == 200
    assert fresh.json() == {
        "generation": None,
        "status": "pending",
        "events": [],
        "done": True,
    }
    assert reuploaded.json()["done"] is True
    assert reuploaded.json()["generation"] == 5


def test_progress_endpoint_404_for_unknown_session(monkeypatch) -> None:
    from app.api.v1 import sessions

    async def load(*, session_id: str):
        return None

    monkeypatch.setattr(sessions, "load_intake_progress", load)

    with TestClient(_api_app()) as client:
        response = client.get("/api/v1/sessions/ghost/resume-progress")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_load_intake_progress_shapes(monkeypatch) -> None:
    from app.db import state_store

    class Connection:
        def __init__(self, session_row, event_rows):
            self.session_row = session_row
            self.event_rows = event_rows
            self.fetch_args = None

        async def fetchrow(self, sql, *args):
            return self.session_row

        async def fetch(self, sql, *args):
            assert "ORDER BY seq" in sql
            self.fetch_args = args
            return self.event_rows

    # 会话不存在 → None
    _install_pool(monkeypatch, Connection(None, []))
    assert await state_store.load_intake_progress(session_id="ghost") is None

    # 从未上传（generation=0）→ generation=None 且不查事件表
    class NoFetch(Connection):
        async def fetch(self, sql, *args):
            raise AssertionError("generation=0 must not query events")

    _install_pool(
        monkeypatch,
        NoFetch({"status": "pending", "resume_upload_generation": 0}, []),
    )
    fresh = await state_store.load_intake_progress(session_id="session-1")
    assert fresh == {"status": "pending", "generation": None, "events": []}

    # 正常路径：按当前代取事件
    connection = Connection(
        {"status": "resume_queued", "resume_upload_generation": 4},
        [
            {
                "seq": 1,
                "step": "received",
                "text": "收到！",
                "elapsed_ms": 10,
                "created_at": datetime(2026, 8, 9, tzinfo=UTC),
            }
        ],
    )
    _install_pool(monkeypatch, connection)
    loaded = await state_store.load_intake_progress(session_id="session-1")
    assert loaded is not None
    assert loaded["generation"] == 4
    assert connection.fetch_args == ("session-1", 4)
    assert [event["step"] for event in loaded["events"]] == ["received"]
