import pytest


@pytest.mark.asyncio
async def test_lifespan_closes_pool_when_application_context_raises(monkeypatch):
    from app.api import main

    calls: list[str] = []

    async def fake_get_pool():
        calls.append("open")

    async def fake_close_pool():
        calls.append("close")

    monkeypatch.setattr(main, "get_pool", fake_get_pool)
    monkeypatch.setattr(main, "close_pool", fake_close_pool)

    with pytest.raises(RuntimeError, match="application failure"):
        async with main.lifespan(main.app):
            raise RuntimeError("application failure")

    assert calls == ["open", "close"]
