"""按 session_id 读写 SharedState。这是无状态服务的关键：
服务进程不记任何东西，所有"记忆"都在 Postgres 里按 session 隔离。
"""
import json
from typing import Any

from app.db.pool import get_pool
from app.memory.feedback import normalize_application_outcome
from app.state.schema import SharedState


async def save_state(state: SharedState, status: str = "running") -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO session_state (session_id, user_id, state, status, updated_at)
            VALUES ($1, $2, $3::jsonb, $4, now())
            ON CONFLICT (session_id)
            DO UPDATE SET state = EXCLUDED.state,
                          status = EXCLUDED.status,
                          updated_at = now()
            """,
            state.session_id, state.user_id, state.model_dump_json(), status,
        )


async def load_state(session_id: str) -> SharedState | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT state FROM session_state WHERE session_id = $1", session_id
        )
    if row is None:
        return None
    return SharedState.model_validate(json.loads(row["state"]))


async def load_state_with_status(session_id: str) -> tuple[SharedState, str] | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT state, status FROM session_state WHERE session_id = $1",
            session_id,
        )
    if row is None:
        return None
    return SharedState.model_validate(json.loads(row["state"])), row["status"]


async def add_feedback(
    *,
    session_id: str,
    job_id: str,
    outcome: str,
    reason: str | None = None,
    user_rating: int | None = None,
) -> int:
    state_with_status = await load_state_with_status(session_id)
    if state_with_status is None:
        raise KeyError(session_id)

    state, status = state_with_status
    canonical_outcome = normalize_application_outcome(outcome)
    payload: dict[str, Any] = {
        "job_id": job_id,
        "outcome": canonical_outcome,
        "reason": reason,
        "user_rating": user_rating,
    }

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO feedback_memory (user_id, job_id, outcome, reason, user_rating)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING feedback_id
            """,
            state.user_id,
            job_id,
            canonical_outcome,
            reason,
            user_rating,
        )

    feedback_id = int(row["feedback_id"])
    payload["feedback_id"] = feedback_id
    state.feedback_state.user_feedback.append(payload)
    await save_state(state, status=status or "feedback_recorded")
    return feedback_id
