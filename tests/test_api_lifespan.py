import pytest


@pytest.mark.asyncio
async def test_lifespan_closes_pool_when_application_context_raises(monkeypatch):
    from app.api import main

    calls: list[str] = []

    async def fake_get_pool():
        calls.append("open")

    async def fake_close_pool():
        calls.append("close")

    async def fake_recover_stale_runs(*, stale_after_seconds):
        assert stale_after_seconds >= 1
        calls.append("recover")
        return 2

    monkeypatch.setattr(main, "get_pool", fake_get_pool)
    monkeypatch.setattr(main, "close_pool", fake_close_pool)
    monkeypatch.setattr(
        main,
        "recover_stale_runs",
        fake_recover_stale_runs,
        raising=False,
    )

    with pytest.raises(RuntimeError, match="application failure"):
        async with main.lifespan(main.app):
            raise RuntimeError("application failure")

    assert calls == ["open", "recover", "close"]
