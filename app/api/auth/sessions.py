from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
import secrets
from typing import Any
from urllib.parse import urlsplit
import uuid

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.config import parse_admin_emails, settings
from app.db.pool import get_pool

try:
    import jwt  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover - dependency boundary
    jwt = None


SESSION_COOKIE = "__Host-app_session"
# 答辩局域网演示专用：__Host- 前缀强制 Secure，浏览器只对 localhost 豁免；
# 跨机器 http 访问时需 AUTH_COOKIE_INSECURE=true 切换到无前缀 Cookie。
# production 环境由 validate_runtime_security 拒绝该开关。
INSECURE_SESSION_COOKIE = "app_session"


def session_cookie_name() -> str:
    return INSECURE_SESSION_COOKIE if settings.auth_cookie_insecure else SESSION_COOKIE


def session_cookie_secure() -> bool:
    return not settings.auth_cookie_insecure
JWT_ALGORITHM = "HS256"
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@dataclass(frozen=True)
class AuthedUser:
    user_id: str
    display_name: str | None
    avatar_url: str | None
    status: str
    token_version: int
    is_admin: bool
    created_at: datetime
    last_login_at: datetime | None
    provider: str | None = None

    @classmethod
    def from_row(cls, row: Any) -> "AuthedUser":
        data = dict(row)
        return cls(
            user_id=str(data["user_id"]),
            display_name=data.get("display_name"),
            avatar_url=data.get("avatar_url"),
            status=str(data["status"]),
            token_version=int(data["token_version"]),
            is_admin=bool(data["is_admin"]),
            created_at=data["created_at"],
            last_login_at=data.get("last_login_at"),
        )


def _jwt_library():
    if jwt is None:
        raise RuntimeError("PyJWT is required for authenticated sessions")
    return jwt


def issue_session_token(
    user: AuthedUser,
    *,
    secret_key: str | None = None,
    ttl_days: int | None = None,
    now: datetime | None = None,
    jti: str | None = None,
    idp: str | None = None,
) -> str:
    if idp is not None and (
        not isinstance(idp, str) or idp not in {"email", "phone"}
    ):
        raise ValueError("unsupported identity provider")
    issued_at = now or datetime.now(UTC)
    ttl = ttl_days if ttl_days is not None else settings.auth_session_ttl_days
    payload = {
        "user_id": user.user_id,
        "iat": int(issued_at.timestamp()),
        "exp": int((issued_at + timedelta(days=ttl)).timestamp()),
        "jti": jti or secrets.token_urlsafe(24),
        "token_version": user.token_version,
    }
    if idp is not None:
        payload["idp"] = idp
    return str(
        _jwt_library().encode(
            payload,
            secret_key or settings.auth_secret_key,
            algorithm=JWT_ALGORITHM,
        )
    )


def decode_session_token(
    token: str, *, secret_key: str | None = None
) -> dict[str, Any]:
    library = _jwt_library()
    try:
        payload = library.decode(
            token,
            secret_key or settings.auth_secret_key,
            algorithms=[JWT_ALGORITHM],
            options={
                "require": [
                    "exp",
                    "iat",
                    "jti",
                    "user_id",
                    "token_version",
                ]
            },
        )
        if not isinstance(payload.get("user_id"), str):
            raise library.PyJWTError("invalid user_id")
        if not isinstance(payload.get("token_version"), int):
            raise library.PyJWTError("invalid token_version")
        if "idp" in payload:
            idp = payload["idp"]
            if not isinstance(idp, str) or idp not in {"email", "phone"}:
                raise library.PyJWTError("invalid idp")
    except library.PyJWTError as exc:
        raise ValueError("invalid session token") from exc
    return dict(payload)


def set_session_cookie(
    response: Response,
    token: str,
    *,
    ttl_days: int | None = None,
) -> None:
    ttl = ttl_days if ttl_days is not None else settings.auth_session_ttl_days
    response.set_cookie(
        key=session_cookie_name(),
        value=token,
        max_age=int(timedelta(days=ttl).total_seconds()),
        httponly=True,
        secure=session_cookie_secure(),
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=session_cookie_name(),
        path="/",
        secure=session_cookie_secure(),
        httponly=True,
        samesite="lax",
    )


async def load_user(user_id: str, *, pool: Any | None = None) -> AuthedUser | None:
    database_pool = pool or await get_pool()
    async with database_pool.acquire() as connection:
        row = await connection.fetchrow(
            """
            SELECT user_id, display_name, avatar_url, status,
                   token_version, is_admin, created_at, last_login_at
            FROM users
            WHERE user_id = $1::uuid
            """,
            user_id,
        )
    return AuthedUser.from_row(row) if row is not None else None


async def _identity_user(
    connection: Any, *, provider: str, provider_uid: str
) -> Any | None:
    return await connection.fetchrow(
        """
        SELECT account.user_id, account.display_name, account.avatar_url,
               account.status, account.token_version, account.is_admin,
               account.created_at, account.last_login_at
        FROM user_identities AS identity
        INNER JOIN users AS account ON account.user_id = identity.user_id
        WHERE identity.provider = $1 AND identity.provider_uid = $2
        """,
        provider,
        provider_uid,
    )


async def _complete_login(
    connection: Any,
    user_id: str,
    *,
    provider: str,
) -> AuthedUser:
    if provider == "email":
        identities = await connection.fetch(
            """
            SELECT provider_uid
            FROM user_identities
            WHERE user_id = $1::uuid AND provider = 'email'
            ORDER BY identity_id ASC
            """,
            user_id,
        )
        allowlist = parse_admin_emails(settings.admin_emails)
        is_admin = any(
            str(identity["provider_uid"]).casefold() in allowlist
            for identity in identities
        )
        row = await connection.fetchrow(
            """
            UPDATE users
            SET last_login_at = now(),
                token_version = token_version + CASE
                    WHEN is_admin IS DISTINCT FROM $2::boolean THEN 1
                    ELSE 0
                END,
                is_admin = $2::boolean
            WHERE user_id = $1::uuid
            RETURNING user_id, display_name, avatar_url, status,
                      token_version, is_admin, created_at, last_login_at
            """,
            user_id,
            is_admin,
        )
    else:
        row = await connection.fetchrow(
            """
            UPDATE users
            SET last_login_at = now()
            WHERE user_id = $1::uuid
            RETURNING user_id, display_name, avatar_url, status,
                      token_version, is_admin, created_at, last_login_at
            """,
            user_id,
        )
    return AuthedUser.from_row(row)


async def login_or_register(
    *,
    provider: str,
    provider_uid: str,
    profile: dict[str, Any] | None = None,
    pool: Any | None = None,
) -> AuthedUser:
    if provider not in {"email", "phone"}:
        raise ValueError("unsupported identity provider")
    database_pool = pool or await get_pool()
    async with database_pool.acquire() as connection:
        async with connection.transaction():
            existing = await _identity_user(
                connection,
                provider=provider,
                provider_uid=provider_uid,
            )
            if existing is not None:
                await connection.execute(
                    """
                    UPDATE user_identities
                    SET last_used_at = now()
                    WHERE provider = $1 AND provider_uid = $2
                    """,
                    provider,
                    provider_uid,
                )
                return await _complete_login(
                    connection,
                    str(existing["user_id"]),
                    provider=provider,
                )

            new_user_id = str(uuid.uuid4())
            await connection.execute(
                "INSERT INTO users (user_id) VALUES ($1::uuid)",
                new_user_id,
            )
            inserted = await connection.fetchrow(
                """
                INSERT INTO user_identities (
                    user_id, provider, provider_uid, raw_profile, last_used_at
                )
                VALUES ($1::uuid, $2, $3, $4::jsonb, now())
                ON CONFLICT (provider, provider_uid) DO NOTHING
                RETURNING user_id
                """,
                new_user_id,
                provider,
                provider_uid,
                json.dumps(profile or {}, ensure_ascii=False),
            )
            if inserted is None:
                await connection.execute(
                    "DELETE FROM users WHERE user_id = $1::uuid",
                    new_user_id,
                )
                winner = await _identity_user(
                    connection,
                    provider=provider,
                    provider_uid=provider_uid,
                )
                if winner is None:
                    raise RuntimeError("identity registration race did not resolve")
                return await _complete_login(
                    connection,
                    str(winner["user_id"]),
                    provider=provider,
                )

            await connection.execute(
                """
                INSERT INTO user_profiles (user_id, profile)
                VALUES ($1::uuid, '{}'::jsonb)
                ON CONFLICT (user_id) DO NOTHING
                """,
                new_user_id,
            )
            return await _complete_login(
                connection,
                new_user_id,
                provider=provider,
            )


def _request_origin(request: Request) -> str:
    return f"{request.url.scheme}://{request.url.netloc}".casefold()


def _header_origin(request: Request) -> str | None:
    origin = request.headers.get("origin")
    if origin:
        return origin.rstrip("/").casefold()
    referer = request.headers.get("referer")
    if not referer:
        return None
    parsed = urlsplit(referer)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}".casefold()


class OriginCheckMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if (
            request.method.upper() in _UNSAFE_METHODS
            and _header_origin(request) != _request_origin(request)
        ):
            return JSONResponse(
                status_code=403,
                content={"detail": "origin validation failed"},
            )
        return await call_next(request)
