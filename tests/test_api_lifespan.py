import asyncio

import pytest


@pytest.mark.asyncio
async def test_lifespan_closes_pool_when_application_context_raises(monkeypatch):
    from app.api import main

    calls: list[str] = []
    monkeypatch.setattr(
        main.settings,
        "langgraph_orchestrator_enabled",
        False,
    )

    async def fake_get_pool():
        calls.append("open")

    async def fake_close_pool():
        calls.append("close")

    async def fake_recover_stale_runs(*, stale_after_seconds):
        assert stale_after_seconds >= 1
        calls.append("recover")
        return 2

    monkeypatch.setattr(main, "get_pool", fake_get_pool)
    monkeypatch.setattr(main, "close_pool", fake_close_pool)
    monkeypatch.setattr(
        main,
        "recover_stale_runs",
        fake_recover_stale_runs,
        raising=False,
    )

    with pytest.raises(RuntimeError, match="application failure"):
        async with main.lifespan(main.app):
            raise RuntimeError("application failure")

    assert calls == ["open", "recover", "close"]


@pytest.mark.asyncio
async def test_lifespan_owns_postgres_checkpointer_when_graph_enabled(
    monkeypatch,
):
    from app.api import main

    calls: list[str] = []
    created = {}

    class FakePool:
        def __init__(self, **kwargs):
            created["pool"] = self
            created["pool_kwargs"] = kwargs
            calls.append("checkpoint_pool:create")

        async def open(self):
            calls.append("checkpoint_pool:open")

        async def wait(self, *, timeout):
            assert timeout == 5
            calls.append("checkpoint_pool:wait")

        async def close(self):
            calls.append("checkpoint_pool:close")

    class FakeSaver:
        def __init__(self, pool, *, serde):
            assert pool is created["pool"]
            created["saver"] = self
            created["serde"] = serde
            calls.append("checkpointer:create")

        async def setup(self):
            calls.append("checkpointer:setup")

        async def adelete_thread(self, thread_id):
            calls.append(f"checkpointer:delete:{thread_id}")

    async def fake_get_pool():
        calls.append("asyncpg:open")

    async def fake_close_pool():
        calls.append("asyncpg:close")

    async def fake_recover_stale_runs(*, stale_after_seconds):
        assert stale_after_seconds >= 1
        calls.append("recover")
        return 0

    async def fake_list_terminal_checkpoint_thread_ids():
        calls.append("terminal_checkpoints:list")
        return ["terminal-run-1", "terminal-run-2"]

    monkeypatch.setattr(
        main.settings,
        "langgraph_orchestrator_enabled",
        True,
    )
    monkeypatch.setattr(main.settings, "database_url", "postgresql://graph")
    monkeypatch.setattr(main, "AsyncConnectionPool", FakePool, raising=False)
    monkeypatch.setattr(main, "AsyncPostgresSaver", FakeSaver, raising=False)
    monkeypatch.setattr(main, "get_pool", fake_get_pool)
    monkeypatch.setattr(main, "close_pool", fake_close_pool)
    monkeypatch.setattr(
        main,
        "recover_stale_runs",
        fake_recover_stale_runs,
    )
    monkeypatch.setattr(
        main,
        "list_terminal_checkpoint_thread_ids",
        fake_list_terminal_checkpoint_thread_ids,
        raising=False,
    )

    async with main.lifespan(main.app):
        assert main.app.state.langgraph_checkpointer is created["saver"]

    assert not hasattr(main.app.state, "langgraph_checkpointer")
    assert created["pool_kwargs"] == {
        "conninfo": "postgresql://graph",
        "min_size": 1,
        "max_size": 4,
        "kwargs": {"autocommit": True, "prepare_threshold": 0},
        "open": False,
    }
    assert created["serde"]._allowed_msgpack_modules == {
        ("app.domain.match_brief", "MatchBrief"),
        ("app.domain.results", "ProductResult"),
        ("app.state.schema", "SharedState"),
    }
    assert calls == [
        "asyncpg:open",
        "checkpoint_pool:create",
        "checkpoint_pool:open",
        "checkpoint_pool:wait",
        "checkpointer:create",
        "checkpointer:setup",
        "recover",
        "terminal_checkpoints:list",
        "checkpointer:delete:terminal-run-1",
        "checkpointer:delete:terminal-run-2",
        "checkpoint_pool:close",
        "asyncpg:close",
    ]


@pytest.mark.asyncio
async def test_lifespan_periodically_sweeps_checkpoints_and_cancels_task(
    monkeypatch,
):
    from app.api import main

    deleted_threads: list[str] = []
    created_tasks: list[asyncio.Task] = []
    periodic_delete_completed = asyncio.Event()
    recover_calls = 0

    class FakePool:
        def __init__(self, **_kwargs):
            pass

        async def open(self):
            pass

        async def wait(self, *, timeout):
            assert timeout == 5

        async def close(self):
            pass

    class FakeSaver:
        def __init__(self, _pool, *, serde):
            del serde

        async def setup(self):
            pass

        async def adelete_thread(self, thread_id):
            deleted_threads.append(thread_id)
            if thread_id == "terminal-run-2":
                periodic_delete_completed.set()

    async def no_op():
        return None

    async def fake_recover_stale_runs(*, stale_after_seconds):
        nonlocal recover_calls
        assert stale_after_seconds >= 1
        recover_calls += 1
        return 0

    async def fake_list_terminal_checkpoint_thread_ids():
        return [f"terminal-run-{recover_calls}"]

    real_create_task = asyncio.create_task

    def recording_create_task(coro):
        task = real_create_task(coro)
        created_tasks.append(task)
        return task

    monkeypatch.setattr(
        main.settings,
        "langgraph_orchestrator_enabled",
        True,
    )
    monkeypatch.setattr(
        main.settings,
        "checkpoint_sweep_interval_seconds",
        0.01,
        raising=False,
    )
    monkeypatch.setattr(main.settings, "database_url", "postgresql://graph")
    monkeypatch.setattr(main, "AsyncConnectionPool", FakePool)
    monkeypatch.setattr(main, "AsyncPostgresSaver", FakeSaver)
    monkeypatch.setattr(main, "get_pool", no_op)
    monkeypatch.setattr(main, "close_pool", no_op)
    monkeypatch.setattr(
        main,
        "recover_stale_runs",
        fake_recover_stale_runs,
    )
    monkeypatch.setattr(
        main,
        "list_terminal_checkpoint_thread_ids",
        fake_list_terminal_checkpoint_thread_ids,
    )
    monkeypatch.setattr(main.asyncio, "create_task", recording_create_task)

    async with main.lifespan(main.app):
        await asyncio.wait_for(periodic_delete_completed.wait(), timeout=1)
        assert len(created_tasks) == 1
        assert not created_tasks[0].done()

    assert created_tasks[0].cancelled()
    assert recover_calls >= 2
    assert deleted_threads[:2] == ["terminal-run-1", "terminal-run-2"]


@pytest.mark.asyncio
async def test_lifespan_disables_periodic_sweep_when_interval_is_zero(
    monkeypatch,
):
    from app.api import main

    class FakePool:
        def __init__(self, **_kwargs):
            pass

        async def open(self):
            pass

        async def wait(self, *, timeout):
            assert timeout == 5

        async def close(self):
            pass

    class FakeSaver:
        def __init__(self, _pool, *, serde):
            del serde

        async def setup(self):
            pass

        async def adelete_thread(self, _thread_id):
            pass

    async def no_op():
        return None

    async def fake_recover_stale_runs(*, stale_after_seconds):
        assert stale_after_seconds >= 1
        return 0

    async def no_terminal_checkpoints():
        return []

    def reject_create_task(coro):
        coro.close()
        raise AssertionError("periodic checkpoint sweep must be disabled")

    monkeypatch.setattr(
        main.settings,
        "langgraph_orchestrator_enabled",
        True,
    )
    monkeypatch.setattr(
        main.settings,
        "checkpoint_sweep_interval_seconds",
        0,
    )
    monkeypatch.setattr(main.settings, "database_url", "postgresql://graph")
    monkeypatch.setattr(main, "AsyncConnectionPool", FakePool)
    monkeypatch.setattr(main, "AsyncPostgresSaver", FakeSaver)
    monkeypatch.setattr(main, "get_pool", no_op)
    monkeypatch.setattr(main, "close_pool", no_op)
    monkeypatch.setattr(
        main,
        "recover_stale_runs",
        fake_recover_stale_runs,
    )
    monkeypatch.setattr(
        main,
        "list_terminal_checkpoint_thread_ids",
        no_terminal_checkpoints,
    )
    monkeypatch.setattr(main.asyncio, "create_task", reject_create_task)

    async with main.lifespan(main.app):
        assert main.app.state.langgraph_checkpointer is not None
