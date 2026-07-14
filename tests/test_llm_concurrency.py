import asyncio
import os

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")
os.environ.setdefault("QWEN_API_KEY", "sk-test")


@pytest.mark.asyncio
async def test_deepseek_chat_respects_global_semaphore(monkeypatch):
    from app.llm import deepseek

    active = 0
    max_active = 0

    class FakeMessage:
        content = "ok"

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    class FakeCompletions:
        async def create(self, **kwargs):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            try:
                await asyncio.sleep(0.03)
            finally:
                active -= 1
            return FakeResponse()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr(deepseek, "_client", FakeClient())
    monkeypatch.setattr(deepseek, "_sem", asyncio.Semaphore(2))

    await asyncio.gather(
        *[
            deepseek.chat("system", f"user-{index}")
            for index in range(5)
        ]
    )

    assert max_active == 2


@pytest.mark.asyncio
async def test_qwen_embedding_respects_global_semaphore(monkeypatch):
    from app.llm import qwen_embed

    active = 0
    max_active = 0

    class FakeDatum:
        def __init__(self, index: int):
            self.embedding = [float(index), 1.0]

    class FakeResponse:
        def __init__(self, count: int):
            self.data = [FakeDatum(index) for index in range(count)]

    class FakeEmbeddings:
        async def create(self, **kwargs):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            try:
                await asyncio.sleep(0.03)
            finally:
                active -= 1
            return FakeResponse(len(kwargs["input"]))

    class FakeClient:
        embeddings = FakeEmbeddings()

    monkeypatch.setattr(qwen_embed, "_client", FakeClient())
    monkeypatch.setattr(qwen_embed, "_sem", asyncio.Semaphore(3))

    results = await asyncio.gather(
        *[qwen_embed.embed_texts([f"resume-{index}"]) for index in range(9)]
    )

    assert max_active == 3
    assert results == [[[0.0, 1.0]]] * 9
