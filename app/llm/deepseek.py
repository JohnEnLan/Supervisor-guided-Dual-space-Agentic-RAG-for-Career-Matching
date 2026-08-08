"""DeepSeek 异步客户端（OpenAI 兼容）+ Semaphore 限流。

所有 LLM 调用都走这里，统一限流，防止触发速率限制。
Agent 只调用 chat()，不直接 new 客户端。
"""
import asyncio
import json
import logging
from typing import Any

from openai import AsyncOpenAI

from app.config import settings
from app.llm.context_budget import fit_user_prompt_to_budget
from app.llm import usage_context


logger = logging.getLogger(__name__)

_client = AsyncOpenAI(
    api_key=settings.deepseek_api_key,
    base_url=settings.deepseek_base_url,
)

# 全局并发闸门：同时最多 N 个 LLM 调用
_sem = asyncio.Semaphore(settings.llm_max_concurrency)


def extract_json_response(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return json.loads(stripped)


async def chat(
    system: str,
    user: str,
    *,
    pro: bool = False,
    temperature: float = 0.2,
    json_mode: bool = False,
) -> str:
    """单轮调用。pro=True 用推理模型（贵，给 Supervisor 核查/复杂规划用）。"""
    model = settings.deepseek_model_pro if pro else settings.deepseek_model_fast
    bounded_user = fit_user_prompt_to_budget(
        user,
        max_chars=settings.llm_user_prompt_max_chars,
    )
    kwargs = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": bounded_user},
        ],
        "temperature": temperature,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    async with _sem:
        resp = await _client.chat.completions.create(**kwargs)
    content = resp.choices[0].message.content
    try:
        usage = getattr(resp, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens")
        completion_tokens = getattr(usage, "completion_tokens")
        total_tokens = getattr(usage, "total_tokens")
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in (prompt_tokens, completion_tokens, total_tokens)
        ):
            raise ValueError("invalid token usage")
        await usage_context.record_llm_usage(
            "deepseek",
            model,
            prompt_tokens,
            completion_tokens,
            total_tokens,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("deepseek usage recording failed", exc_info=True)
    return content
