from __future__ import annotations

import asyncio

import pytest

from app.db import pool as pool_module


@pytest.mark.asyncio
async def test_get_pool_initializes_once_for_concurrent_first_call(monkeypatch) -> None:
    created: list[object] = []

    async def fake_create_pool(**_kwargs):
        await asyncio.sleep(0)
        candidate = object()
        created.append(candidate)
        return candidate

    monkeypatch.setattr(pool_module, "_pool", None)
    monkeypatch.setattr(pool_module.asyncpg, "create_pool", fake_create_pool)

    first, second = await asyncio.gather(
        pool_module.get_pool(),
        pool_module.get_pool(),
    )

    assert len(created) == 1
    assert first is second is created[0]
