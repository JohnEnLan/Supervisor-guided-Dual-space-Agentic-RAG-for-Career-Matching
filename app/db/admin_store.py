from __future__ import annotations

import json
from typing import Any

from app.db.pool import get_pool


_ADMIN_PAGE_SIZE = 20


async def get_admin_overview() -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as connection:
        aggregate = await connection.fetchrow(
            """
            SELECT (SELECT COUNT(*) FROM users) AS users_total,
                   (SELECT COUNT(*)
                    FROM product_events
                    WHERE kind = 'login'
                      AND created_at >=
                          date_trunc('day', now() AT TIME ZONE 'UTC')
                          AT TIME ZONE 'UTC') AS logins_today,
                   (SELECT COUNT(*)
                    FROM product_events
                    WHERE kind = 'login'
                      AND created_at >=
                          (date_trunc('day', now() AT TIME ZONE 'UTC')
                           AT TIME ZONE 'UTC') - interval '6 days')
                       AS logins_7d,
                   (SELECT COUNT(*)
                    FROM product_events
                    WHERE kind = 'login'
                      AND created_at >=
                          (date_trunc('day', now() AT TIME ZONE 'UTC')
                           AT TIME ZONE 'UTC') - interval '29 days')
                       AS logins_30d,
                   (SELECT COUNT(*) FROM session_state) AS sessions_total,
                   (SELECT COUNT(*)
                    FROM product_events
                    WHERE kind = 'consult_turn') AS consult_turns_total,
                   (SELECT COUNT(*) FROM match_runs) AS runs_total
            """
        )
        day_rows = await connection.fetch(
            """
            WITH usage_by_day AS (
                SELECT (created_at AT TIME ZONE 'UTC')::date AS day,
                       total_tokens
                FROM llm_usage
                WHERE created_at >=
                      (date_trunc('day', now() AT TIME ZONE 'UTC')
                       AT TIME ZONE 'UTC') - interval '29 days'
            )
            SELECT day::text AS date,
                   SUM(total_tokens)::bigint AS total_tokens
            FROM usage_by_day
            GROUP BY day
            ORDER BY day ASC
            """
        )
        model_rows = await connection.fetch(
            """
            SELECT model,
                   SUM(prompt_tokens)::bigint AS prompt_tokens,
                   SUM(completion_tokens)::bigint AS completion_tokens,
                   SUM(total_tokens)::bigint AS total_tokens
            FROM llm_usage
            GROUP BY model
            ORDER BY model ASC
            """
        )

    values = dict(aggregate or {})
    return {
        "users_total": int(values.get("users_total") or 0),
        "logins_today": int(values.get("logins_today") or 0),
        "logins_7d": int(values.get("logins_7d") or 0),
        "logins_30d": int(values.get("logins_30d") or 0),
        "sessions_total": int(values.get("sessions_total") or 0),
        "consult_turns_total": int(values.get("consult_turns_total") or 0),
        "runs_total": int(values.get("runs_total") or 0),
        "tokens_by_day": [
            {
                "date": str(row["date"]),
                "total_tokens": int(row["total_tokens"]),
            }
            for row in day_rows
        ],
        "tokens_by_model": [
            {
                "model": str(row["model"]),
                "prompt_tokens": _optional_int(row["prompt_tokens"]),
                "completion_tokens": _optional_int(row["completion_tokens"]),
                "total_tokens": int(row["total_tokens"]),
            }
            for row in model_rows
        ],
    }


async def list_admin_users(*, page: int) -> dict[str, Any]:
    offset = (page - 1) * _ADMIN_PAGE_SIZE
    pool = await get_pool()
    async with pool.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT account.user_id,
                   email.provider_uid AS email,
                   account.created_at,
                   account.last_login_at,
                   (SELECT COUNT(*)
                    FROM session_state AS counted_session
                    WHERE counted_session.owner_user_id = account.user_id)
                       AS session_count,
                   resume.state #>> '{resume_state,contact,name}'
                       AS resume_name,
                   resume.state #>> '{resume_state,contact,phone}'
                       AS resume_phone,
                   resume.state #>> '{resume_state,education,0,institution}'
                       AS resume_school,
                   resume.state #>> '{resume_state,education,0,degree}'
                       AS resume_degree
            FROM users AS account
            LEFT JOIN LATERAL (
                SELECT identity.provider_uid
                FROM user_identities AS identity
                WHERE identity.user_id = account.user_id
                  AND identity.provider = 'email'
                ORDER BY identity.created_at ASC, identity.identity_id ASC
                LIMIT 1
            ) AS email ON TRUE
            LEFT JOIN LATERAL (
                SELECT session.session_id,
                       session.state,
                       session.resume_confirmed_at,
                       session.resume_version
                FROM session_state AS session
                WHERE session.owner_user_id = account.user_id
                  AND session.resume_version > 0
                ORDER BY session.resume_confirmed_at DESC NULLS LAST,
                         session.resume_version DESC,
                         session.session_id ASC
                LIMIT 1
            ) AS resume ON TRUE
            ORDER BY account.created_at DESC, account.user_id ASC
            LIMIT $1 OFFSET $2
            """,
            _ADMIN_PAGE_SIZE + 1,
            offset,
        )

    has_more = len(rows) > _ADMIN_PAGE_SIZE
    return {
        "items": [
            {
                **dict(row),
                "user_id": str(row["user_id"]),
                "session_count": int(row["session_count"] or 0),
            }
            for row in rows[:_ADMIN_PAGE_SIZE]
        ],
        "page": page,
        "page_size": _ADMIN_PAGE_SIZE,
        "has_more": has_more,
    }


async def get_admin_user_resume(*, user_id: str) -> dict[str, Any] | None:
    pool = await get_pool()
    async with pool.acquire() as connection:
        row = await connection.fetchrow(
            """
            SELECT account.user_id,
                   resume.session_id,
                   resume.state -> 'resume_state' AS resume_state
            FROM users AS account
            LEFT JOIN LATERAL (
                SELECT session.session_id,
                       session.state,
                       session.resume_confirmed_at,
                       session.resume_version
                FROM session_state AS session
                WHERE session.owner_user_id = account.user_id
                  AND session.resume_version > 0
                ORDER BY session.resume_confirmed_at DESC NULLS LAST,
                         session.resume_version DESC,
                         session.session_id ASC
                LIMIT 1
            ) AS resume ON TRUE
            WHERE account.user_id = $1::uuid
            """,
            user_id,
        )
    if row is None:
        return None
    return {
        "user_id": str(row["user_id"]),
        "session_id": (
            str(row["session_id"]) if row["session_id"] is not None else None
        ),
        "resume_state": _json_object_or_none(row["resume_state"]),
    }


async def reset_resume_parse_count(*, session_id: str) -> dict[str, Any]:
    """Reset parse quota without re-queueing the current generation.

    A future recovery path that moves the same generation to resume_queued must
    first delete its resume_intake_progress rows; this endpoint never re-queues.
    """
    pool = await get_pool()
    async with pool.acquire() as connection:
        async with connection.transaction():
            row = await connection.fetchrow(
                """
                SELECT session_id, status, resume_parse_count,
                       resume_upload_generation
                FROM session_state
                WHERE session_id = $1
                FOR UPDATE
                """,
                session_id,
            )
            if row is None:
                raise KeyError(session_id)

            status = str(row["status"])
            # §5.3 字面：② 的 queued 遗留清理不以计数为前提——极端双故障
            # 角（refund 成功但 mark 失败）会留下 count=0 + queued 的孤儿，
            # 提前短路会让它永卡（协调者验收修正）。仅"计数已 0 且非
            # queued"才是真 no-op。
            if (
                int(row["resume_parse_count"] or 0) == 0
                and status != "resume_queued"
            ):
                return _reset_result(session_id, status)

            if status == "resume_queued":
                await connection.execute(
                    """
                    UPDATE session_state
                    SET resume_parse_count = 0,
                        status = 'resume_error',
                        updated_at = now()
                    WHERE session_id = $1
                    """,
                    session_id,
                )
                await connection.execute(
                    """
                    UPDATE resume_uploads
                    SET content = NULL,
                        extracted_text = NULL
                    WHERE session_id = $1
                    """,
                    session_id,
                )
                status = "resume_error"
            else:
                await connection.execute(
                    """
                    UPDATE session_state
                    SET resume_parse_count = 0,
                        updated_at = now()
                    WHERE session_id = $1
                    """,
                    session_id,
                )
    return _reset_result(session_id, status)


def _reset_result(session_id: str, status: str) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "resume_parse_count": 0,
        "status": status,
    }


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _json_object_or_none(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value) if isinstance(value, dict) else None
