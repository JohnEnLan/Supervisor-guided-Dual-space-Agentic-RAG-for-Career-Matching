from __future__ import annotations

import asyncio
from collections.abc import Iterable
import json
import math

import httpx
import pytest


def _success_response(scores: Iterable[tuple[int, float]]) -> httpx.Response:
    payload = {
        "output": {
            "results": [
                {"index": index, "relevance_score": score}
                for index, score in scores
            ]
        }
    }
    return httpx.Response(
        200,
        request=httpx.Request("POST", "https://example.test/rerank"),
        content=json.dumps(payload, allow_nan=True).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


class _FakeAsyncClient:
    responses: list[object] = []
    calls: list[dict] = []
    timeouts: list[float] = []

    def __init__(self, *, timeout: float) -> None:
        self.timeouts.append(timeout)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args) -> None:
        return None

    async def post(self, endpoint: str, **kwargs):
        self.calls.append({"endpoint": endpoint, **kwargs})
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


@pytest.fixture
def reranker(monkeypatch):
    from app.llm import reranker as module

    _FakeAsyncClient.responses = []
    _FakeAsyncClient.calls = []
    _FakeAsyncClient.timeouts = []
    monkeypatch.setattr(module.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(module.settings, "qwen_api_key", "sk-rerank-test")
    monkeypatch.setattr(module.settings, "rerank_model", "gte-rerank-v2")
    monkeypatch.setattr(
        module.settings,
        "rerank_endpoint",
        "https://example.test/rerank",
    )
    monkeypatch.setattr(module.settings, "rerank_timeout_seconds", 5)
    monkeypatch.setattr(module, "_sem", asyncio.Semaphore(4))
    return module


def test_est_tokens_counts_all_non_ascii_characters_conservatively(reranker) -> None:
    assert reranker.est_tokens("abcdef") == 2
    assert reranker.est_tokens("中文") == 2
    assert reranker.est_tokens("مرحبا") == 5
    assert reranker.est_tokens("Привет") == 6
    assert reranker.est_tokens("🙂") == 1
    assert reranker.est_tokens("abc中🙂") == 3


@pytest.mark.parametrize(
    "endpoint",
    [None, "", "not-a-url", "ftp://example.test/rerank", "https:///missing", "https://host/{WorkspaceId}/rerank"],
)
def test_require_rerank_endpoint_rejects_missing_or_invalid_values(
    reranker,
    monkeypatch,
    endpoint,
) -> None:
    monkeypatch.setattr(reranker.settings, "rerank_endpoint", endpoint)

    with pytest.raises(reranker.RerankMisconfigured):
        reranker._require_rerank_endpoint()


def test_require_rerank_endpoint_returns_valid_http_url(reranker) -> None:
    assert (
        reranker._require_rerank_endpoint()
        == "https://example.test/rerank"
    )


@pytest.mark.asyncio
async def test_rerank_rebuilds_input_order_from_provider_indices(reranker) -> None:
    _FakeAsyncClient.responses = [
        _success_response([(2, 0.3), (0, 0.9), (1, 0.5)])
    ]

    scores = await reranker.rerank_documents("query", ["a", "b", "c"])

    assert scores == [0.9, 0.5, 0.3]
    assert len(_FakeAsyncClient.calls) == 1
    assert _FakeAsyncClient.calls[0]["json"] == {
        "model": "gte-rerank-v2",
        "input": {"query": "query", "documents": ["a", "b", "c"]},
        "parameters": {"return_documents": False, "top_n": 3},
    }
    assert _FakeAsyncClient.calls[0]["headers"]["Authorization"] == (
        "Bearer sk-rerank-test"
    )
    assert _FakeAsyncClient.timeouts == [5]


@pytest.mark.parametrize(
    "scores",
    [
        [(0, 0.8), (0, 0.7)],
        [(0, 0.8)],
        [(0, 0.8), (2, 0.7)],
        [(0, -0.1), (1, 0.7)],
        [(0, 1.1), (1, 0.7)],
        [(0, math.nan), (1, 0.7)],
        [(0, math.inf), (1, 0.7)],
    ],
)
@pytest.mark.asyncio
async def test_rerank_rejects_invalid_indices_and_scores(reranker, scores) -> None:
    _FakeAsyncClient.responses = [_success_response(scores)]

    with pytest.raises(reranker.RerankUnavailable):
        await reranker.rerank_documents("query", ["a", "b"])


@pytest.mark.asyncio
async def test_rerank_rejects_malformed_response_contract(reranker) -> None:
    _FakeAsyncClient.responses = [
        httpx.Response(
            200,
            request=httpx.Request("POST", "https://example.test/rerank"),
            json={"output": {}},
        )
    ]

    with pytest.raises(reranker.RerankUnavailable):
        await reranker.rerank_documents("query", ["a"])


@pytest.mark.parametrize("status_code", [429, 500, 503])
@pytest.mark.asyncio
async def test_transient_http_errors_retry_once_outside_semaphore(
    reranker,
    monkeypatch,
    status_code,
) -> None:
    _FakeAsyncClient.responses = [
        httpx.Response(status_code),
        _success_response([(0, 0.8), (1, 0.2)]),
    ]
    sleeps: list[tuple[float, bool]] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append((delay, reranker._sem.locked()))

    monkeypatch.setattr(reranker.asyncio, "sleep", fake_sleep)

    assert await reranker.rerank_documents("query", ["a", "b"]) == [0.8, 0.2]
    assert len(_FakeAsyncClient.calls) == 2
    assert sleeps == [(0.5, False)]


@pytest.mark.parametrize(
    "error",
    [
        httpx.TimeoutException("timeout"),
        httpx.ConnectError("connect failed"),
    ],
)
@pytest.mark.asyncio
async def test_transient_transport_errors_retry_only_once(
    reranker,
    monkeypatch,
    error,
) -> None:
    _FakeAsyncClient.responses = [error, error]

    async def no_wait(_delay: float) -> None:
        return None

    monkeypatch.setattr(reranker.asyncio, "sleep", no_wait)

    with pytest.raises(reranker.RerankUnavailable):
        await reranker.rerank_documents("query", ["a"])
    assert len(_FakeAsyncClient.calls) == 2


@pytest.mark.parametrize("status_code", [401, 403])
@pytest.mark.asyncio
async def test_authentication_errors_are_misconfigured_without_retry(
    reranker,
    status_code,
) -> None:
    _FakeAsyncClient.responses = [httpx.Response(status_code)]

    with pytest.raises(reranker.RerankMisconfigured):
        await reranker.rerank_documents("query", ["a"])
    assert len(_FakeAsyncClient.calls) == 1


@pytest.mark.parametrize("status_code", [400, 404, 422])
@pytest.mark.asyncio
async def test_other_client_errors_are_unavailable_without_retry(
    reranker,
    status_code,
) -> None:
    _FakeAsyncClient.responses = [httpx.Response(status_code)]

    with pytest.raises(reranker.RerankUnavailable):
        await reranker.rerank_documents("query", ["a"])
    assert len(_FakeAsyncClient.calls) == 1


@pytest.mark.asyncio
async def test_cancelled_error_propagates_without_retry(reranker) -> None:
    _FakeAsyncClient.responses = [asyncio.CancelledError()]

    with pytest.raises(asyncio.CancelledError):
        await reranker.rerank_documents("query", ["a"])
    assert len(_FakeAsyncClient.calls) == 1


@pytest.mark.parametrize(
    ("query", "documents"),
    [
        ("中" * 3801, ["a"]),
        ("query", ["中" * 3801]),
        ("中" * 3000, ["文" * 12001, "a" * 36000]),
    ],
)
@pytest.mark.asyncio
async def test_client_rejects_inputs_outside_any_token_budget_layer(
    reranker,
    query,
    documents,
) -> None:
    with pytest.raises(reranker.RerankUnavailable):
        await reranker.rerank_documents(query, documents)
    assert _FakeAsyncClient.calls == []


@pytest.mark.asyncio
async def test_response_contract_remains_equal_length(reranker) -> None:
    _FakeAsyncClient.responses = [_success_response([(0, 0.5)])]
    assert len(await reranker.rerank_documents("query", ["a"])) == 1


@pytest.mark.asyncio
async def test_module_semaphore_caps_concurrent_http_attempts(
    reranker,
    monkeypatch,
) -> None:
    active = 0
    peak = 0

    class ConcurrentClient(_FakeAsyncClient):
        async def post(self, endpoint: str, **kwargs):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            count = len(kwargs["json"]["input"]["documents"])
            return _success_response((index, 0.5) for index in range(count))

    monkeypatch.setattr(reranker.httpx, "AsyncClient", ConcurrentClient)
    monkeypatch.setattr(reranker, "_sem", asyncio.Semaphore(2))

    await asyncio.gather(
        *(reranker.rerank_documents("query", [str(index)]) for index in range(6))
    )

    assert peak == 2
