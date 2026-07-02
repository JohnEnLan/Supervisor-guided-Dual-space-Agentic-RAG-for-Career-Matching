from __future__ import annotations

from typing import Any

from app.db.pool import get_pool


POSITIVE_OUTCOMES = {
    "passed_screen",
    "oa",
    "interview",
    "interview_1",
    "interview_2",
    "final_interview",
    "offer",
}


def is_positive_outcome(outcome: str) -> bool:
    return outcome.strip().casefold() in POSITIVE_OUTCOMES


async def record_application_feedback(
    *,
    user_id: str,
    job_id: str,
    outcome: str,
    reason: str | None = None,
    user_rating: int | None = None,
) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO feedback_memory (user_id, job_id, outcome, reason, user_rating)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING feedback_id
            """,
            user_id,
            job_id,
            outcome,
            reason,
            user_rating,
        )
    return int(row["feedback_id"])


async def list_feedback_for_user(
    *, user_id: str, limit: int = 50
) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT feedback_id, user_id, job_id, outcome, reason, user_rating, created_at
            FROM feedback_memory
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            user_id,
            limit,
        )
    return [dict(row) for row in rows]
