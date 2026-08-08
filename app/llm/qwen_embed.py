"""Qwen Embedding 异步客户端（DashScope，OpenAI 兼容接口）。

- 维度必须等于 settings.embed_dim 和 schema.sql 的 vector(N)。
- 加 Semaphore 限流。
- 内容哈希 LRU 缓存：同一段文本（同模型）只调一次 API。
  运行时热点是"同一份简历在多次检索/重跑里反复编码"，内容不变即命中。
"""
import asyncio
import hashlib
import logging
from collections import OrderedDict

from openai import AsyncOpenAI

from app.config import settings
from app.llm import usage_context


logger = logging.getLogger(__name__)

# DashScope 提供 OpenAI 兼容 endpoint
_client = AsyncOpenAI(
    api_key=settings.qwen_api_key,
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)

_sem = asyncio.Semaphore(settings.embed_max_concurrency)

_CACHE_MAX_ENTRIES = 4096
_cache: OrderedDict[str, list[float]] = OrderedDict()


def _cache_key(text: str) -> str:
    payload = f"{settings.qwen_embed_model}\x00{text}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_get(key: str) -> list[float] | None:
    vector = _cache.get(key)
    if vector is not None:
        _cache.move_to_end(key)
    return vector


def _cache_put(key: str, vector: list[float]) -> None:
    _cache[key] = vector
    _cache.move_to_end(key)
    while len(_cache) > _CACHE_MAX_ENTRIES:
        _cache.popitem(last=False)


def clear_embedding_cache() -> None:
    """测试与语料切换后手动清空。"""
    _cache.clear()


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """批量编码。返回与输入等长的向量列表；缓存命中的条目不再调 API。"""
    keys = [_cache_key(text) for text in texts]
    results: list[list[float] | None] = [_cache_get(key) for key in keys]
    missing = [index for index, vector in enumerate(results) if vector is None]
    if missing:
        async with _sem:
            resp = await _client.embeddings.create(
                model=settings.qwen_embed_model,
                input=[texts[index] for index in missing],
            )
        for position, index in enumerate(missing):
            vector = resp.data[position].embedding
            results[index] = vector
            _cache_put(keys[index], vector)
        try:
            usage = getattr(resp, "usage", None)
            prompt_tokens = getattr(usage, "prompt_tokens")
            total_tokens = getattr(usage, "total_tokens")
            if any(
                isinstance(value, bool) or not isinstance(value, int) or value < 0
                for value in (prompt_tokens, total_tokens)
            ):
                raise ValueError("invalid token usage")
            await usage_context.record_llm_usage(
                "dashscope",
                settings.qwen_embed_model,
                prompt_tokens,
                None,
                total_tokens,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("qwen embedding usage recording failed", exc_info=True)
    return [vector for vector in results if vector is not None]


async def embed_one(text: str) -> list[float]:
    out = await embed_texts([text])
    return out[0]
