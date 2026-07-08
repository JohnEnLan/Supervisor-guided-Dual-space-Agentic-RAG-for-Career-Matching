from __future__ import annotations

import json
from typing import Any

from app.db.pool import get_pool
from app.state.schema import ResumeState, StrategyState


def build_private_resume_payload(
    *,
    resume_state: ResumeState,
    raw_resume_text: str | None = None,
    user_goal_text: str | None = None,
    strategy_state: StrategyState | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "memory_scope": "private",
        "resume_state": resume_state.model_dump(mode="json"),
        "user_goal_text": user_goal_text,
        "metadata": metadata or {},
    }
    if raw_resume_text is not None:
        payload["raw_resume_text"] = raw_resume_text
    if strategy_state is not None:
        payload["strategy_state"] = strategy_state.model_dump(mode="json")
    return payload


async def save_private_resume_memory(
    *,
    user_id: str,
    resume_version_id: str,
    resume_state: ResumeState,
    raw_resume_text: str | None = None,
    user_goal_text: str | None = None,
    strategy_state: StrategyState | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    payload = build_private_resume_payload(
        resume_state=resume_state,
        raw_resume_text=raw_resume_text,
        user_goal_text=user_goal_text,
        strategy_state=strategy_state,
        metadata=metadata,
    )
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO private_memory (user_id, resume_version_id, payload, updated_at)
            VALUES ($1, $2, $3::jsonb, now())
            ON CONFLICT (user_id, resume_version_id)
            DO UPDATE SET payload = EXCLUDED.payload,
                          updated_at = now()
            """,
            user_id,
            resume_version_id,
            json.dumps(payload, ensure_ascii=False),
        )


async def load_private_resume_memory(
    *, user_id: str, resume_version_id: str
) -> dict[str, Any] | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT payload
            FROM private_memory
            WHERE user_id = $1 AND resume_version_id = $2
            """,
            user_id,
            resume_version_id,
        )
    if row is None:
        return None
    return _decode_payload(row["payload"])


async def list_private_resume_history(
    *, user_id: str, limit: int = 20
) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT resume_version_id, payload, updated_at
            FROM private_memory
            WHERE user_id = $1
            ORDER BY updated_at DESC
            LIMIT $2
            """,
            user_id,
            limit,
        )
    return [
        {
            "resume_version_id": row["resume_version_id"],
            "payload": _decode_payload(row["payload"]),
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


async def list_private_resume_versions(
    *, user_id: str, limit: int = 20
) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT resume_version_id, updated_at
            FROM private_memory
            WHERE user_id = $1
            ORDER BY updated_at DESC
            LIMIT $2
            """,
            user_id,
            limit,
        )
    return [dict(row) for row in rows]


def _decode_payload(payload: Any) -> dict[str, Any]:
    return json.loads(payload) if isinstance(payload, str) else dict(payload)
