from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from app.db.pool import get_pool


PUBLIC_PAYLOAD_KEYS = frozenset(
    {
        "message",
        "reason_code",
        "warning_code",
        "attempt",
        "max_attempts",
        "count",
        "duration_ms",
        "partial",
        "retry_after_ms",
    }
)
PRIVATE_KEYS = frozenset(
    {
        "prompt",
        "system_prompt",
        "state",
        "shared_state",
        "supervisor_log",
        "user_id",
        "email",
        "phone",
        "api_key",
    }
)


def _validate_public_payload(value: Any, *, key: str | None = None) -> None:
    if key in PRIVATE_KEYS:
        raise ValueError(f"payload key {key!r} is not public")
    if isinstance(value, Mapping):
        for child_key, child_value in value.items():
            if key is None and child_key not in PUBLIC_PAYLOAD_KEYS:
                raise ValueError(f"payload key {child_key!r} is not public")
            _validate_public_payload(child_value, key=str(child_key))
    elif isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        for child in value:
            _validate_public_payload(child)


async def append_event(
    *,
    run_id: str,
    event_type: str,
    public_payload: dict[str, Any],
    stage: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    _validate_public_payload(public_payload)
    pool = await get_pool()
    async with pool.acquire() as connection:
        row = await connection.fetchrow(
            """
            INSERT INTO run_events
                (run_id, event_type, stage, status, public_payload)
            VALUES ($1, $2, $3, $4, $5::jsonb)
            RETURNING event_id, run_id, event_type, stage, status,
                      public_payload, created_at
            """,
            run_id,
            event_type,
            stage,
            status,
            json.dumps(public_payload, ensure_ascii=False),
        )
    if row is None:
        raise RuntimeError("database did not return the created run event")
    return dict(row)


async def list_events(*, run_id: str) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT event_id, run_id, event_type, stage, status,
                   public_payload, created_at
            FROM run_events
            WHERE run_id = $1
            ORDER BY event_id
            """,
            run_id,
        )
    return [dict(row) for row in rows]
