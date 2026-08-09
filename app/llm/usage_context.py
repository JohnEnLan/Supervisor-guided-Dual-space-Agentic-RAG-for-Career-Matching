from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import AsyncIterator

from app.db.pool import get_pool


logger = logging.getLogger(__name__)

_FAILURE_LIMIT = 5
_DISABLED_SECONDS = 300.0


@dataclass(frozen=True)
class _UsageScope:
    user_id: str | None
    session_id: str | None
    purpose: str


_scope: ContextVar[_UsageScope | None] = ContextVar("llm_usage_scope", default=None)
_breaker_lock = asyncio.Lock()
_consecutive_failures = 0
_disabled_until = 0.0
_probe_in_flight = False


@asynccontextmanager
async def usage_scope(
    user_id: str | None,
    session_id: str | None,
    purpose: str,
) -> AsyncIterator[None]:
    token = _scope.set(
        _UsageScope(
            user_id=user_id,
            session_id=session_id,
            purpose=purpose,
        )
    )
    try:
        yield
    finally:
        _scope.reset(token)


@asynccontextmanager
async def usage_purpose(purpose: str) -> AsyncIterator[None]:
    current = _scope.get()
    async with usage_scope(
        current.user_id if current is not None else None,
        current.session_id if current is not None else None,
        purpose,
    ):
        yield


async def record_llm_usage(
    provider: str,
    model: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    total_tokens: int,
) -> None:
    admitted, is_probe = await _admit_write()
    if not admitted:
        return
    try:
        current = _scope.get()
        user_id = current.user_id if current is not None else None
        session_id = current.session_id if current is not None else None
        purpose = current.purpose if current is not None else "unscoped"
        pool = await get_pool()
        async with pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO llm_usage (
                    user_id, session_id, provider, model, purpose,
                    prompt_tokens, completion_tokens, total_tokens
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                user_id,
                session_id,
                provider,
                model,
                purpose,
                prompt_tokens,
                completion_tokens,
                total_tokens,
            )
    except asyncio.CancelledError:
        await _finish_cancelled(is_probe=is_probe)
        raise
    except Exception:
        opened = await _finish_failure(is_probe=is_probe)
        if opened:
            logger.warning(
                "usage recorder disabled for %s seconds",
                int(_DISABLED_SECONDS),
                exc_info=True,
            )
        return
    await _finish_success()


async def record_product_event(kind: str, user_id: str | None) -> None:
    admitted, is_probe = await _admit_write()
    if not admitted:
        return
    try:
        pool = await get_pool()
        async with pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO product_events (kind, user_id)
                VALUES ($1, $2)
                """,
                kind,
                user_id,
            )
    except asyncio.CancelledError:
        await _finish_cancelled(is_probe=is_probe)
        raise
    except Exception:
        opened = await _finish_failure(is_probe=is_probe)
        if opened:
            logger.warning(
                "usage recorder disabled for %s seconds",
                int(_DISABLED_SECONDS),
                exc_info=True,
            )
        return
    await _finish_success()


async def _admit_write() -> tuple[bool, bool]:
    global _probe_in_flight

    disabled_until = _disabled_until
    if disabled_until == 0.0:
        return True, False
    if time.monotonic() < disabled_until:
        return False, False
    async with _breaker_lock:
        if _disabled_until == 0.0:
            return True, False
        if time.monotonic() < _disabled_until or _probe_in_flight:
            return False, False
        _probe_in_flight = True
        return True, True


async def _finish_success() -> None:
    global _consecutive_failures, _disabled_until, _probe_in_flight

    async with _breaker_lock:
        _consecutive_failures = 0
        _disabled_until = 0.0
        _probe_in_flight = False


async def _finish_failure(*, is_probe: bool) -> bool:
    global _consecutive_failures, _disabled_until, _probe_in_flight

    async with _breaker_lock:
        if is_probe:
            _disabled_until = time.monotonic() + _DISABLED_SECONDS
            _probe_in_flight = False
            return True
        if _disabled_until != 0.0:
            # 窗口开启前已获准的迟到失败：恢复与否只由探针裁决，
            # 不重复告警、不后移 deadline。
            return False
        _consecutive_failures += 1
        if _consecutive_failures < _FAILURE_LIMIT:
            return False
        _disabled_until = time.monotonic() + _DISABLED_SECONDS
        _probe_in_flight = False
        return True


async def _finish_cancelled(*, is_probe: bool) -> None:
    global _probe_in_flight

    if not is_probe:
        return
    async with _breaker_lock:
        _probe_in_flight = False


def reset_usage_recorder() -> None:
    global _consecutive_failures, _disabled_until, _probe_in_flight

    _consecutive_failures = 0
    _disabled_until = 0.0
    _probe_in_flight = False
