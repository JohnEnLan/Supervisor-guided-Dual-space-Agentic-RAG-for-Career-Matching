from __future__ import annotations

import ipaddress
import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from app.api.auth.deps import current_user
from app.api.auth.otp import (
    OtpExpired,
    OtpInvalid,
    OtpRateLimited,
    issue_otp,
    verify_otp,
)
from app.api.auth.providers import send_otp
from app.api.auth.sessions import (
    AuthedUser,
    clear_session_cookie,
    issue_session_token,
    login_or_register,
    set_session_cookie,
)
from app.api.v1.schemas import (
    MeResponse,
    MeSessionResponse,
    MeSessionsResponse,
    OtpRequest,
    OtpRequestAccepted,
    OtpVerifyRequest,
    ProfilePatchRequest,
    ProfileResponse,
)
from app.db.pool import get_pool


router = APIRouter()
logger = logging.getLogger(__name__)
CurrentUser = Annotated[AuthedUser, Depends(current_user)]


def _client_ip(request: Request) -> str:
    candidate = request.client.host if request.client is not None else ""
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return "0.0.0.0"


def _me(user: AuthedUser) -> MeResponse:
    return MeResponse(
        user_id=user.user_id,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        status=user.status,
        is_admin=user.is_admin,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


@router.post(
    "/auth/otp/request",
    response_model=OtpRequestAccepted,
    status_code=202,
)
async def request_otp(
    payload: OtpRequest,
    http_request: Request,
) -> OtpRequestAccepted:
    try:
        issued = await issue_otp(
            channel=payload.channel,
            target=payload.target,
            client_ip=_client_ip(http_request),
        )
    except OtpRateLimited:
        return OtpRequestAccepted()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    try:
        await send_otp(
            channel=payload.channel,
            target=issued.normalized_target,
            code=issued.code,
        )
    except Exception:
        logger.warning(
            "otp_delivery_failed channel=%s",
            payload.channel,
        )
    return OtpRequestAccepted()


@router.post("/auth/otp/verify", response_model=MeResponse)
async def verify_login_otp(
    payload: OtpVerifyRequest,
    response: Response,
) -> MeResponse:
    try:
        provider_uid = await verify_otp(
            channel=payload.channel,
            target=payload.target,
            code=payload.code,
        )
    except OtpExpired:
        raise HTTPException(status_code=410, detail="OTP expired") from None
    except OtpRateLimited:
        raise HTTPException(status_code=429, detail="too many attempts") from None
    except (OtpInvalid, ValueError):
        raise HTTPException(status_code=401, detail="invalid OTP") from None

    user = await login_or_register(
        provider=payload.channel,
        provider_uid=provider_uid,
    )
    if user.status != "active":
        raise HTTPException(status_code=401, detail="account unavailable")
    token = issue_session_token(user)
    set_session_cookie(response, token)
    return _me(user)


@router.post("/auth/logout", status_code=204, response_class=Response)
async def logout(response: Response) -> Response:
    clear_session_cookie(response)
    response.status_code = 204
    return response


@router.get("/me", response_model=MeResponse)
async def me(user: CurrentUser) -> MeResponse:
    return _me(user)


async def load_profile(user_id: str) -> dict[str, Any] | None:
    pool = await get_pool()
    async with pool.acquire() as connection:
        row = await connection.fetchrow(
            """
            SELECT profile, updated_at
            FROM user_profiles
            WHERE user_id = $1::uuid
            """,
            user_id,
        )
    return dict(row) if row is not None else None


async def merge_profile(user_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(updates, ensure_ascii=False)
    if len(encoded.encode("utf-8")) > 32_768:
        raise HTTPException(status_code=413, detail="profile update is too large")
    pool = await get_pool()
    async with pool.acquire() as connection:
        row = await connection.fetchrow(
            """
            INSERT INTO user_profiles (user_id, profile, updated_at)
            VALUES ($1::uuid, $2::jsonb, now())
            ON CONFLICT (user_id) DO UPDATE
            SET profile = user_profiles.profile || EXCLUDED.profile,
                updated_at = now()
            RETURNING profile, updated_at
            """,
            user_id,
            encoded,
        )
    return dict(row)


async def list_owned_sessions(
    user_id: str, *, page: int, page_size: int
) -> tuple[list[dict[str, Any]], bool]:
    pool = await get_pool()
    async with pool.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT session_id, status, updated_at
            FROM session_state
            WHERE owner_user_id = $1::uuid
            ORDER BY updated_at DESC, session_id DESC
            LIMIT $2 OFFSET $3
            """,
            user_id,
            page_size + 1,
            (page - 1) * page_size,
        )
    return [dict(row) for row in rows[:page_size]], len(rows) > page_size


@router.get("/me/profile", response_model=ProfileResponse)
async def get_profile(user: CurrentUser) -> ProfileResponse:
    stored = await load_profile(user.user_id)
    if stored is None:
        return ProfileResponse(profile={}, updated_at=user.created_at)
    return ProfileResponse.model_validate(stored)


@router.patch("/me/profile", response_model=ProfileResponse)
async def patch_profile(
    payload: ProfilePatchRequest,
    user: CurrentUser,
) -> ProfileResponse:
    stored = await merge_profile(user.user_id, payload.profile)
    return ProfileResponse.model_validate(stored)


@router.get("/me/sessions", response_model=MeSessionsResponse)
async def get_my_sessions(
    user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=50),
) -> MeSessionsResponse:
    rows, has_more = await list_owned_sessions(
        user.user_id,
        page=page,
        page_size=page_size,
    )
    return MeSessionsResponse(
        sessions=[MeSessionResponse.model_validate(row) for row in rows],
        page=page,
        page_size=page_size,
        has_more=has_more,
    )
