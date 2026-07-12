"""按 session_id 读写 SharedState。这是无状态服务的关键：
服务进程不记任何东西，所有"记忆"都在 Postgres 里按 session 隔离。
"""
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from app.db.pool import get_pool
from app.memory.case_base import (
    merge_case_soft_preferences,
    normalize_case_soft_preferences,
)
from app.memory.feedback import normalize_application_outcome
from app.state.schema import SharedState


MutationResult = TypeVar("MutationResult")


class FeedbackIdempotencyConflict(ValueError):
    """The idempotency key already belongs to a different feedback payload."""


@dataclass(frozen=True)
class FeedbackWriteResult:
    feedback_id: int
    created: bool
    feedback: dict[str, Any]


async def save_state(state: SharedState, status: str = "running") -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO session_state (
                    session_id, user_id, state, status, updated_at
                )
                VALUES ($1, $2, $3::jsonb, $4, now())
                ON CONFLICT (session_id) DO NOTHING
                """,
                state.session_id,
                state.user_id,
                state.model_dump_json(),
                status,
            )

            latest = await _load_locked_state(conn, state.session_id)
            merged = _merge_feedback_owned_state(latest, state)
            await conn.execute(
                """
                UPDATE session_state
                SET state = $1::jsonb,
                    status = $2,
                    updated_at = now()
                WHERE session_id = $3
                """,
                merged.model_dump_json(),
                status,
                merged.session_id,
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


async def get_resume_metadata(session_id: str) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT resume_version, confirmed_resume_version,
                   resume_content_hash, resume_confirmed_at
            FROM session_state
            WHERE session_id = $1
            """,
            session_id,
        )
    if row is None:
        return {"exists": False}
    return {"exists": True, **dict(row)}


async def mark_resume_normalized(
    *, session_id: str, content_hash: str
) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE session_state
            SET resume_version = resume_version + 1,
                confirmed_resume_version = NULL,
                resume_content_hash = $2,
                resume_confirmed_at = NULL,
                status = 'resume_ready',
                version = version + 1,
                updated_at = now()
            WHERE session_id = $1
            RETURNING resume_version, confirmed_resume_version,
                      resume_content_hash, resume_confirmed_at
            """,
            session_id,
            content_hash,
        )
    if row is None:
        raise KeyError(session_id)
    return {"exists": True, **dict(row)}


async def confirm_resume(*, session_id: str) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE session_state
            SET confirmed_resume_version = resume_version,
                resume_confirmed_at = now(),
                version = version + 1,
                updated_at = now()
            WHERE session_id = $1 AND resume_version > 0
            RETURNING resume_version, confirmed_resume_version,
                      resume_content_hash, resume_confirmed_at
            """,
            session_id,
        )
    if row is None:
        raise KeyError(session_id)
    return {"exists": True, **dict(row)}


async def mutate_state_atomically(
    *, session_id: str, mutator: Callable[[SharedState], MutationResult]
) -> MutationResult:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            state = await _load_locked_state(conn, session_id)
            result = mutator(state)
            await _write_locked_state(conn, state)
            return result


async def add_feedback(
    *,
    session_id: str,
    job_id: str,
    outcome: str,
    reason: str | None = None,
    user_rating: int | None = None,
    idempotency_key: str | None = None,
) -> FeedbackWriteResult:
    canonical_outcome = normalize_application_outcome(outcome)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            state = await _load_locked_state(conn, session_id)
            if idempotency_key:
                existing_feedback = _feedback_for_idempotency_key(
                    state, idempotency_key
                )
                if existing_feedback is not None:
                    if not _feedback_payload_matches(
                        existing_feedback,
                        job_id=job_id,
                        outcome=canonical_outcome,
                        reason=reason,
                        user_rating=user_rating,
                    ):
                        raise FeedbackIdempotencyConflict(idempotency_key)
                    return FeedbackWriteResult(
                        feedback_id=int(existing_feedback["feedback_id"]),
                        created=False,
                        feedback=dict(existing_feedback),
                    )
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
            feedback_entry = {
                "job_id": job_id,
                "outcome": canonical_outcome,
                "reason": reason,
                "user_rating": user_rating,
                "feedback_id": feedback_id,
            }
            if idempotency_key:
                feedback_entry["idempotency_key"] = idempotency_key
            state.feedback_state.user_feedback.append(feedback_entry)
            await _write_locked_state(conn, state)
            return FeedbackWriteResult(
                feedback_id=feedback_id,
                created=True,
                feedback=dict(feedback_entry),
            )


def _feedback_for_idempotency_key(
    state: SharedState, idempotency_key: str
) -> dict[str, Any] | None:
    for entry in state.feedback_state.user_feedback:
        if entry.get("idempotency_key") != idempotency_key:
            continue
        if entry.get("feedback_id") is not None:
            return entry
    return None


def _feedback_payload_matches(
    entry: dict[str, Any],
    *,
    job_id: str,
    outcome: str,
    reason: str | None,
    user_rating: int | None,
) -> bool:
    return (
        entry.get("job_id") == job_id
        and entry.get("outcome") == outcome
        and entry.get("reason") == reason
        and entry.get("user_rating") == user_rating
    )


async def _load_locked_state(conn: Any, session_id: str) -> SharedState:
    state = await _load_locked_state_or_none(conn, session_id)
    if state is None:
        raise KeyError(session_id)
    return state


async def _load_locked_state_or_none(
    conn: Any, session_id: str
) -> SharedState | None:
    row = await conn.fetchrow(
        "SELECT state FROM session_state WHERE session_id = $1 FOR UPDATE",
        session_id,
    )
    if row is None:
        return None
    return SharedState.model_validate(json.loads(row["state"]))


def _merge_feedback_owned_state(
    latest: SharedState, incoming: SharedState
) -> SharedState:
    merged = incoming.model_copy(deep=True)
    merged.feedback_state.application_history = _merge_append_only_entries(
        latest.feedback_state.application_history,
        incoming.feedback_state.application_history,
    )
    merged.feedback_state.interview_outcomes = _merge_append_only_entries(
        latest.feedback_state.interview_outcomes,
        incoming.feedback_state.interview_outcomes,
    )
    merged.feedback_state.user_feedback = _merge_append_only_entries(
        latest.feedback_state.user_feedback,
        incoming.feedback_state.user_feedback,
        identity_keys=("feedback_id", "idempotency_key"),
    )
    merged.feedback_state.case_soft_preferences = _merge_case_preferences(
        latest.feedback_state.case_soft_preferences,
        incoming.feedback_state.case_soft_preferences,
    )
    merged.supervisor_log = _merge_append_only_entries(
        latest.supervisor_log,
        incoming.supervisor_log,
    )
    return merged


def _merge_append_only_entries(
    latest: list[dict],
    incoming: list[dict],
    *,
    identity_keys: tuple[str, ...] = (),
) -> list[dict]:
    merged = [dict(item) for item in latest]
    identities = {
        identity
        for item in latest
        if (identity := _entry_identity(item, identity_keys)) is not None
    }
    for item in incoming:
        identity = _entry_identity(item, identity_keys)
        if identity is not None:
            if identity in identities:
                continue
            identities.add(identity)
        elif item in merged:
            continue
        merged.append(dict(item))
    return merged


def _entry_identity(
    entry: dict, identity_keys: tuple[str, ...]
) -> tuple[str, str] | None:
    for key in identity_keys:
        value = entry.get(key)
        if value is not None and str(value):
            return key, str(value)
    return None


def _merge_case_preferences(latest: dict, incoming: dict) -> dict:
    merged = merge_case_soft_preferences({}, normalize_case_soft_preferences(latest))
    return merge_case_soft_preferences(merged, normalize_case_soft_preferences(incoming))


async def _write_locked_state(conn: Any, state: SharedState) -> None:
    await conn.execute(
        """
        UPDATE session_state
        SET state = $1::jsonb,
            updated_at = now()
        WHERE session_id = $2
        """,
        state.model_dump_json(),
        state.session_id,
    )
