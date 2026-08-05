from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from scripts.cutover_cnuk_demo import CutoverBlocked, switch_corpus


class Connection:
    def __init__(self, *, active_runs=0, jobs=3, chunks=7):
        self.active_runs = active_runs
        self.jobs = jobs
        self.chunks = chunks
        self.snapshot_count = 0
        self.commands: list[tuple[str, tuple]] = []

    @asynccontextmanager
    async def transaction(self):
        self.commands.append(("BEGIN", ()))
        try:
            yield
        finally:
            self.commands.append(("END", ()))

    async def fetchval(self, sql, *args):
        self.commands.append((sql, args))
        if "match_runs" in sql:
            return self.active_runs
        if "count(*)" in sql and "corpus_cutover_snapshot" in sql:
            return self.snapshot_count
        if "FROM jobs" in sql and "count(*)" in sql and "job_chunks" not in sql:
            return self.jobs
        if "job_chunks" in sql:
            return self.chunks
        if "bool_and" in sql:
            return True
        raise AssertionError(sql)

    async def execute(self, sql, *args):
        self.commands.append((sql, args))
        if "INSERT INTO corpus_cutover_snapshot" in sql:
            self.snapshot_count = self.jobs
        if "DELETE FROM corpus_cutover_snapshot" in sql:
            self.snapshot_count = 0
        return "UPDATE 3"


class StatefulConnection(Connection):
    def __init__(self) -> None:
        super().__init__(active_runs=0, jobs=1, chunks=1)
        self.rows = {
            "legacy-open": {"source_tag": "legacy-fixrev", "is_open": True},
            "legacy-closed": {"source_tag": "legacy-fixrev", "is_open": False},
            "demo-new": {"source_tag": "demo-v1", "is_open": False},
        }
        self.snapshot: dict[str, bool] = {}

    async def fetchval(self, sql, *args):
        self.commands.append((sql, args))
        if "match_runs" in sql:
            return 0
        if "count(*)" in sql and "corpus_cutover_snapshot" in sql:
            return len(self.snapshot)
        if "job_chunks" in sql:
            return sum(
                row["source_tag"] == args[0] for row in self.rows.values()
            )
        if "FROM jobs" in sql and "count(*)" in sql:
            return sum(
                row["source_tag"] == args[0] for row in self.rows.values()
            )
        if "bool_and" in sql and "corpus_cutover_snapshot" in sql:
            return all(
                self.rows[job_id]["is_open"] == was_open
                for job_id, was_open in self.snapshot.items()
                if job_id in self.rows
            )
        if "bool_and" in sql:
            source_tag, expected_open = args
            matching = [
                row
                for row in self.rows.values()
                if row["source_tag"] == source_tag
            ]
            return bool(matching) and all(
                row["is_open"] == expected_open for row in matching
            )
        raise AssertionError(sql)

    async def execute(self, sql, *args):
        self.commands.append((sql, args))
        normalized = " ".join(sql.split())
        if "pg_advisory_xact_lock" in sql:
            return "SELECT 1"
        if "CREATE TABLE IF NOT EXISTS corpus_cutover_snapshot" in sql:
            return "CREATE TABLE"
        if "INSERT INTO corpus_cutover_snapshot" in sql and "__cutover_marker__" in sql:
            self.snapshot["__cutover_marker__"] = False
            return "INSERT 0 1"
        if "INSERT INTO corpus_cutover_snapshot" in sql:
            old_source_tags = set(args[0])
            self.snapshot = {
                job_id: bool(row["is_open"])
                for job_id, row in self.rows.items()
                if row["source_tag"] is None
                or row["source_tag"] in old_source_tags
            }
            return f"INSERT 0 {len(self.snapshot)}"
        if (
            "UPDATE jobs" in normalized
            and "FROM corpus_cutover_snapshot" in normalized
        ):
            restored = 0
            for job_id, was_open in self.snapshot.items():
                if job_id in self.rows:
                    self.rows[job_id]["is_open"] = was_open
                    restored += 1
            return f"UPDATE {restored}"
        if "DELETE FROM corpus_cutover_snapshot" in sql:
            deleted = len(self.snapshot)
            self.snapshot.clear()
            return f"DELETE {deleted}"
        if "SET is_open = FALSE" in normalized and "source_tag IS NULL" in normalized:
            old_source_tags = set(args[0])
            for row in self.rows.values():
                if row["source_tag"] is None or row["source_tag"] in old_source_tags:
                    row["is_open"] = False
            return "UPDATE 2"
        if "SET is_open = TRUE" in normalized and "source_tag = $1" in normalized:
            for row in self.rows.values():
                if row["source_tag"] == args[0]:
                    row["is_open"] = True
            return "UPDATE 1"
        if "SET is_open = FALSE" in normalized and "source_tag = $1" in normalized:
            for row in self.rows.values():
                if row["source_tag"] == args[0]:
                    row["is_open"] = False
            return "UPDATE 1"
        raise AssertionError(sql)


class Pool:
    def __init__(self, connection):
        self.connection = connection

    @asynccontextmanager
    async def acquire(self):
        yield self.connection


@pytest.mark.asyncio
async def test_cutover_refuses_when_any_run_is_queued_or_running() -> None:
    connection = Connection(active_runs=1)

    with pytest.raises(CutoverBlocked, match="active runs"):
        await switch_corpus(
            Pool(connection),
            direction="forward",
            source_tag="demo-v1",
            expected_jobs=3,
            expected_chunks=7,
        )

    assert not any(
        command.lstrip().upper().startswith("UPDATE JOBS")
        for command, _args in connection.commands
    )


@pytest.mark.asyncio
async def test_cutover_locks_exclusively_before_rechecking_active_runs() -> None:
    connection = Connection(active_runs=1)

    with pytest.raises(CutoverBlocked, match="active runs"):
        await switch_corpus(
            Pool(connection),
            direction="forward",
            source_tag="demo-v1",
            expected_jobs=3,
            expected_chunks=7,
        )

    lock_index = next(
        index
        for index, (sql, _args) in enumerate(connection.commands)
        if "pg_advisory_xact_lock" in sql
    )
    recheck_index = next(
        index
        for index, (sql, _args) in enumerate(connection.commands)
        if "match_runs" in sql
    )
    lock_sql, lock_args = connection.commands[lock_index]
    assert "pg_advisory_xact_lock($1)" in lock_sql
    assert lock_args == (4_851_018_008_693_645_601,)
    assert lock_index < recheck_index


@pytest.mark.asyncio
async def test_cutover_reconciles_counts_and_flips_both_directions() -> None:
    connection = Connection()
    pool = Pool(connection)

    forward = await switch_corpus(
        pool,
        direction="forward",
        source_tag="demo-v1",
        expected_jobs=3,
        expected_chunks=7,
    )
    backward = await switch_corpus(
        pool,
        direction="rollback",
        source_tag="demo-v1",
        expected_jobs=3,
        expected_chunks=7,
    )

    assert forward["direction"] == "forward"
    assert backward["direction"] == "rollback"
    updates = [sql for sql, _args in connection.commands if sql.lstrip().upper().startswith("UPDATE JOBS")]
    assert any("source_tag = $1" in sql and "is_open = TRUE" in sql for sql in updates)
    assert any("source_tag = $1" in sql and "is_open = FALSE" in sql for sql in updates)


@pytest.mark.asyncio
async def test_forward_and_rollback_restore_each_legacy_visibility_value() -> None:
    connection = StatefulConnection()
    pool = Pool(connection)
    original = {
        job_id: bool(row["is_open"])
        for job_id, row in connection.rows.items()
        if row["source_tag"] == "legacy-fixrev"
    }

    await switch_corpus(
        pool,
        direction="forward",
        source_tag="demo-v1",
        expected_jobs=1,
        expected_chunks=1,
        old_source_tags=("legacy-fixrev",),
    )

    assert connection.snapshot == {**original, "__cutover_marker__": False}
    assert all(
        not connection.rows[job_id]["is_open"] for job_id in original
    )

    await switch_corpus(
        pool,
        direction="rollback",
        source_tag="demo-v1",
        expected_jobs=1,
        expected_chunks=1,
        old_source_tags=("legacy-fixrev",),
    )

    assert {
        job_id: bool(connection.rows[job_id]["is_open"])
        for job_id in original
    } == original
    assert connection.rows["demo-new"]["is_open"] is False
    assert connection.snapshot == {}
    snapshot_ddl = next(
        sql
        for sql, _args in connection.commands
        if "CREATE TABLE IF NOT EXISTS corpus_cutover_snapshot" in sql
    )
    assert "job_id TEXT PRIMARY KEY" in snapshot_ddl
    assert "was_open BOOLEAN NOT NULL" in snapshot_ddl


@pytest.mark.asyncio
async def test_forward_without_legacy_rows_still_records_rollbackable_cutover() -> None:
    # 复审 P2：干净部署（零 legacy 行）forward 后快照为空，rollback 被拒，
    # 新语料再也关不掉——哨兵行保证 rollback 永远可用
    connection = StatefulConnection()
    connection.rows = {
        "demo-new": {"source_tag": "demo-v1", "is_open": False},
    }
    pool = Pool(connection)

    await switch_corpus(
        pool,
        direction="forward",
        source_tag="demo-v1",
        expected_jobs=1,
        expected_chunks=1,
        old_source_tags=("legacy-fixrev",),
    )

    assert connection.snapshot == {"__cutover_marker__": False}
    assert connection.rows["demo-new"]["is_open"] is True

    await switch_corpus(
        pool,
        direction="rollback",
        source_tag="demo-v1",
        expected_jobs=1,
        expected_chunks=1,
        old_source_tags=("legacy-fixrev",),
    )

    assert connection.rows["demo-new"]["is_open"] is False
    assert connection.snapshot == {}
