from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from scripts.cutover_cnuk_demo import CutoverBlocked, switch_corpus


class Connection:
    def __init__(self, *, active_runs=0, jobs=3, chunks=7):
        self.active_runs = active_runs
        self.jobs = jobs
        self.chunks = chunks
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
        if "FROM jobs" in sql and "count(*)" in sql and "job_chunks" not in sql:
            return self.jobs
        if "job_chunks" in sql:
            return self.chunks
        if "bool_and" in sql:
            return True
        raise AssertionError(sql)

    async def execute(self, sql, *args):
        self.commands.append((sql, args))
        return "UPDATE 3"


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
