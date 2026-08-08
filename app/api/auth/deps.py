from __future__ import annotations

from dataclasses import replace
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from app.api.auth.sessions import (
    AuthedUser,
    decode_session_token,
    load_user,
    session_cookie_name,
)
from app.config import parse_admin_emails, settings
from app.db.pool import get_pool


async def optional_current_user(request: Request) -> AuthedUser | None:
    token = request.cookies.get(session_cookie_name())
    if token is None:
        if settings.auth_enforced:
            raise HTTPException(status_code=401, detail="authentication required")
        return None
    try:
        payload = decode_session_token(token)
    except (RuntimeError, ValueError):
        raise HTTPException(status_code=401, detail="invalid session") from None
    user = await load_user(str(payload["user_id"]))
    if (
        user is None
        or user.status != "active"
        or user.token_version != int(payload["token_version"])
    ):
        raise HTTPException(status_code=401, detail="invalid session")
    return replace(user, provider=payload.get("idp"))


async def current_user(
    user: Annotated[AuthedUser | None, Depends(optional_current_user)],
) -> AuthedUser:
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return user


async def require_owned_session(
    session_id: str,
    user: Annotated[AuthedUser | None, Depends(optional_current_user)],
) -> None:
    if user is None:
        return
    pool = await get_pool()
    async with pool.acquire() as connection:
        row = await connection.fetchrow(
            """
            SELECT owner_user_id
            FROM session_state
            WHERE session_id = $1
            """,
            session_id,
        )
    if row is None or str(row["owner_user_id"] or "") != user.user_id:
        raise HTTPException(status_code=404, detail="session_id not found")


async def require_owned_run(
    run_id: str,
    user: Annotated[AuthedUser | None, Depends(optional_current_user)],
) -> None:
    if user is None:
        return
    pool = await get_pool()
    async with pool.acquire() as connection:
        row = await connection.fetchrow(
            """
            SELECT session.owner_user_id
            FROM match_runs AS run
            INNER JOIN session_state AS session
                ON session.session_id = run.session_id
            WHERE run.run_id = $1
            """,
            run_id,
        )
    if row is None or str(row["owner_user_id"] or "") != user.user_id:
        raise HTTPException(status_code=404, detail="run_id not found")


async def require_admin(
    user: Annotated[AuthedUser | None, Depends(optional_current_user)],
) -> None:
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    if user.provider != "email":
        raise HTTPException(status_code=403, detail="administrator required")
    allowlist = parse_admin_emails(settings.admin_emails)
    if not allowlist:
        raise HTTPException(status_code=403, detail="administrator required")

    pool = await get_pool()
    async with pool.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT account.is_admin, identity.provider_uid
            FROM users AS account
            LEFT JOIN user_identities AS identity
                ON identity.user_id = account.user_id
               AND identity.provider = 'email'
            WHERE account.user_id = $1::uuid
            ORDER BY identity.identity_id ASC
            """,
            user.user_id,
        )
    if (
        not rows
        or not bool(rows[0]["is_admin"])
        or not any(
            row["provider_uid"] is not None
            and str(row["provider_uid"]).casefold() in allowlist
            for row in rows
        )
    ):
        raise HTTPException(status_code=403, detail="administrator required")


async def require_monitoring_enabled() -> None:
    if not settings.monitoring_enabled:
        raise HTTPException(
            status_code=404,
            detail="monitoring capability disabled",
        )
