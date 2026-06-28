"""按 session_id 读写 SharedState。这是无状态服务的关键：
服务进程不记任何东西，所有"记忆"都在 Postgres 里按 session 隔离。
"""
import json
from app.db.pool import get_pool
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


async def get_status(session_id: str) -> str | None:
    """前端轮询用。"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status FROM session_state WHERE session_id = $1", session_id
        )
    return row["status"] if row else None
