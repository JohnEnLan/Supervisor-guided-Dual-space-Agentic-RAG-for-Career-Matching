"""DashScope text reranker with strict validation and bounded retries."""

from __future__ import annotations

import asyncio
import logging
import math
from numbers import Real
from urllib.parse import urlsplit

import httpx

from app.config import settings
from app.llm import usage_context


logger = logging.getLogger(__name__)

_QUERY_TOKEN_LIMIT = 3_800
_DOCUMENT_TOKEN_LIMIT = 3_800
_REQUEST_TOKEN_LIMIT = 27_000
_RETRY_DELAY_SECONDS = 0.5
_MAX_ATTEMPTS = 2

_sem = asyncio.Semaphore(settings.rerank_max_concurrency)


class RerankMisconfigured(RuntimeError):
    """The reranker cannot be called until configuration is corrected."""


class RerankUnavailable(RuntimeError):
    """The reranker failed at runtime and the caller may use its baseline."""


def est_tokens(text: str) -> int:
    """Conservatively estimate tokens for mixed ASCII and non-ASCII text."""
    ascii_chars = sum(character.isascii() for character in text)
    non_ascii_chars = len(text) - ascii_chars
    return non_ascii_chars + math.ceil(ascii_chars / 3)


def _require_rerank_endpoint() -> str:
    endpoint = settings.rerank_endpoint
    if not endpoint or "{WorkspaceId}" in endpoint:
        raise RerankMisconfigured("rerank_endpoint_invalid")
    try:
        parsed = urlsplit(endpoint)
    except ValueError as exc:
        raise RerankMisconfigured("rerank_endpoint_invalid") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RerankMisconfigured("rerank_endpoint_invalid")
    return endpoint


def _validate_input_budget(query: str, documents: list[str]) -> None:
    if not documents:
        raise RerankUnavailable("rerank_documents_empty")
    query_tokens = est_tokens(query)
    document_tokens = [est_tokens(document) for document in documents]
    if query_tokens > _QUERY_TOKEN_LIMIT:
        raise RerankUnavailable("rerank_query_budget_exceeded")
    if any(tokens > _DOCUMENT_TOKEN_LIMIT for tokens in document_tokens):
        raise RerankUnavailable("rerank_document_budget_exceeded")
    if query_tokens * len(documents) + sum(document_tokens) > _REQUEST_TOKEN_LIMIT:
        raise RerankUnavailable("rerank_request_budget_exceeded")


def _aligned_scores(response: httpx.Response, document_count: int) -> list[float]:
    try:
        payload = response.json()
        results = payload["output"]["results"]
    except (KeyError, TypeError, ValueError) as exc:
        raise RerankUnavailable("rerank_response_contract_invalid") from exc
    if not isinstance(results, list) or len(results) != document_count:
        raise RerankUnavailable("rerank_response_contract_invalid")

    scores_by_index: dict[int, float] = {}
    for result in results:
        if not isinstance(result, dict):
            raise RerankUnavailable("rerank_response_contract_invalid")
        index = result.get("index")
        score = result.get("relevance_score")
        if isinstance(index, bool) or not isinstance(index, int):
            raise RerankUnavailable("rerank_response_index_invalid")
        if isinstance(score, bool) or not isinstance(score, Real):
            raise RerankUnavailable("rerank_response_score_invalid")
        numeric_score = float(score)
        if not math.isfinite(numeric_score) or not 0 <= numeric_score <= 1:
            raise RerankUnavailable("rerank_response_score_invalid")
        if index in scores_by_index:
            raise RerankUnavailable("rerank_response_index_invalid")
        scores_by_index[index] = numeric_score

    if set(scores_by_index) != set(range(document_count)):
        raise RerankUnavailable("rerank_response_index_invalid")
    return [scores_by_index[index] for index in range(document_count)]


async def rerank_documents(query: str, documents: list[str]) -> list[float]:
    """Return one validated score per document, aligned to input order."""
    endpoint = _require_rerank_endpoint()
    _validate_input_budget(query, documents)
    request_body = {
        "model": settings.rerank_model,
        "input": {"query": query, "documents": documents},
        "parameters": {
            "return_documents": False,
            "top_n": len(documents),
        },
    }
    headers = {
        "Authorization": f"Bearer {settings.qwen_api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(
        timeout=settings.rerank_timeout_seconds,
    ) as client:
        for attempt in range(_MAX_ATTEMPTS):
            retry_reason: str | None = None
            try:
                async with _sem:
                    response = await client.post(
                        endpoint,
                        json=request_body,
                        headers=headers,
                    )
            except asyncio.CancelledError:
                raise
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                retry_reason = type(exc).__name__
                if attempt == _MAX_ATTEMPTS - 1:
                    logger.warning("rerank_unavailable reason=%s", retry_reason)
                    raise RerankUnavailable("rerank_transport_unavailable") from exc
            else:
                status_code = response.status_code
                if status_code in {401, 403}:
                    raise RerankMisconfigured(
                        f"rerank_http_{status_code}"
                    )
                if status_code == 429 or status_code >= 500:
                    retry_reason = f"http_{status_code}"
                    if attempt == _MAX_ATTEMPTS - 1:
                        logger.warning(
                            "rerank_unavailable reason=%s",
                            retry_reason,
                        )
                        raise RerankUnavailable(retry_reason)
                elif 400 <= status_code < 500:
                    raise RerankUnavailable(f"rerank_http_{status_code}")
                elif status_code >= 300:
                    raise RerankUnavailable(f"rerank_http_{status_code}")
                else:
                    scores = _aligned_scores(response, len(documents))
                    try:
                        usage = response.json()["usage"]
                        total_tokens = usage["total_tokens"]
                        if (
                            isinstance(total_tokens, bool)
                            or not isinstance(total_tokens, int)
                            or total_tokens < 0
                        ):
                            raise ValueError("invalid token usage")
                        await usage_context.record_llm_usage(
                            "dashscope",
                            settings.rerank_model,
                            None,
                            None,
                            total_tokens,
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logger.warning(
                            "reranker usage recording failed",
                            exc_info=True,
                        )
                    return scores

            if retry_reason is not None:
                logger.warning("rerank_retry reason=%s", retry_reason)
                await asyncio.sleep(_RETRY_DELAY_SECONDS)

    raise RerankUnavailable("rerank_attempts_exhausted")
