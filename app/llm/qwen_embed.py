"""Qwen Embedding 异步客户端（DashScope，OpenAI 兼容接口）。

- 维度必须等于 settings.embed_dim 和 schema.sql 的 vector(N)。
- 加 Semaphore 限流。
- embed_cache 接口预留：基于 resume_version_id + chunk_id 缓存，简历不改就不重算。
"""
import asyncio
from openai import AsyncOpenAI
from app.config import settings

# DashScope 提供 OpenAI 兼容 endpoint
_client = AsyncOpenAI(
    api_key=settings.qwen_api_key,
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)

_sem = asyncio.Semaphore(settings.embed_max_concurrency)


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """批量编码。返回与输入等长的向量列表。"""
    async with _sem:
        resp = await _client.embeddings.create(
            model=settings.qwen_embed_model,
            input=texts,
        )
    return [d.embedding for d in resp.data]


async def embed_one(text: str) -> list[float]:
    out = await embed_texts([text])
    return out[0]

# TODO(P0): 加 embedding 缓存层（key = resume_version_id + chunk_id），
#           仅当简历对应 chunk 变化时才重新调用 embed_texts。
