from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _run_row(**overrides):
    values = {
        "run_id": "run-1",
        "session_id": "session-1",
        "status": "plan_ready",
        "stage": "plan",
        "plan_version": 1,
        "approved_plan": {},
        "result_snapshot": None,
        "warning_codes": [],
        "error_code": None,
        "execution_durability": "process_local",
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
        "started_at": None,
        "finished_at": None,
    }
    values.update(overrides)
    return values


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
        return self.fetchrow_results.pop(0) if self.fetchrow_results else None

    async def fetch(self, sql: str, *args: object):
        self.calls.append((sql, args))
        return self.fetch_results.pop(0) if self.fetch_results else []


def test_run_lifecycle_migration_is_additive_and_snapshot_based() -> None:
    sql = (
        ROOT / "app/db/migrations/0002_run_lifecycle.sql"
    ).read_text(encoding="utf-8")
    snapshot = (ROOT / "app/db/schema.sql").read_text(encoding="utf-8")

    for source in (sql, snapshot):
        assert "CREATE TABLE IF NOT EXISTS match_runs" in source
        assert "CREATE TABLE IF NOT EXISTS run_events" in source
        assert "approved_plan" in source
        assert "state_snapshot" in source
        assert "result_snapshot" in source
        assert "warning_codes" in source
        assert "confirmed_resume_version" in source


@pytest.mark.asyncio
async def test_create_run_persists_distinct_run_id(monkeypatch) -> None:
    from app.db import run_store
    from app.domain.run import RunStatus

    connection = Connection(
        fetchrow_results=[_run_row(status="draft", stage=None, plan_version=0)]
    )

    async def fake_get_pool():
        return Pool(connection)

    monkeypatch.setattr(run_store, "get_pool", fake_get_pool)

    run = await run_store.create_run(
        session_id="session-1", run_id="run-1"
    )

    assert run.run_id == "run-1"
    assert run.session_id == "session-1"
    assert run.status is RunStatus.DRAFT
    sql, args = connection.calls[0]
    assert "INSERT INTO match_runs" in sql
    assert "confirmed_resume_version = resume_version" in sql
    assert "state_snapshot" in sql
    assert args[:2] == ("run-1", "session-1")


@pytest.mark.asyncio
async def test_save_match_brief_and_queue_use_cas(monkeypatch) -> None:
    from app.db import run_store
    from app.domain.match_brief import create_match_brief
    from app.domain.run import RunStatus

    brief = create_match_brief(
        career_goal="Find evidence-grounded data analyst roles",
        hard_constraints={"locations": ["Birmingham"]},
        soft_preferences={},
        avoid_roles=[],
        result_count=5,
        plan_version=1,
    )
    connection = Connection(
        fetchrow_results=[
            _run_row(approved_plan=brief.model_dump(mode="json")),
            _run_row(
                status="queued",
                stage=None,
                approved_plan=brief.model_dump(mode="json"),
            ),
        ]
    )

    async def fake_get_pool():
        return Pool(connection)

    monkeypatch.setattr(run_store, "get_pool", fake_get_pool)

    saved = await run_store.save_match_brief(run_id="run-1", brief=brief)
    queued = await run_store.queue_run(
        run_id="run-1",
        plan_version=brief.plan_version,
        plan_hash=brief.plan_hash,
    )

    assert saved.status is RunStatus.PLAN_READY
    assert queued.status is RunStatus.QUEUED
    queue_sql, queue_args = connection.calls[1]
    assert "status = 'plan_ready'" in queue_sql
    assert brief.plan_version in queue_args
    assert brief.plan_hash in queue_args


@pytest.mark.asyncio
async def test_queue_run_rejects_stale_or_duplicate_execute(monkeypatch) -> None:
    from app.db import run_store

    connection = Connection(fetchrow_results=[None])

    async def fake_get_pool():
        return Pool(connection)

    monkeypatch.setattr(run_store, "get_pool", fake_get_pool)

    with pytest.raises(run_store.RunConflict, match="plan_ready"):
        await run_store.queue_run(
            run_id="run-1", plan_version=1, plan_hash="stale"
        )


@pytest.mark.asyncio
async def test_concurrent_duplicate_queue_has_exactly_one_winner(monkeypatch) -> None:
    import asyncio

    from app.db import run_store
    from app.domain.run import MatchRun

    connection = Connection(
        fetchrow_results=[_run_row(status="queued", stage=None), None]
    )

    async def fake_get_pool():
        return Pool(connection)

    monkeypatch.setattr(run_store, "get_pool", fake_get_pool)

    outcomes = await asyncio.gather(
        run_store.queue_run(run_id="run-1", plan_version=1, plan_hash="a" * 64),
        run_store.queue_run(run_id="run-1", plan_version=1, plan_hash="a" * 64),
        return_exceptions=True,
    )

    assert sum(isinstance(item, MatchRun) for item in outcomes) == 1
    assert sum(isinstance(item, run_store.RunConflict) for item in outcomes) == 1


@pytest.mark.asyncio
async def test_save_match_brief_rejects_noncanonical_hash(monkeypatch) -> None:
    from app.db import run_store
    from app.domain.match_brief import MatchBrief, create_match_brief

    valid = create_match_brief(
        career_goal="Find evidence-grounded data analyst roles",
        hard_constraints={},
        soft_preferences={},
        avoid_roles=[],
        result_count=5,
        plan_version=1,
    )
    forged = MatchBrief.model_validate(
        {**valid.model_dump(mode="json"), "plan_hash": "0" * 64}
    )

    with pytest.raises(run_store.RunConflict, match="canonical"):
        await run_store.save_match_brief(run_id="run-1", brief=forged)


@pytest.mark.asyncio
async def test_update_run_stage_only_mutates_running_run(monkeypatch) -> None:
    from app.db import run_store
    from app.domain.run import RunStage

    connection = Connection(fetchrow_results=[{"run_id": "run-1"}])

    async def fake_get_pool():
        return Pool(connection)

    monkeypatch.setattr(run_store, "get_pool", fake_get_pool)

    await run_store.update_run_stage(
        run_id="run-1", stage=RunStage.STRATEGY
    )

    sql, args = connection.calls[0]
    assert "status = 'running'" in sql
    assert args == ("run-1", "strategy")


@pytest.mark.asyncio
async def test_event_store_rejects_private_payload_and_orders_public_events(
    monkeypatch,
) -> None:
    from app.db import event_store

    with pytest.raises(ValueError, match="not public"):
        await event_store.append_event(
            run_id="run-1",
            event_type="stage_started",
            public_payload={"prompt": "private system prompt"},
        )

    rows = [
        {
            "event_id": 1,
            "run_id": "run-1",
            "event_type": "stage_started",
            "stage": "retrieval",
            "status": "running",
            "public_payload": {"message": "Retrieving jobs"},
            "created_at": datetime.now(UTC),
        }
    ]
    connection = Connection(fetchrow_results=rows, fetch_results=[rows])

    async def fake_get_pool():
        return Pool(connection)

    monkeypatch.setattr(event_store, "get_pool", fake_get_pool)

    event = await event_store.append_event(
        run_id="run-1",
        event_type="stage_started",
        stage="retrieval",
        status="running",
        public_payload={"message": "Retrieving jobs"},
    )
    listed = await event_store.list_events(run_id="run-1")

    assert event["event_id"] == 1
    assert listed == rows
    assert "ORDER BY event_id" in connection.calls[-1][0]
