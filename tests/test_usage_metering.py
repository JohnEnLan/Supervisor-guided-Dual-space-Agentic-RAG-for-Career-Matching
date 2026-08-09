from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import TypedDict

import httpx
import pytest


class _Acquire:
    def __init__(self, connection) -> None:
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None


class _Pool:
    def __init__(self, connection) -> None:
        self.connection = connection

    def acquire(self) -> _Acquire:
        return _Acquire(self.connection)


class _RecordingConnection:
    def __init__(self, outcomes=()) -> None:
        self.calls: list[tuple[str, tuple]] = []
        self.outcomes = deque(outcomes)

    async def execute(self, sql: str, *args):
        self.calls.append((" ".join(sql.split()), args))
        if self.outcomes:
            outcome = self.outcomes.popleft()
            if isinstance(outcome, BaseException):
                raise outcome
        return "INSERT 0 1"


@pytest.fixture
def usage_module(monkeypatch):
    from app.llm import usage_context

    usage_context.reset_usage_recorder()
    yield usage_context
    usage_context.reset_usage_recorder()


def _patch_pool(monkeypatch, usage_context, connection) -> None:
    async def get_pool():
        return _Pool(connection)

    monkeypatch.setattr(usage_context, "get_pool", get_pool)


def _llm_rows(connection: _RecordingConnection) -> list[tuple]:
    return [args for sql, args in connection.calls if "INSERT INTO llm_usage" in sql]


def _event_rows(connection: _RecordingConnection) -> list[tuple]:
    return [
        args for sql, args in connection.calls if "INSERT INTO product_events" in sql
    ]


@pytest.mark.asyncio
async def test_u1_nested_usage_scope_restores_outer_attribution(
    monkeypatch,
    usage_module,
) -> None:
    connection = _RecordingConnection()
    _patch_pool(monkeypatch, usage_module, connection)

    async with usage_module.usage_scope("owner-1", "session-1", "consult"):
        await usage_module.record_llm_usage("deepseek", "fast", 3, 2, 5)
        async with usage_module.usage_scope("owner-1", "session-1", "coach"):
            await usage_module.record_llm_usage("deepseek", "pro", 7, 4, 11)
        await usage_module.record_llm_usage("deepseek", "fast", 5, 3, 8)

    assert _llm_rows(connection) == [
        ("owner-1", "session-1", "deepseek", "fast", "consult", 3, 2, 5),
        ("owner-1", "session-1", "deepseek", "pro", "coach", 7, 4, 11),
        ("owner-1", "session-1", "deepseek", "fast", "consult", 5, 3, 8),
    ]


@pytest.mark.asyncio
async def test_u2_concurrent_usage_scopes_are_isolated(
    monkeypatch,
    usage_module,
) -> None:
    connection = _RecordingConnection()
    _patch_pool(monkeypatch, usage_module, connection)
    first_entered = asyncio.Event()
    second_recorded = asyncio.Event()

    async def first_task() -> None:
        async with usage_module.usage_scope("owner-a", "session-a", "run"):
            first_entered.set()
            await second_recorded.wait()
            await usage_module.record_llm_usage("deepseek", "a", 1, 1, 2)

    async def second_task() -> None:
        await first_entered.wait()
        async with usage_module.usage_scope("owner-b", "session-b", "consult"):
            await usage_module.record_llm_usage("deepseek", "b", 2, 2, 4)
        second_recorded.set()

    await asyncio.gather(first_task(), second_task())

    assert set(_llm_rows(connection)) == {
        ("owner-a", "session-a", "deepseek", "a", "run", 1, 1, 2),
        ("owner-b", "session-b", "deepseek", "b", "consult", 2, 2, 4),
    }


@pytest.mark.asyncio
async def test_u3_recorder_failures_are_fail_open(
    monkeypatch,
    usage_module,
) -> None:
    async def broken_pool():
        raise RuntimeError("pool unavailable")

    monkeypatch.setattr(usage_module, "get_pool", broken_pool)
    await usage_module.record_llm_usage("deepseek", "fast", 1, 1, 2)
    await usage_module.record_product_event("login", "owner-1")

    connection = _RecordingConnection([RuntimeError("insert failed")])
    _patch_pool(monkeypatch, usage_module, connection)
    await usage_module.record_llm_usage("deepseek", "fast", 1, 1, 2)


@pytest.mark.asyncio
async def test_u3_cancelled_error_passes_through_without_arming_breaker(
    monkeypatch,
    usage_module,
) -> None:
    connection = _RecordingConnection([asyncio.CancelledError(), None])
    _patch_pool(monkeypatch, usage_module, connection)

    with pytest.raises(asyncio.CancelledError):
        await usage_module.record_llm_usage("deepseek", "fast", 1, 1, 2)
    await usage_module.record_llm_usage("deepseek", "fast", 1, 1, 2)

    assert len(connection.calls) == 2


@pytest.mark.asyncio
async def test_u3_breaker_silences_window_and_recovers_on_successful_probe(
    monkeypatch,
    usage_module,
    caplog,
) -> None:
    clock = [100.0]
    monkeypatch.setattr(usage_module.time, "monotonic", lambda: clock[0])
    connection = _RecordingConnection([RuntimeError("down")] * 5 + [None, None])
    _patch_pool(monkeypatch, usage_module, connection)

    for _ in range(5):
        await usage_module.record_llm_usage("deepseek", "fast", 1, 1, 2)
    await usage_module.record_llm_usage("deepseek", "fast", 1, 1, 2)
    assert len(connection.calls) == 5

    clock[0] = 400.0
    await usage_module.record_llm_usage("deepseek", "fast", 1, 1, 2)
    await usage_module.record_llm_usage("deepseek", "fast", 1, 1, 2)

    assert len(connection.calls) == 7
    assert sum("usage recorder disabled" in record.message for record in caplog.records) == 1
    assert len(caplog.records) == 1


@pytest.mark.asyncio
async def test_u3_failed_probe_rearms_breaker_for_a_new_window(
    monkeypatch,
    usage_module,
    caplog,
) -> None:
    clock = [10.0]
    monkeypatch.setattr(usage_module.time, "monotonic", lambda: clock[0])
    connection = _RecordingConnection([RuntimeError("down")] * 6)
    _patch_pool(monkeypatch, usage_module, connection)

    for _ in range(5):
        await usage_module.record_product_event("login", "owner-1")
    clock[0] = 310.0
    await usage_module.record_product_event("login", "owner-1")
    await usage_module.record_product_event("login", "owner-1")

    assert len(connection.calls) == 6
    assert sum("usage recorder disabled" in record.message for record in caplog.records) == 2
    assert len(caplog.records) == 2


@pytest.mark.asyncio
async def test_u3_late_inflight_failure_neither_rewarns_nor_extends_window(
    monkeypatch,
    usage_module,
    caplog,
) -> None:
    clock = [100.0]
    monkeypatch.setattr(usage_module.time, "monotonic", lambda: clock[0])

    gate = asyncio.Event()

    class _GatedConnection(_RecordingConnection):
        async def execute(self, sql: str, *args):
            self.calls.append((" ".join(sql.split()), args))
            if len(self.calls) == 1:
                await gate.wait()
                raise RuntimeError("late failure")
            if len(self.calls) <= 6:
                raise RuntimeError("down")
            return "INSERT 0 1"

    connection = _GatedConnection()
    _patch_pool(monkeypatch, usage_module, connection)

    late = asyncio.create_task(
        usage_module.record_llm_usage("deepseek", "fast", 1, 1, 2)
    )
    for _ in range(50):
        if connection.calls:
            break
        await asyncio.sleep(0)
    assert len(connection.calls) == 1

    for _ in range(5):
        await usage_module.record_llm_usage("deepseek", "fast", 1, 1, 2)
    assert (
        sum("usage recorder disabled" in r.message for r in caplog.records) == 1
    )

    clock[0] = 350.0
    gate.set()
    await late
    # 迟到失败不得再次告警，也不得把 deadline 从 400 后移到 650。
    assert (
        sum("usage recorder disabled" in r.message for r in caplog.records) == 1
    )

    clock[0] = 401.0
    await usage_module.record_llm_usage("deepseek", "fast", 1, 1, 2)

    assert len(connection.calls) == 7
    assert (
        sum("usage recorder disabled" in r.message for r in caplog.records) == 1
    )


@pytest.mark.asyncio
async def test_u3_late_inflight_success_does_not_unlock_armed_window(
    monkeypatch,
    usage_module,
) -> None:
    clock = [100.0]
    monkeypatch.setattr(usage_module.time, "monotonic", lambda: clock[0])

    gate = asyncio.Event()

    class _GatedConnection(_RecordingConnection):
        async def execute(self, sql: str, *args):
            self.calls.append((" ".join(sql.split()), args))
            if len(self.calls) == 1:
                await gate.wait()
                return "INSERT 0 1"
            if len(self.calls) <= 6:
                raise RuntimeError("down")
            return "INSERT 0 1"

    connection = _GatedConnection()
    _patch_pool(monkeypatch, usage_module, connection)

    late = asyncio.create_task(
        usage_module.record_llm_usage("deepseek", "fast", 1, 1, 2)
    )
    for _ in range(50):
        if connection.calls:
            break
        await asyncio.sleep(0)
    assert len(connection.calls) == 1

    for _ in range(5):
        await usage_module.record_llm_usage("deepseek", "fast", 1, 1, 2)

    clock[0] = 200.0
    gate.set()
    await late
    # 迟到成功与迟到失败对称：不得解锁武装中的窗口，窗口内写入仍被拒。
    await usage_module.record_llm_usage("deepseek", "fast", 1, 1, 2)
    assert len(connection.calls) == 6

    clock[0] = 401.0
    await usage_module.record_llm_usage("deepseek", "fast", 1, 1, 2)
    await usage_module.record_llm_usage("deepseek", "fast", 1, 1, 2)

    assert len(connection.calls) == 8


@pytest.mark.asyncio
async def test_u3_success_resets_consecutive_failure_count(
    monkeypatch,
    usage_module,
) -> None:
    outcomes = [RuntimeError("down")] * 4 + [None] + [RuntimeError("down")] * 4
    connection = _RecordingConnection(outcomes)
    _patch_pool(monkeypatch, usage_module, connection)

    for _ in outcomes:
        await usage_module.record_product_event("consult_turn", "owner-1")

    assert len(connection.calls) == 9


@pytest.mark.asyncio
async def test_u6_unscoped_usage_is_recorded_without_owner_or_session(
    monkeypatch,
    usage_module,
) -> None:
    connection = _RecordingConnection()
    _patch_pool(monkeypatch, usage_module, connection)

    await usage_module.record_llm_usage("deepseek", "fast", 1, 2, 3)
    await usage_module.record_product_event("session_created", None)

    assert _llm_rows(connection) == [
        (None, None, "deepseek", "fast", "unscoped", 1, 2, 3)
    ]
    assert _event_rows(connection) == [("session_created", None)]


def test_ddl_oracle_migration_and_schema_have_same_five_metering_statements() -> None:
    root = Path(__file__).resolve().parents[1]
    migration = (
        root / "app/db/migrations/0011_llm_usage_and_product_events.sql"
    ).read_text(encoding="utf-8")
    schema = (root / "app/db/schema.sql").read_text(encoding="utf-8")
    names = {
        "llm_usage",
        "idx_llm_usage_created",
        "idx_llm_usage_user",
        "product_events",
        "idx_product_events_kind",
    }

    def statements(sql: str) -> dict[str, str]:
        found = {}
        for statement in re.findall(r"CREATE\s+(?:TABLE|INDEX).*?;", sql, re.S | re.I):
            match = re.search(
                r"CREATE\s+(?:TABLE|INDEX)\s+IF\s+NOT\s+EXISTS\s+([a-z_]+)",
                statement,
                re.I,
            )
            if match and match.group(1).casefold() in names:
                found[match.group(1).casefold()] = " ".join(statement.split())
        return found

    migration_statements = statements(migration)
    schema_statements = statements(schema)
    assert set(migration_statements) == names
    assert schema_statements == migration_statements


@pytest.mark.asyncio
async def test_u4_deepseek_records_one_row_for_one_provider_request(
    monkeypatch,
) -> None:
    from app.llm import deepseek

    recorded = []

    async def record(*args):
        recorded.append(args)

    async def create(**_kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=SimpleNamespace(
                prompt_tokens=11,
                completion_tokens=7,
                total_tokens=18,
            ),
        )

    monkeypatch.setattr(deepseek.usage_context, "record_llm_usage", record)
    monkeypatch.setattr(deepseek._client.chat.completions, "create", create)

    assert await deepseek.chat("system", "user") == "ok"
    assert recorded == [
        (
            "deepseek",
            deepseek.settings.deepseek_model_fast,
            11,
            7,
            18,
        )
    ]


@pytest.mark.asyncio
async def test_u4_qwen_embed_records_only_missing_provider_batch(
    monkeypatch,
) -> None:
    from app.llm import qwen_embed

    recorded = []
    provider_calls = 0

    async def record(*args):
        recorded.append(args)

    async def create(**kwargs):
        nonlocal provider_calls
        provider_calls += 1
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=[0.1, 0.2]) for _ in kwargs["input"]],
            usage=SimpleNamespace(prompt_tokens=4, total_tokens=4),
        )

    qwen_embed.clear_embedding_cache()
    monkeypatch.setattr(qwen_embed.usage_context, "record_llm_usage", record)
    monkeypatch.setattr(qwen_embed._client.embeddings, "create", create)

    assert await qwen_embed.embed_one("metering-cache-key") == [0.1, 0.2]
    assert await qwen_embed.embed_one("metering-cache-key") == [0.1, 0.2]
    assert provider_calls == 1
    assert recorded == [
        (
            "dashscope",
            qwen_embed.settings.qwen_embed_model,
            4,
            None,
            4,
        )
    ]
    qwen_embed.clear_embedding_cache()


@pytest.mark.asyncio
async def test_u4_qwen_vl_records_three_token_counts(monkeypatch) -> None:
    from app.llm import qwen_vl

    recorded = []

    async def record(*args):
        recorded.append(args)

    async def create(**_kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=" OCR text "))],
            usage=SimpleNamespace(
                prompt_tokens=13,
                completion_tokens=5,
                total_tokens=18,
            ),
        )

    monkeypatch.setattr(qwen_vl.usage_context, "record_llm_usage", record)
    monkeypatch.setattr(qwen_vl._client.chat.completions, "create", create)

    assert await qwen_vl.ocr_image_jpeg(b"jpeg") == "OCR text"
    assert recorded == [
        (
            "dashscope",
            qwen_vl.settings.qwen_vl_model,
            13,
            5,
            18,
        )
    ]


class _MeteringRerankClient:
    response: httpx.Response

    def __init__(self, *, timeout: float) -> None:
        del timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args) -> None:
        return None

    async def post(self, endpoint: str, **_kwargs):
        del endpoint
        return self.response


def _rerank_response(*, usage) -> httpx.Response:
    return httpx.Response(
        200,
        request=httpx.Request("POST", "https://example.test/rerank"),
        content=json.dumps(
            {
                "output": {
                    "results": [
                        {"index": 1, "relevance_score": 0.25},
                        {"index": 0, "relevance_score": 0.75},
                    ]
                },
                "usage": usage,
            }
        ).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


@pytest.mark.asyncio
async def test_u7_reranker_records_total_tokens_without_realigning_scores(
    monkeypatch,
) -> None:
    from app.llm import reranker

    recorded = []

    async def record(*args):
        recorded.append(args)

    _MeteringRerankClient.response = _rerank_response(
        usage={"total_tokens": 17}
    )
    monkeypatch.setattr(reranker.httpx, "AsyncClient", _MeteringRerankClient)
    monkeypatch.setattr(
        reranker.settings,
        "rerank_endpoint",
        "https://example.test/rerank",
    )
    monkeypatch.setattr(reranker.usage_context, "record_llm_usage", record)

    scores = await reranker.rerank_documents("query", ["first", "second"])

    assert scores == [0.75, 0.25]
    assert recorded == [
        (
            "dashscope",
            reranker.settings.rerank_model,
            None,
            None,
            17,
        )
    ]


@pytest.mark.asyncio
async def test_u7_reranker_malformed_usage_does_not_change_scores(
    monkeypatch,
    caplog,
) -> None:
    from app.llm import reranker

    recorded = []

    async def record(*args):
        recorded.append(args)

    _MeteringRerankClient.response = _rerank_response(
        usage={"total_tokens": "seventeen"}
    )
    monkeypatch.setattr(reranker.httpx, "AsyncClient", _MeteringRerankClient)
    monkeypatch.setattr(
        reranker.settings,
        "rerank_endpoint",
        "https://example.test/rerank",
    )
    monkeypatch.setattr(reranker.usage_context, "record_llm_usage", record)

    scores = await reranker.rerank_documents("query", ["first", "second"])

    assert scores == [0.75, 0.25]
    assert recorded == []
    assert any("usage" in record.message for record in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("client_name", ["deepseek", "qwen_embed", "qwen_vl"])
async def test_u4_openai_compatible_clients_ignore_malformed_usage(
    monkeypatch,
    caplog,
    client_name,
) -> None:
    recorded = []

    async def record(*args):
        recorded.append(args)

    if client_name == "deepseek":
        from app.llm import deepseek as client

        async def create(**_kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
                usage=SimpleNamespace(total_tokens="bad"),
            )

        monkeypatch.setattr(client.usage_context, "record_llm_usage", record)
        monkeypatch.setattr(client._client.chat.completions, "create", create)
        result = await client.chat("system", "user")
        assert result == "ok"
    elif client_name == "qwen_embed":
        from app.llm import qwen_embed as client

        async def create(**_kwargs):
            return SimpleNamespace(
                data=[SimpleNamespace(embedding=[0.3])],
                usage=SimpleNamespace(prompt_tokens=1, total_tokens="bad"),
            )

        client.clear_embedding_cache()
        monkeypatch.setattr(client.usage_context, "record_llm_usage", record)
        monkeypatch.setattr(client._client.embeddings, "create", create)
        result = await client.embed_one("malformed-usage")
        assert result == [0.3]
        client.clear_embedding_cache()
    else:
        from app.llm import qwen_vl as client

        async def create(**_kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="text"))],
                usage=None,
            )

        monkeypatch.setattr(client.usage_context, "record_llm_usage", record)
        monkeypatch.setattr(client._client.chat.completions, "create", create)
        result = await client.ocr_image_jpeg(b"jpeg")
        assert result == "text"

    assert recorded == []
    assert any("usage" in record.message for record in caplog.records)


class _GraphScopeState(TypedDict):
    purpose: str


@pytest.mark.asyncio
async def test_u5_real_langgraph_async_node_reads_inherited_scope() -> None:
    from langgraph.graph import END, START, StateGraph

    from app.llm import usage_context

    async def read_scope(_state: _GraphScopeState) -> _GraphScopeState:
        current = usage_context._scope.get()
        return {"purpose": current.purpose if current is not None else "missing"}

    builder = StateGraph(_GraphScopeState)
    builder.add_node("read_scope", read_scope)
    builder.add_edge(START, "read_scope")
    builder.add_edge("read_scope", END)
    graph = builder.compile()

    async with usage_context.usage_scope("owner-1", "session-1", "run"):
        result = await graph.ainvoke({"purpose": ""})

    assert result["purpose"] == "run"


@pytest.mark.asyncio
async def test_u5_to_thread_reads_inherited_scope() -> None:
    from app.llm import usage_context

    async with usage_context.usage_scope("owner-1", "session-1", "ocr"):
        current = await asyncio.to_thread(usage_context._scope.get)

    assert current is not None
    assert (current.user_id, current.session_id, current.purpose) == (
        "owner-1",
        "session-1",
        "ocr",
    )


class _RunAttributionConnection(_RecordingConnection):
    def __init__(self, rows=None, *, fetch_error: BaseException | None = None) -> None:
        super().__init__()
        self.rows = rows or {}
        self.fetch_error = fetch_error
        self.fetch_calls: list[tuple[str, tuple]] = []

    async def fetchrow(self, sql: str, *args):
        self.fetch_calls.append((" ".join(sql.split()), args))
        if self.fetch_error is not None:
            raise self.fetch_error
        return self.rows.get(args[0])


@pytest.mark.asyncio
async def test_u5_run_wrapper_isolates_concurrent_run_attribution(
    monkeypatch,
    usage_module,
) -> None:
    from app.api.v1 import runs

    connection = _RunAttributionConnection(
        {
            "run-a": {"session_id": "session-a", "owner_user_id": "owner-a"},
            "run-b": {"session_id": "session-b", "owner_user_id": "owner-b"},
        }
    )
    _patch_pool(monkeypatch, usage_module, connection)
    _patch_pool(monkeypatch, runs, connection)
    first_entered = asyncio.Event()
    second_recorded = asyncio.Event()

    async def executor(*, run_id: str, checkpointer) -> None:
        assert checkpointer is not None
        if run_id == "run-a":
            first_entered.set()
            await second_recorded.wait()
        await usage_module.record_llm_usage("deepseek", run_id, 1, 1, 2)
        if run_id == "run-b":
            second_recorded.set()

    await asyncio.gather(
        runs._run_with_usage_scope(
            "run-a",
            executor,
            run_id="run-a",
            checkpointer=object(),
        ),
        runs._run_with_usage_scope(
            "run-b",
            executor,
            run_id="run-b",
            checkpointer=object(),
        ),
    )

    assert set(_llm_rows(connection)) == {
        ("owner-a", "session-a", "deepseek", "run-a", "run", 1, 1, 2),
        ("owner-b", "session-b", "deepseek", "run-b", "run", 1, 1, 2),
    }
    assert [args for _sql, args in connection.fetch_calls] == [
        ("run-a",),
        ("run-b",),
    ]


@pytest.mark.asyncio
async def test_u5_run_wrapper_restores_scope_when_executor_raises(
    monkeypatch,
    usage_module,
) -> None:
    from app.api.v1 import runs

    connection = _RunAttributionConnection(
        {"run-1": {"session_id": "session-1", "owner_user_id": "owner-1"}}
    )
    _patch_pool(monkeypatch, usage_module, connection)
    _patch_pool(monkeypatch, runs, connection)

    async def executor(**_kwargs) -> None:
        await usage_module.record_llm_usage("deepseek", "inside", 1, 1, 2)
        raise RuntimeError("executor failed")

    with pytest.raises(RuntimeError, match="executor failed"):
        await runs._run_with_usage_scope("run-1", executor, run_id="run-1")
    await usage_module.record_llm_usage("deepseek", "outside", 1, 1, 2)

    assert _llm_rows(connection) == [
        ("owner-1", "session-1", "deepseek", "inside", "run", 1, 1, 2),
        (None, None, "deepseek", "outside", "unscoped", 1, 1, 2),
    ]


@pytest.mark.asyncio
async def test_u5_run_lookup_failure_still_calls_real_executor_with_all_kwargs(
    monkeypatch,
) -> None:
    from app.api.v1 import runs

    connection = _RunAttributionConnection(fetch_error=RuntimeError("db down"))
    _patch_pool(monkeypatch, runs, connection)
    checkpointer = object()
    received = []

    async def executor(**kwargs) -> None:
        received.append(kwargs)

    await runs._run_with_usage_scope(
        "run-1",
        executor,
        run_id="run-1",
        checkpointer=checkpointer,
    )

    assert received == [{"run_id": "run-1", "checkpointer": checkpointer}]


@pytest.mark.asyncio
async def test_u5_missing_run_attribution_still_calls_real_executor(
    monkeypatch,
) -> None:
    from app.api.v1 import runs

    connection = _RunAttributionConnection()
    _patch_pool(monkeypatch, runs, connection)
    received = []

    async def executor(**kwargs) -> None:
        received.append(kwargs)

    await runs._run_with_usage_scope("missing", executor, run_id="missing")

    assert received == [{"run_id": "missing"}]


@pytest.mark.asyncio
async def test_u5_run_lookup_cancelled_error_propagates_without_executor(
    monkeypatch,
) -> None:
    from app.api.v1 import runs

    connection = _RunAttributionConnection(fetch_error=asyncio.CancelledError())
    _patch_pool(monkeypatch, runs, connection)
    called = False

    async def executor(**_kwargs) -> None:
        nonlocal called
        called = True

    with pytest.raises(asyncio.CancelledError):
        await runs._run_with_usage_scope("run-1", executor, run_id="run-1")
    assert called is False


@pytest.mark.asyncio
async def test_u5_background_normalize_wrapper_uses_raw_owner_and_late_binding(
    monkeypatch,
) -> None:
    from fastapi import BackgroundTasks

    from app.api.v1 import sessions
    from app.api.v1.schemas import ResumeParseRequest

    captured = []

    async def begin(**_kwargs):
        return {
            "owner_user_id": None,
            "extracted_text": "resume text",
            "suffix": ".txt",
            "content": b"resume text",
        }

    async def record_event(*_args):
        return None

    async def late_bound_normalize(**kwargs):
        current = sessions.usage_context._scope.get()
        captured.append((current, kwargs))

    monkeypatch.setattr(sessions, "begin_resume_parse", begin)
    monkeypatch.setattr(
        sessions.usage_context,
        "record_product_event",
        record_event,
    )
    background_tasks = BackgroundTasks()
    await sessions.parse_resume(
        "session-anonymous",
        ResumeParseRequest(generation=2),
        background_tasks,
    )
    monkeypatch.setattr(sessions, "_normalize_resume", late_bound_normalize)

    assert background_tasks.tasks[0].func is sessions._normalize_resume_with_scope
    await background_tasks()

    current, kwargs = captured[0]
    assert (current.user_id, current.session_id, current.purpose) == (
        None,
        "session-anonymous",
        "normalize",
    )
    assert kwargs["session_id"] == "session-anonymous"
    assert kwargs["expected_generation"] == 2


@pytest.mark.asyncio
async def test_u5_classic_executor_is_also_scheduled_through_wrapper(
    monkeypatch,
) -> None:
    from fastapi import BackgroundTasks

    from app.api.v1 import runs
    from app.api.v1.schemas import ExecuteRunRequest
    from app.domain.run import MatchRun, RunStatus

    now = datetime.now(UTC)
    queued = MatchRun(
        run_id="run-classic",
        session_id="session-1",
        status=RunStatus.QUEUED,
        plan_version=1,
        approved_plan={},
        created_at=now,
        updated_at=now,
    )

    async def queue(**_kwargs):
        return queued

    async def classic_executor(*, run_id: str):
        del run_id

    async def record_event(*_args):
        return None

    monkeypatch.setattr(runs, "queue_run", queue)
    monkeypatch.setattr(runs, "run_persisted_agentic_match_run", classic_executor)
    monkeypatch.setattr(runs.settings, "langgraph_orchestrator_enabled", False)
    monkeypatch.setattr(runs.usage_context, "record_product_event", record_event)
    background_tasks = BackgroundTasks()

    await runs.execute_run(
        "run-classic",
        ExecuteRunRequest(plan_version=1, plan_hash="a" * 64),
        background_tasks,
        SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())),
    )

    task = background_tasks.tasks[0]
    assert task.func is runs._run_with_usage_scope
    assert task.args == ("run-classic", classic_executor)
    assert task.kwargs == {"run_id": "run-classic"}


@pytest.mark.asyncio
async def test_u5_normalize_image_branch_nests_ocr_purpose(monkeypatch) -> None:
    from app.api.v1 import sessions
    from app.state.schema import ResumeState

    purposes = []

    async def no_progress(**_kwargs):
        return None

    async def ocr(_jpeg, *, on_attempt=None):
        if on_attempt is not None:
            on_attempt()
        current = sessions.usage_context._scope.get()
        purposes.append(current.purpose)
        return "Python data analyst experience"

    async def normalize(_raw_text, _spans):
        return ResumeState(normalized_base_resume="normalized")

    async def no_save(**_kwargs):
        return None

    async def no_cleanup(**_kwargs):
        return None

    monkeypatch.setattr(sessions.settings, "resume_ocr_enabled", True)
    monkeypatch.setattr(sessions, "record_intake_progress", no_progress)
    monkeypatch.setattr(sessions, "prepare_image_jpeg", lambda *_args: b"jpeg")
    monkeypatch.setattr(sessions, "ocr_image_jpeg", ocr)
    monkeypatch.setattr(sessions, "normalize_resume_text", normalize)
    monkeypatch.setattr(sessions, "save_normalized_resume", no_save)
    monkeypatch.setattr(sessions, "clear_resume_upload_content", no_cleanup)

    await sessions._normalize_resume_with_scope(
        "owner-1",
        session_id="session-1",
        user_id="owner-1",
        raw_text="",
        suffix=".png",
        content=b"png",
        expected_generation=1,
    )

    assert purposes == ["ocr"]


@pytest.mark.asyncio
async def test_u5_consult_scope_nests_coach_purpose(monkeypatch) -> None:
    from app.agents.consult_coach import CoachAttemptOutcome
    from app.agents.consult_engine import ConsultTurn, profile_draft
    from app.api.v1 import sessions
    from app.api.v1.schemas import ConsultRequest
    from app.db.state_store import ConsultContext, MutationOutcome
    from app.state.schema import CareerState, SharedState

    database_state = SharedState(
        session_id="session-1",
        user_id="owner-1",
        career_state=CareerState(current_goal=["Data analyst"]),
    )
    purposes = []

    async def load_context(_session_id):
        return ConsultContext(
            state=database_state.model_copy(deep=True),
            status="intent_consulting",
            resume_version=0,
            confirmed_resume_version=None,
            resume_upload_generation=0,
        )

    async def advisor(working, **_kwargs):
        purposes.append(sessions.usage_context._scope.get().purpose)
        working.career_state.consult_rounds_used = 1
        working.career_state.consult_transcript.append(
            {
                "round": 1,
                "user_message": "continue",
                "assistant_reply": "Got it.",
                "next_question": "What matters next?",
                "phase": "deepen",
            }
        )
        return ConsultTurn(
            assistant_reply="Got it.",
            next_question="What matters next?",
            phase="deepen",
            completeness=0.2,
            can_finalize=False,
            round=1,
            profile_draft=profile_draft(working.career_state),
        )

    async def mutate(*, mutator, **_kwargs):
        nonlocal database_state
        result = mutator(database_state, 0, 0)
        if isinstance(result, MutationOutcome):
            result = result.result
        database_state = result.model_copy(deep=True)
        return database_state.model_copy(deep=True)

    async def coach(*_args, **_kwargs):
        purposes.append(sessions.usage_context._scope.get().purpose)
        return CoachAttemptOutcome(status="unavailable", error_code="service")

    async def record_event(*_args):
        return None

    monkeypatch.setattr(sessions.settings, "consult_coach_enabled", True)
    monkeypatch.setattr(sessions.settings, "resume_clarify_enabled", False)
    monkeypatch.setattr(sessions, "load_consult_context", load_context)
    monkeypatch.setattr(sessions, "run_consult_round", advisor)
    monkeypatch.setattr(sessions, "mutate_state_atomically", mutate)
    monkeypatch.setattr(sessions, "run_consult_coach", coach)
    monkeypatch.setattr(
        sessions.usage_context,
        "record_product_event",
        record_event,
    )

    response = await sessions.continue_consultation(
        "session-1",
        ConsultRequest(mode="targeted", message="continue", expected_round=0),
        None,
    )

    assert response.round == 1
    assert purposes == ["consult", "coach"]


@pytest.mark.asyncio
async def test_u5_case_embed_applies_only_to_case_write_side(monkeypatch) -> None:
    from app.llm import usage_context
    from app.memory import case_base

    purposes = []

    async def embed(_text):
        purposes.append(usage_context._scope.get().purpose)
        return [0.0] * case_base.settings.embed_dim

    class Connection(_RecordingConnection):
        async def fetch(self, *_args):
            return []

    connection = Connection()
    _patch_pool(monkeypatch, case_base, connection)
    monkeypatch.setattr(case_base, "embed_one", embed)
    case = case_base.CareerCase(
        case_id="case-usage",
        background_type="business_undergraduate",
        target_role="Data Analyst",
        successful_resume_features=["SQL project"],
        missing_skills_before=["advanced SQL"],
        application_outcome="interview",
        recommended_bridge_roles=["Business Analyst Intern"],
    )

    async with usage_context.usage_scope("owner-1", "session-1", "run"):
        await case_base.upsert_career_case(case)
        await case_base.search_similar_cases("data analyst")

    assert purposes == ["case_embed", "run"]


@pytest.mark.asyncio
async def test_u8_login_event_is_written_only_for_active_verified_user(
    monkeypatch,
) -> None:
    from fastapi import HTTPException, Response

    from app.api.auth import routes
    from app.api.v1.schemas import OtpVerifyRequest

    events = []
    user = SimpleNamespace(
        user_id="owner-1",
        display_name=None,
        avatar_url=None,
        status="active",
        is_admin=False,
        created_at=datetime.now(UTC),
        last_login_at=datetime.now(UTC),
    )

    async def verified(**_kwargs):
        return "person@example.com"

    async def login(**_kwargs):
        return user

    async def record(*args):
        events.append(args)

    monkeypatch.setattr(routes, "verify_otp", verified)
    monkeypatch.setattr(routes, "login_or_register", login)
    # 桩签名随 J-2 强制 idp 签发链路（M2 白名单冲突，协调者批准落行）
    monkeypatch.setattr(
        routes, "issue_session_token", lambda _user, *, idp=None: "token"
    )
    monkeypatch.setattr(routes.usage_context, "record_product_event", record)
    payload = OtpVerifyRequest(
        channel="email",
        target="person@example.com",
        code="123456",
    )

    result = await routes.verify_login_otp(payload, Response())
    assert result.user_id == "owner-1"

    user.status = "banned"
    with pytest.raises(HTTPException) as excinfo:
        await routes.verify_login_otp(payload, Response())
    assert excinfo.value.status_code == 401
    assert events == [("login", "owner-1")]


@pytest.mark.asyncio
async def test_u8_session_created_event_follows_successful_quota_transaction(
    monkeypatch,
) -> None:
    from fastapi import HTTPException

    from app.api.v1 import sessions

    events = []
    accepted = True

    async def create_owned(*_args, **_kwargs):
        return accepted

    async def record(*args):
        events.append(args)

    user = SimpleNamespace(user_id="owner-1")
    monkeypatch.setattr(sessions, "create_owned_session_with_quota", create_owned)
    monkeypatch.setattr(sessions.usage_context, "record_product_event", record)

    response = await sessions.create_session(user, None)
    assert response.status == "awaiting_resume"

    accepted = False
    with pytest.raises(HTTPException) as excinfo:
        await sessions.create_session(user, None)
    assert excinfo.value.status_code == 402
    assert events == [("session_created", "owner-1")]


@pytest.mark.asyncio
async def test_u8_consult_turn_event_follows_successful_cas_only(
    monkeypatch,
) -> None:
    from fastapi import HTTPException

    from app.agents.consult_engine import ConsultTurn, profile_draft
    from app.api.v1 import sessions
    from app.api.v1.schemas import ConsultRequest
    from app.db.state_store import ConsultContext, MutationOutcome
    from app.state.schema import CareerState, SharedState

    events = []
    database_state = SharedState(
        session_id="session-1",
        user_id="owner-1",
        career_state=CareerState(current_goal=["Data analyst"]),
    )

    async def load_context(_session_id):
        return ConsultContext(
            state=database_state.model_copy(deep=True),
            status="intent_consulting",
            resume_version=0,
            confirmed_resume_version=None,
            resume_upload_generation=0,
        )

    async def advisor(working, **_kwargs):
        working.career_state.consult_rounds_used = 1
        working.career_state.consult_transcript.append(
            {
                "round": 1,
                "user_message": "continue",
                "assistant_reply": "Got it.",
                "next_question": "What matters next?",
                "phase": "deepen",
            }
        )
        return ConsultTurn(
            assistant_reply="Got it.",
            next_question="What matters next?",
            phase="deepen",
            completeness=0.2,
            can_finalize=False,
            round=1,
            profile_draft=profile_draft(working.career_state),
        )

    async def mutate(*, mutator, **_kwargs):
        nonlocal database_state
        result = mutator(database_state, 0, 0)
        if isinstance(result, MutationOutcome):
            result = result.result
        database_state = result.model_copy(deep=True)
        return database_state.model_copy(deep=True)

    async def record(*args):
        events.append(args)

    async def no_profile(_user_id):
        return None

    monkeypatch.setattr(sessions.settings, "consult_coach_enabled", False)
    monkeypatch.setattr(sessions.settings, "resume_clarify_enabled", False)
    monkeypatch.setattr(sessions, "load_consult_context", load_context)
    monkeypatch.setattr(sessions, "run_consult_round", advisor)
    monkeypatch.setattr(sessions, "mutate_state_atomically", mutate)
    monkeypatch.setattr(sessions, "load_profile", no_profile)
    monkeypatch.setattr(sessions.usage_context, "record_product_event", record)
    user = SimpleNamespace(user_id="owner-1")
    request = ConsultRequest(mode="targeted", message="continue", expected_round=0)

    response = await sessions.continue_consultation("session-1", request, user)
    assert response.round == 1

    with pytest.raises(HTTPException) as excinfo:
        await sessions.continue_consultation("session-1", request, user)
    assert excinfo.value.status_code == 409
    assert events == [("consult_turn", "owner-1")]


@pytest.mark.asyncio
async def test_u8_resume_parse_event_follows_successful_begin_cas_only(
    monkeypatch,
) -> None:
    from fastapi import BackgroundTasks, HTTPException

    from app.api.v1 import sessions
    from app.api.v1.schemas import ResumeParseRequest

    events = []
    owner_user_id = uuid.UUID("11111111-1111-1111-1111-111111111111")

    async def begin(**_kwargs):
        return {
            "owner_user_id": owner_user_id,
            "extracted_text": "resume",
            "suffix": ".txt",
            "content": b"resume",
        }

    async def record(*args):
        events.append(args)

    monkeypatch.setattr(sessions.settings, "resume_ocr_enabled", True)
    monkeypatch.setattr(sessions, "begin_resume_parse", begin)
    monkeypatch.setattr(sessions.usage_context, "record_product_event", record)

    await sessions.parse_resume(
        "session-1",
        ResumeParseRequest(generation=1),
        BackgroundTasks(),
    )

    async def missing(**_kwargs):
        raise KeyError("missing")

    monkeypatch.setattr(sessions, "begin_resume_parse", missing)
    with pytest.raises(HTTPException) as excinfo:
        await sessions.parse_resume(
            "session-1",
            ResumeParseRequest(generation=1),
            BackgroundTasks(),
        )
    assert excinfo.value.status_code == 404
    assert events == [("resume_parse", str(owner_user_id))]


@pytest.mark.asyncio
async def test_u8_run_started_event_follows_successful_queue_cas_only(
    monkeypatch,
) -> None:
    from fastapi import BackgroundTasks, HTTPException

    from app.api.v1 import runs
    from app.api.v1.schemas import ExecuteRunRequest
    from app.db.run_store import RunConflict
    from app.domain.run import MatchRun, RunStatus

    events = []
    now = datetime.now(UTC)
    queued = MatchRun(
        run_id="run-1",
        session_id="session-1",
        status=RunStatus.QUEUED,
        plan_version=1,
        approved_plan={},
        created_at=now,
        updated_at=now,
    )

    async def queue(**_kwargs):
        return queued

    async def record(*args):
        events.append(args)

    monkeypatch.setattr(runs, "queue_run", queue)
    monkeypatch.setattr(runs.settings, "langgraph_orchestrator_enabled", False)
    monkeypatch.setattr(runs.usage_context, "record_product_event", record)
    request = ExecuteRunRequest(plan_version=1, plan_hash="a" * 64)
    http_request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    user = SimpleNamespace(user_id="owner-1")

    response = await runs.execute_run(
        "run-1",
        request,
        BackgroundTasks(),
        http_request,
        user=user,
    )
    assert response.status == "queued"

    async def conflict(**_kwargs):
        raise RunConflict("run is already queued")

    monkeypatch.setattr(runs, "queue_run", conflict)
    with pytest.raises(HTTPException) as excinfo:
        await runs.execute_run(
            "run-1",
            request,
            BackgroundTasks(),
            http_request,
            user=user,
        )
    assert excinfo.value.status_code == 409
    assert events == [("run_started", "owner-1")]
