"""按 session_id 读写 SharedState。这是无状态服务的关键：
服务进程不记任何东西，所有"记忆"都在 Postgres 里按 session 隔离。
"""
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, TypeVar

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
    "resume_unparsed",
    "resume_parse_limit",
}


# B3 终态进度事件（done/error, seq=100）：由 save_normalized_resume /
# mark_resume_error 在其 CAS 事务内写入——CAS 未命中则整体 no-op 零事件。
_TERMINAL_PROGRESS_SEQ = 100


@dataclass(frozen=True)
class TerminalEvent:
    step: Literal["done", "error"]
    text: str
    elapsed_ms: int = 0


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


async def accept_resume_upload(
    *,
    session_id: str,
    filename: str,
    suffix: str,
    content: bytes,
    extracted_text: str,
    pages: int,
    chars: int,
    ocr_suggested: bool,
) -> dict[str, Any]:
    """接受一次上传：状态置 resume_uploaded（等待用户确认解析），
    上传内容与本地提取结果持久化进 resume_uploads（只留最新一代）。
    行锁先行（首条 UPDATE），后续 DELETE/INSERT 被同一把锁串行化。
    不重写 SharedState JSON。"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                UPDATE session_state
                SET status = 'resume_uploaded',
                    resume_upload_generation = resume_upload_generation + 1,
                    confirmed_resume_version = NULL,
                    resume_confirmed_at = NULL,
                    updated_at = now()
                WHERE session_id = $1
                RETURNING user_id, resume_upload_generation, resume_parse_count
                """,
                session_id,
            )
            if row is None:
                raise KeyError(session_id)
            await conn.execute(
                "DELETE FROM resume_uploads WHERE session_id = $1",
                session_id,
            )
            await conn.execute(
                """
                INSERT INTO resume_uploads
                    (session_id, generation, filename, suffix, content,
                     extracted_text, pages, chars, ocr_suggested)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                session_id,
                row["resume_upload_generation"],
                filename,
                suffix,
                content,
                extracted_text,
                pages,
                chars,
                ocr_suggested,
            )
    return dict(row)


async def begin_resume_parse(
    *, session_id: str, generation: int, max_parses: int
) -> dict[str, Any]:
    """确认解析：单事务内 FOR UPDATE 单快照分类 → 扣一次解析额度 →
    置 resume_queued → 取回上传字节（入内存交给后台任务，此后任何并发
    重传的 DELETE 都伤不到在途任务）。

    分类优先级写死：parse_limit ＞ resume_changed ＞ resume_processing
    ＞ resume_unparsed。找不到会话抛 KeyError（404）。"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                SELECT status, resume_upload_generation, resume_parse_count,
                       owner_user_id
                FROM session_state
                WHERE session_id = $1
                FOR UPDATE
                """,
                session_id,
            )
            if row is None:
                raise KeyError(session_id)
            if row["resume_parse_count"] >= max_parses:
                raise ResumeLifecycleConflict("resume_parse_limit")
            if row["resume_upload_generation"] != generation:
                raise ResumeLifecycleConflict("resume_changed")
            if row["status"] == "resume_queued":
                raise ResumeLifecycleConflict("resume_processing")
            if row["status"] != "resume_uploaded":
                raise ResumeLifecycleConflict("resume_unparsed")
            await conn.execute(
                """
                UPDATE session_state
                SET status = 'resume_queued',
                    resume_parse_count = resume_parse_count + 1,
                    updated_at = now()
                WHERE session_id = $1
                """,
                session_id,
            )
            upload = await conn.fetchrow(
                """
                SELECT filename, suffix, content, extracted_text,
                       pages, chars, ocr_suggested
                FROM resume_uploads
                WHERE session_id = $1 AND generation = $2
                """,
                session_id,
                generation,
            )
            if upload is None or upload["content"] is None:
                # 行缺失/内容已清：视为已被取代，整个事务回滚（不扣额度）
                raise ResumeLifecycleConflict("resume_changed")
            return {
                "owner_user_id": row["owner_user_id"],
                "resume_parse_count": row["resume_parse_count"] + 1,
                **dict(upload),
            }


async def record_intake_progress(
    *,
    session_id: str,
    generation: int,
    seq: int,
    step: str,
    text: str,
    elapsed_ms: int = 0,
    first: bool = False,
) -> None:
    """B3 非终态进度事件（seq 1..99，任务内计数器分配）。

    守卫：INSERT 仅在会话仍处于本代 resume_queued 时生效（迟到的旧任务
    写不进新代）；首事件在同一事务内先按代数谓词清理旧代（generation <
    本代），旧任务同样删不到新代。EXISTS 为快照读，极端交错可残留有界
    孤儿行（读端按当前代过滤，无害）。"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            if first:
                await conn.execute(
                    """
                    DELETE FROM resume_intake_progress
                    WHERE session_id = $1 AND generation < $2
                    """,
                    session_id,
                    generation,
                )
            await conn.execute(
                """
                INSERT INTO resume_intake_progress
                    (session_id, generation, seq, step, text, elapsed_ms)
                SELECT $1, $2, $3, $4, $5, $6
                WHERE EXISTS (
                    SELECT 1 FROM session_state
                    WHERE session_id = $1
                      AND resume_upload_generation = $2
                      AND status = 'resume_queued'
                )
                ON CONFLICT (session_id, generation, seq) DO NOTHING
                """,
                session_id,
                generation,
                seq,
                step,
                text,
                elapsed_ms,
            )


async def load_intake_progress(*, session_id: str) -> dict[str, Any] | None:
    """B3 进度读取：当前代全量事件（ORDER BY seq，每代 ≤100 行无需游标）。
    会话不存在 → None；从未上传（generation=0）→ generation=None。
    状态行与事件两读放同一 repeatable-read 事务：单快照，杜绝
    "status 已翻转但 events 属旧拍"的撕裂响应（Codex B3 审查收编）。"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction(isolation="repeatable_read", readonly=True):
            row = await conn.fetchrow(
                """
                SELECT status, resume_upload_generation
                FROM session_state
                WHERE session_id = $1
                """,
                session_id,
            )
            if row is None:
                return None
            generation = int(row["resume_upload_generation"] or 0)
            events: list[dict[str, Any]] = []
            if generation > 0:
                records = await conn.fetch(
                    """
                    SELECT seq, step, text, elapsed_ms, created_at
                    FROM resume_intake_progress
                    WHERE session_id = $1 AND generation = $2
                    ORDER BY seq
                    """,
                    session_id,
                    generation,
                )
                events = [dict(record) for record in records]
    return {
        "status": str(row["status"] or "pending"),
        "generation": generation if generation > 0 else None,
        "events": events,
    }


async def refund_parse_count(*, session_id: str) -> None:
    """预外呼失败返还：无 generation 谓词（扣费先于任务启动已提交）；
    每任务至多一次返还由唯一调用点（_normalize_resume 的唯一 except
    分支）保证；GREATEST 兜底。"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE session_state
            SET resume_parse_count = GREATEST(resume_parse_count - 1, 0),
                updated_at = now()
            WHERE session_id = $1
            """,
            session_id,
        )


async def clear_resume_upload_content(
    *, session_id: str, generation: int
) -> None:
    """解析结束（成败均）定向清理：上传原件与临时提取副本不留存。
    行已被新上传删除时为 no-op。"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE resume_uploads
            SET content = NULL, extracted_text = NULL
            WHERE session_id = $1 AND generation = $2
            """,
            session_id,
            generation,
        )


async def get_pending_resume_upload(*, session_id: str) -> dict[str, Any] | None:
    """刷新恢复：仅当会话处于 resume_uploaded 态时返回当前代上传元数据
    （不含 content）；否则 None。"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT u.generation, u.filename, u.suffix, u.extracted_text,
                   u.pages, u.chars, u.ocr_suggested,
                   s.resume_parse_count
            FROM session_state s
            JOIN resume_uploads u
              ON u.session_id = s.session_id
             AND u.generation = s.resume_upload_generation
            WHERE s.session_id = $1
              AND s.status = 'resume_uploaded'
            """,
            session_id,
        )
    if row is None:
        return None
    return dict(row)


async def _insert_terminal_progress(
    conn: Any, session_id: str, generation: int, event: TerminalEvent
) -> None:
    # 不带 EXISTS 守卫：正当性由外层 CAS（generation+status 命中）保证；
    # 每代单任务 + CAS 单命中使 PK 冲突按构造不可达——方案 §1.2：万一
    # 发生则让唯一键异常冒泡、整个 CAS 事务回滚 no-op（禁止 DO NOTHING
    # 吞掉冲突后仍提交状态翻转；Codex B3 对侧审查裁定）。回滚后任务的
    # 唯一 except 分支走 mark_resume_error 兜底，状态机不悬空。
    await conn.execute(
        """
        INSERT INTO resume_intake_progress
            (session_id, generation, seq, step, text, elapsed_ms)
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        session_id,
        generation,
        _TERMINAL_PROGRESS_SEQ,
        event.step,
        event.text,
        event.elapsed_ms,
    )


async def save_normalized_resume(
    *,
    session_id: str,
    resume_state: ResumeState,
    content_hash: str,
    expected_generation: int,
    terminal_event: TerminalEvent | None = None,
) -> dict[str, Any] | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            locked = await _load_locked_state(conn, session_id)
            if locked.resume_upload_generation != expected_generation:
                return None
            if locked.status != "resume_queued":
                # 状态已被重传/重置改走（B2：杜绝重复任务连加 resume_version）
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
                  AND status = 'resume_queued'
                RETURNING resume_version, confirmed_resume_version,
                          resume_content_hash, resume_confirmed_at,
                          resume_upload_generation, status
                """,
                state.model_dump_json(),
                content_hash,
                session_id,
                expected_generation,
            )
            if row is not None and terminal_event is not None:
                # B3：终态事件与状态翻转同事务（CAS 命中才写，miss 零事件）
                await _insert_terminal_progress(
                    conn, session_id, expected_generation, terminal_event
                )
    if row is None:
        return None
    return {"exists": True, **dict(row)}


async def mark_resume_error(
    *,
    session_id: str,
    expected_generation: int,
    terminal_event: TerminalEvent | None = None,
) -> bool:
    """Mark only the currently accepted upload as failed.

    B3：改为单事务 UPDATE…RETURNING——命中才（同事务）写终态进度事件，
    未命中整体 no-op 零事件（旧任务晚到不产生旧代孤儿终态）。"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                UPDATE session_state
                SET status = 'resume_error',
                    updated_at = now()
                WHERE session_id = $1
                  AND resume_upload_generation = $2
                  AND status = 'resume_queued'
                RETURNING session_id
                """,
                session_id,
                expected_generation,
            )
            if row is not None and terminal_event is not None:
                await _insert_terminal_progress(
                    conn, session_id, expected_generation, terminal_event
                )
    return row is not None


async def confirm_resume(
    *, session_id: str, expected_resume_version: int | None
) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            locked = await _load_locked_state(conn, session_id)
            if locked.status == "resume_uploaded":
                raise ResumeLifecycleConflict("resume_unparsed")
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


# B2 MutationOutcome 协议：mutator 可在行锁内基于 locked 事实动态决定本次
# 落库是否写 status 列。status_override 三态：KEEP_STATUS（默认，沿用调用方
# 传入的 status）/ None（本次不写 status 列，只落 state）/ str（覆写）。
class _KeepStatus:
    """哨兵类型：与 None（合法覆写值）可区分的"沿用调用方 status"。"""


KEEP_STATUS = _KeepStatus()


@dataclass(frozen=True)
class MutationOutcome:
    result: Any
    status_override: str | None | _KeepStatus = KEEP_STATUS


async def mutate_state_atomically(
    *,
    session_id: str,
    mutator: Callable[[SharedState, int, int, str], MutationResult],
    status: str | None = None,
) -> MutationResult:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            locked = await _load_locked_state(conn, session_id)
            raw = mutator(
                locked.state,
                locked.resume_version,
                locked.resume_upload_generation,
                locked.status,
            )
            effective_status = status
            result = raw
            if isinstance(raw, MutationOutcome):
                result = raw.result
                if raw.status_override is not KEEP_STATUS:
                    effective_status = raw.status_override
            await _write_locked_state(conn, locked.state, status=effective_status)
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
