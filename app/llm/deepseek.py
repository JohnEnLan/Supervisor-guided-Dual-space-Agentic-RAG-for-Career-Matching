"""DeepSeek 异步客户端（OpenAI 兼容）+ Semaphore 限流。

所有 LLM 调用都走这里，统一限流，防止触发速率限制。
Agent 只调用 chat()，不直接 new 客户端。
"""
import asyncio
from openai import AsyncOpenAI
from app.config import settings
from app.llm.context_budget import fit_user_prompt_to_budget

_client = AsyncOpenAI(
    api_key=settings.deepseek_api_key,
    base_url=settings.deepseek_base_url,
)

# 全局并发闸门：同时最多 N 个 LLM 调用
_sem = asyncio.Semaphore(settings.llm_max_concurrency)


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
    return resp.choices[0].message.content
