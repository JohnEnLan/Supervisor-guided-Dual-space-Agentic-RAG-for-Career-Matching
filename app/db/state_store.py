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
from app.state.schema import ResumeState, SharedState


MutationResult = TypeVar("MutationResult")
_RESUME_LIFECYCLE_DETAILS = {
    "resume_changed",
    "resume_processing",
    "resume_error",
}


class ResumeLifecycleConflict(ValueError):
    def __init__(self, detail: str):
        if detail not in _RESUME_LIFECYCLE_DETAILS:
            raise ValueError(f"unknown resume lifecycle detail: {detail}")
        self.detail = detail
        super().__init__(detail)


class FeedbackIdempotencyConflict(ValueError):
    """The idempotency key already belongs to a different feedback payload."""


@dataclass(frozen=True)
class FeedbackWriteResult:
    feedback_id: int
    created: bool
    feedback: dict[str, Any]


@dataclass(frozen=True)
class ConsultContext:
    state: SharedState
    status: str
    resume_version: int
    confirmed_resume_version: int | None
    resume_upload_generation: int


async def save_state(
    state: SharedState,
    status: str = "running",
    *,
    owner_user_id: str | None = None,
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO session_state (
                    session_id, user_id, state, status, owner_user_id, updated_at
                )
                VALUES ($1, $2, $3::jsonb, $4, $5::uuid, now())
                ON CONFLICT (session_id) DO NOTHING
                """,
                state.session_id,
                state.user_id,
                state.model_dump_json(),
                status,
                owner_user_id,
            )

            locked = await _load_locked_state(conn, state.session_id)
            merged = _merge_feedback_owned_state(locked.state, state)
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


async def count_owned_sessions(owner_user_id: str) -> int:
    pool = await get_pool()
    async with pool.acquire() as connection:
        return int(
            await connection.fetchval(
                """
                SELECT count(*)
                FROM session_state
                WHERE owner_user_id = $1::uuid
                """,
                owner_user_id,
            )
        )


async def create_owned_session_with_quota(
    state: SharedState,
    *,
    owner_user_id: str,
    quota: int,
) -> bool:
    """Atomically enforce one owner's session quota and insert a new session."""
    pool = await get_pool()
    async with pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1::text, 0))",
                owner_user_id,
            )
            owned = int(
                await connection.fetchval(
                    """
                    SELECT count(*)
                    FROM session_state
                    WHERE owner_user_id = $1::uuid
                    """,
                    owner_user_id,
                )
            )
            if owned >= int(quota):
                return False
            await connection.execute(
                """
                INSERT INTO session_state (
                    session_id, user_id, state, status, owner_user_id, updated_at
                )
                VALUES ($1, $2, $3::jsonb, 'awaiting_resume', $4::uuid, now())
                """,
                state.session_id,
                state.user_id,
                state.model_dump_json(),
                owner_user_id,
            )
    return True


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


async def load_consult_context(session_id: str) -> ConsultContext | None:
    """Load state and resume lifecycle metadata from one database snapshot."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT state, status, resume_version, confirmed_resume_version,
                   resume_upload_generation
            FROM session_state
            WHERE session_id = $1
            """,
            session_id,
        )
    return _consult_context_from_row(row)


async def get_resume_metadata(session_id: str) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT status, resume_version, confirmed_resume_version,
                   resume_content_hash, resume_confirmed_at,
                   resume_upload_generation
            FROM session_state
            WHERE session_id = $1
            """,
            session_id,
        )
    if row is None:
        return {"exists": False}
    return {"exists": True, **dict(row)}


async def accept_resume_upload(*, session_id: str) -> dict[str, Any]:
    """Queue one upload without ever rewriting the SharedState JSON."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE session_state
            SET status = 'resume_queued',
                resume_upload_generation = resume_upload_generation + 1,
                confirmed_resume_version = NULL,
                resume_confirmed_at = NULL,
                updated_at = now()
            WHERE session_id = $1
            RETURNING user_id, resume_upload_generation
            """,
            session_id,
        )
    if row is None:
        raise KeyError(session_id)
    return dict(row)


async def save_normalized_resume(
    *,
    session_id: str,
    resume_state: ResumeState,
    content_hash: str,
    expected_generation: int,
) -> dict[str, Any] | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            locked = await _load_locked_state(conn, session_id)
            if locked.resume_upload_generation != expected_generation:
                return None
            state = locked.state
            state.resume_state = resume_state.model_copy(deep=True)
            row = await conn.fetchrow(
                """
                UPDATE session_state
                SET state = $1::jsonb,
                    resume_version = resume_version + 1,
                    confirmed_resume_version = NULL,
                    resume_content_hash = $2,
                    resume_confirmed_at = NULL,
                    status = 'resume_ready',
                    version = version + 1,
                    updated_at = now()
                WHERE session_id = $3
                  AND resume_upload_generation = $4
                RETURNING resume_version, confirmed_resume_version,
                          resume_content_hash, resume_confirmed_at,
                          resume_upload_generation, status
                """,
                state.model_dump_json(),
                content_hash,
                session_id,
                expected_generation,
            )
    if row is None:
        return None
    return {"exists": True, **dict(row)}


async def mark_resume_error(
    *, session_id: str, expected_generation: int
) -> bool:
    """Mark only the currently accepted upload as failed."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE session_state
            SET status = 'resume_error',
                updated_at = now()
            WHERE session_id = $1
              AND resume_upload_generation = $2
              AND status = 'resume_queued'
            """,
            session_id,
            expected_generation,
        )
    return result == "UPDATE 1"


async def confirm_resume(
    *, session_id: str, expected_resume_version: int | None
) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            locked = await _load_locked_state(conn, session_id)
            if locked.status == "resume_error":
                raise ResumeLifecycleConflict("resume_error")
            if locked.status != "resume_ready" or locked.resume_version < 1:
                raise ResumeLifecycleConflict("resume_processing")
            if (
                expected_resume_version is not None
                and expected_resume_version != locked.resume_version
            ):
                raise ResumeLifecycleConflict("resume_changed")
            row = await conn.fetchrow(
                """
                UPDATE session_state
                SET confirmed_resume_version = resume_version,
                    resume_confirmed_at = now(),
                    version = version + 1,
                    updated_at = now()
                WHERE session_id = $1
                RETURNING resume_version, confirmed_resume_version,
                          resume_content_hash, resume_confirmed_at,
                          resume_upload_generation, status
                """,
                session_id,
            )
    if row is None:  # pragma: no cover - row is locked above
        raise KeyError(session_id)
    return {"exists": True, **dict(row)}


async def mutate_state_atomically(
    *,
    session_id: str,
    mutator: Callable[[SharedState, int, int], MutationResult],
    status: str | None = None,
) -> MutationResult:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            locked = await _load_locked_state(conn, session_id)
            result = mutator(
                locked.state,
                locked.resume_version,
                locked.resume_upload_generation,
            )
            await _write_locked_state(conn, locked.state, status=status)
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
            locked = await _load_locked_state(conn, session_id)
            state = locked.state
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


async def _load_locked_state(conn: Any, session_id: str) -> ConsultContext:
    context = await _load_locked_state_or_none(conn, session_id)
    if context is None:
        raise KeyError(session_id)
    return context


async def _load_locked_state_or_none(
    conn: Any, session_id: str
) -> ConsultContext | None:
    row = await conn.fetchrow(
        """
        SELECT state, status, resume_version, confirmed_resume_version,
               resume_upload_generation
        FROM session_state
        WHERE session_id = $1
        FOR UPDATE
        """,
        session_id,
    )
    return _consult_context_from_row(row)


def _consult_context_from_row(row: Any | None) -> ConsultContext | None:
    if row is None:
        return None
    return ConsultContext(
        state=SharedState.model_validate(json.loads(row["state"])),
        status=str(_row_value(row, "status", "pending")),
        resume_version=int(_row_value(row, "resume_version", 0) or 0),
        confirmed_resume_version=_optional_int(
            _row_value(row, "confirmed_resume_version", None)
        ),
        resume_upload_generation=int(
            _row_value(row, "resume_upload_generation", 0) or 0
        ),
    )


def _row_value(row: Any, key: str, default: Any) -> Any:
    try:
        return row[key]
    except (KeyError, TypeError):
        return default


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


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


async def _write_locked_state(
    conn: Any,
    state: SharedState,
    *,
    status: str | None = None,
) -> None:
    if status is not None:
        await conn.execute(
            """
            UPDATE session_state
            SET state = $1::jsonb,
                status = $2,
                updated_at = now()
            WHERE session_id = $3
            """,
            state.model_dump_json(),
            status,
            state.session_id,
        )
        return
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
