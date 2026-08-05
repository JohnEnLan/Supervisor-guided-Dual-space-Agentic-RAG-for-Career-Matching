from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import logging
import re
import secrets
from typing import Any, Literal

from app.config import settings
from app.db.pool import get_pool


OtpChannel = Literal["email", "phone"]
OTP_PURPOSE_LOGIN = "login"
OTP_TTL = timedelta(minutes=5)
OTP_CLEANUP_INTERVAL_SECONDS = 300
VERIFY_ATTEMPTS_PER_MINUTE = 10

LOCK_NAMESPACE_GLOBAL = 31_001
LOCK_NAMESPACE_IP = 31_002
LOCK_NAMESPACE_TARGET = 31_003
LOCK_NAMESPACE_VERIFY = 31_004

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_PHONE_RE = re.compile(r"^\+[1-9]\d{7,14}$")
logger = logging.getLogger(__name__)


class OtpError(ValueError):
    pass


class OtpRateLimited(OtpError):
    pass


class OtpInvalid(OtpError):
    pass


class OtpExpired(OtpError):
    pass


@dataclass(frozen=True)
class IssuedOtp:
    challenge_id: int
    normalized_target: str
    code: str
    expires_at: datetime


def normalize_target(channel: OtpChannel, target: str) -> str:
    normalized = target.strip()
    if channel == "email":
        normalized = normalized.lower()
        if len(normalized) > 320 or not _EMAIL_RE.fullmatch(normalized):
            raise ValueError("invalid email address")
        return normalized
    if channel == "phone":
        if not _PHONE_RE.fullmatch(normalized):
            raise ValueError("phone must use E.164 format")
        return normalized
    raise ValueError("unsupported OTP channel")


def generate_otp_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp_code(
    *,
    channel: OtpChannel,
    normalized_target: str,
    purpose: str,
    code: str,
    pepper: str | None = None,
) -> str:
    key = (pepper if pepper is not None else settings.otp_pepper).encode("utf-8")
    message = f"{channel}{normalized_target}{purpose}{code}".encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def _advisory_key(value: str) -> int:
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big", signed=True)


async def _lock_issue_rate_limits(
    connection: Any,
    *,
    channel: OtpChannel,
    normalized_target: str,
    client_ip: str,
) -> None:
    lock_keys = (
        (LOCK_NAMESPACE_GLOBAL, channel),
        (LOCK_NAMESPACE_IP, f"{channel}:{client_ip}"),
        (LOCK_NAMESPACE_TARGET, f"{channel}:{normalized_target}"),
    )
    for namespace, key in lock_keys:
        await connection.execute(
            "SELECT pg_advisory_xact_lock($1, $2)",
            namespace,
            _advisory_key(key),
        )


async def _check_issue_rate_limits(
    connection: Any,
    *,
    channel: OtpChannel,
    normalized_target: str,
    client_ip: str,
) -> None:
    counts = await connection.fetchrow(
        """
        SELECT
          (SELECT count(*) FROM otp_challenges
           WHERE channel = $1 AND normalized_target = $2
             AND created_at >= now() - interval '1 minute') AS target_minute,
          (SELECT count(*) FROM otp_challenges
           WHERE channel = $1 AND normalized_target = $2
             AND created_at >= now() - interval '1 hour') AS target_hour,
          (SELECT count(*) FROM otp_challenges
           WHERE channel = $1 AND normalized_target = $2
             AND created_at >= now() - interval '24 hours') AS target_day,
          (SELECT count(*) FROM otp_challenges
           WHERE channel = $1 AND client_ip = $3::inet
             AND created_at >= now() - interval '1 hour') AS ip_hour,
          (SELECT count(*) FROM otp_challenges
           WHERE channel = $1
             AND created_at >= now() - interval '24 hours') AS global_day
        """,
        channel,
        normalized_target,
        client_ip,
    )
    limits = {
        "target_minute": 1,
        "target_hour": 5,
        "target_day": 10,
        "ip_hour": 20,
        "global_day": 1_000,
    }
    if any(int(counts[name]) >= limit for name, limit in limits.items()):
        raise OtpRateLimited("OTP request rate limit exceeded")


async def issue_otp(
    *,
    channel: OtpChannel,
    target: str,
    client_ip: str,
    purpose: str = OTP_PURPOSE_LOGIN,
    pool: Any | None = None,
    now: datetime | None = None,
    pepper: str | None = None,
) -> IssuedOtp:
    normalized_target = normalize_target(channel, target)
    issued_at = now or datetime.now(UTC)
    expires_at = issued_at + OTP_TTL
    database_pool = pool or await get_pool()
    async with database_pool.acquire() as connection:
        async with connection.transaction():
            await _lock_issue_rate_limits(
                connection,
                channel=channel,
                normalized_target=normalized_target,
                client_ip=client_ip,
            )
            await _check_issue_rate_limits(
                connection,
                channel=channel,
                normalized_target=normalized_target,
                client_ip=client_ip,
            )
            code = generate_otp_code()
            code_hash = hash_otp_code(
                channel=channel,
                normalized_target=normalized_target,
                purpose=purpose,
                code=code,
                pepper=pepper,
            )
            row = await connection.fetchrow(
                """
                INSERT INTO otp_challenges (
                    channel, normalized_target, purpose, code_hash,
                    expires_at, client_ip
                )
                VALUES ($1, $2, $3, $4, $5, $6::inet)
                RETURNING id
                """,
                channel,
                normalized_target,
                purpose,
                code_hash,
                expires_at,
                client_ip,
            )
    return IssuedOtp(
        challenge_id=int(row["id"]),
        normalized_target=normalized_target,
        code=code,
        expires_at=expires_at,
    )


async def verify_otp(
    *,
    channel: OtpChannel,
    target: str,
    code: str,
    purpose: str = OTP_PURPOSE_LOGIN,
    pool: Any | None = None,
    now: datetime | None = None,
    pepper: str | None = None,
) -> str:
    normalized_target = normalize_target(channel, target)
    checked_at = now or datetime.now(UTC)
    database_pool = pool or await get_pool()
    error: OtpError | None = None
    verified = False

    async with database_pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute(
                "SELECT pg_advisory_xact_lock($1, $2)",
                LOCK_NAMESPACE_VERIFY,
                _advisory_key(f"{channel}:{normalized_target}"),
            )
            bucket = await connection.fetchrow(
                """
                INSERT INTO otp_verify_attempts (
                    channel, normalized_target, bucket_start, attempts
                )
                VALUES ($1, $2, date_trunc('minute', now()), 1)
                ON CONFLICT (channel, normalized_target, bucket_start)
                DO UPDATE SET attempts = otp_verify_attempts.attempts + 1
                RETURNING attempts
                """,
                channel,
                normalized_target,
            )
            if int(bucket["attempts"]) > VERIFY_ATTEMPTS_PER_MINUTE:
                error = OtpRateLimited("OTP verification rate limit exceeded")
            else:
                challenge = await connection.fetchrow(
                    """
                    SELECT id, code_hash, attempts, expires_at, consumed_at
                    FROM otp_challenges
                    WHERE channel = $1
                      AND normalized_target = $2
                      AND purpose = $3
                    ORDER BY created_at DESC, id DESC
                    LIMIT 1
                    FOR UPDATE
                    """,
                    channel,
                    normalized_target,
                    purpose,
                )
                if challenge is None:
                    error = OtpInvalid("invalid OTP")
                elif (
                    challenge["consumed_at"] is not None
                    or int(challenge["attempts"]) >= 5
                ):
                    error = OtpInvalid("invalid OTP")
                elif challenge["expires_at"] <= checked_at:
                    error = OtpExpired("OTP expired")
                else:
                    candidate_hash = hash_otp_code(
                        channel=channel,
                        normalized_target=normalized_target,
                        purpose=purpose,
                        code=code,
                        pepper=pepper,
                    )
                    if hmac.compare_digest(
                        str(challenge["code_hash"]), candidate_hash
                    ):
                        consumed = await connection.fetchrow(
                            """
                            UPDATE otp_challenges
                            SET attempts = attempts + 1, consumed_at = now()
                            WHERE id = $1
                              AND consumed_at IS NULL
                              AND expires_at > now()
                              AND attempts < 5
                            RETURNING id
                            """,
                            challenge["id"],
                        )
                        if consumed is None:
                            error = OtpInvalid("invalid OTP")
                        else:
                            verified = True
                    else:
                        await connection.fetchrow(
                            """
                            UPDATE otp_challenges
                            SET attempts = attempts + 1,
                                consumed_at = CASE
                                    WHEN attempts + 1 >= 5 THEN now()
                                    ELSE consumed_at
                                END
                            WHERE id = $1
                              AND consumed_at IS NULL
                              AND attempts < 5
                            RETURNING attempts
                            """,
                            challenge["id"],
                        )
                        error = OtpInvalid("invalid OTP")

    if error is not None:
        raise error
    if not verified:
        raise OtpInvalid("invalid OTP")
    return normalized_target


def _deleted_count(command_tag: str) -> int:
    return int(str(command_tag).rsplit(" ", 1)[-1])


async def invalidate_otp_challenge(
    challenge_id: int,
    *,
    pool: Any | None = None,
) -> bool:
    database_pool = pool or await get_pool()
    async with database_pool.acquire() as connection:
        result = await connection.execute(
            """
            DELETE FROM otp_challenges
            WHERE id = $1
            """,
            challenge_id,
        )
    return _deleted_count(result) == 1


async def cleanup_expired_otp_data(*, pool: Any | None = None) -> dict[str, int]:
    database_pool = pool or await get_pool()
    async with database_pool.acquire() as connection:
        async with connection.transaction():
            challenges = await connection.execute(
                """
                DELETE FROM otp_challenges
                WHERE expires_at < now()
                   OR consumed_at < now() - interval '1 hour'
                """
            )
            attempts = await connection.execute(
                """
                DELETE FROM otp_verify_attempts
                WHERE bucket_start < now() - interval '24 hours'
                """
            )
    return {
        "challenges": _deleted_count(challenges),
        "verify_attempts": _deleted_count(attempts),
    }


async def run_otp_cleanup(*, interval_seconds: float) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await cleanup_expired_otp_data()
        except Exception:
            logger.warning("otp_cleanup_failed", exc_info=True)
