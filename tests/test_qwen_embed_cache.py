from types import SimpleNamespace

import pytest

from app.llm import qwen_embed


@pytest.fixture(autouse=True)
def clean_cache():
    qwen_embed.clear_embedding_cache()
    yield
    qwen_embed.clear_embedding_cache()


def _install_fake_api(monkeypatch, calls: list[list[str]]):
    async def fake_create(*, model: str, input: list[str]):
        calls.append(list(input))
        return SimpleNamespace(
            data=[
                SimpleNamespace(embedding=[float(len(text)), 0.5])
                for text in input
            ]
        )

    monkeypatch.setattr(
        qwen_embed._client.embeddings, "create", fake_create
    )


@pytest.mark.asyncio
async def test_repeated_text_hits_cache_without_second_api_call(monkeypatch):
    calls: list[list[str]] = []
    _install_fake_api(monkeypatch, calls)

    first = await qwen_embed.embed_texts(["简历片段A", "简历片段B"])
    second = await qwen_embed.embed_texts(["简历片段A", "简历片段B"])

    assert first == second
    assert calls == [["简历片段A", "简历片段B"]]


@pytest.mark.asyncio
async def test_mixed_batch_only_requests_uncached_texts(monkeypatch):
    calls: list[list[str]] = []
    _install_fake_api(monkeypatch, calls)

    await qwen_embed.embed_texts(["旧文本"])
    vectors = await qwen_embed.embed_texts(["新文本一", "旧文本", "新文本二"])

    # 第二次只把两个未命中文本发给 API，且返回顺序与输入一致
    assert calls == [["旧文本"], ["新文本一", "新文本二"]]
    assert vectors[1] == [float(len("旧文本")), 0.5]
    assert len(vectors) == 3


@pytest.mark.asyncio
async def test_cache_is_bounded(monkeypatch):
    calls: list[list[str]] = []
    _install_fake_api(monkeypatch, calls)
    monkeypatch.setattr(qwen_embed, "_CACHE_MAX_ENTRIES", 2)

    await qwen_embed.embed_texts(["一", "二", "三"])

    assert len(qwen_embed._cache) == 2
