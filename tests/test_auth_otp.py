from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
import re

import pytest


class _Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _Acquire:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _Pool:
    def __init__(self, connection):
        self.connection = connection

    def acquire(self):
        return _Acquire(self.connection)


class _OtpConnection:
    def __init__(self, *, now: datetime) -> None:
        self.now = now
        self.challenges: list[dict] = []
        self.verify_counts: defaultdict[tuple[str, str], int] = defaultdict(int)
        self.rate_counts = {
            "target_minute": 0,
            "target_hour": 0,
            "target_day": 0,
            "ip_hour": 0,
            "global_day": 0,
        }
        self.locks: list[tuple[int, int]] = []
        self.statements: list[str] = []

    def transaction(self):
        return _Transaction()

    async def execute(self, sql: str, *args):
        normalized = " ".join(sql.split())
        self.statements.append(normalized)
        if "pg_advisory_xact_lock" in sql:
            self.locks.append((int(args[0]), int(args[1])))
            return "SELECT 1"
        if "DELETE FROM otp_challenges" in sql and "WHERE id = $1" in sql:
            before = len(self.challenges)
            self.challenges = [
                item for item in self.challenges if item["id"] != int(args[0])
            ]
            return f"DELETE {before - len(self.challenges)}"
        if "DELETE FROM otp_challenges" in sql:
            self.challenges = [
                item
                for item in self.challenges
                if item["expires_at"] >= self.now
                and item.get("consumed_at") is None
            ]
            return "DELETE 2"
        if "DELETE FROM otp_verify_attempts" in sql:
            self.verify_counts.clear()
            return "DELETE 3"
        raise AssertionError(f"unexpected execute: {normalized}")

    async def fetchrow(self, sql: str, *args):
        normalized = " ".join(sql.split())
        self.statements.append(normalized)
        if "AS target_minute" in sql:
            return dict(self.rate_counts)
        if "INSERT INTO otp_challenges" in sql:
            challenge = {
                "id": len(self.challenges) + 1,
                "channel": args[0],
                "normalized_target": args[1],
                "purpose": args[2],
                "code_hash": args[3],
                "expires_at": args[4],
                "client_ip": args[5],
                "attempts": 0,
                "consumed_at": None,
                "created_at": self.now,
            }
            self.challenges.append(challenge)
            return {"id": challenge["id"]}
        if "INSERT INTO otp_verify_attempts" in sql:
            key = (str(args[0]), str(args[1]))
            self.verify_counts[key] += 1
            return {"attempts": self.verify_counts[key]}
        if "FOR UPDATE" in sql:
            channel, target, purpose = map(str, args[:3])
            matching = [
                item
                for item in self.challenges
                if item["channel"] == channel
                and item["normalized_target"] == target
                and item["purpose"] == purpose
            ]
            newest = max(
                matching,
                key=lambda item: (item["created_at"], item["id"]),
                default=None,
            )
            return dict(newest) if newest else None
        if "consumed_at = now()" in sql and "attempts = attempts + 1" in sql:
            challenge = self._challenge(int(args[0]))
            if (
                challenge["consumed_at"] is not None
                or challenge["expires_at"] <= self.now
                or challenge["attempts"] >= 5
            ):
                return None
            challenge["attempts"] += 1
            challenge["consumed_at"] = self.now
            return {"id": challenge["id"]}
        if "CASE WHEN attempts + 1 >= 5" in normalized:
            challenge = self._challenge(int(args[0]))
            if challenge["consumed_at"] is not None or challenge["attempts"] >= 5:
                return None
            challenge["attempts"] += 1
            if challenge["attempts"] >= 5:
                challenge["consumed_at"] = self.now
            return {"attempts": challenge["attempts"]}
        raise AssertionError(f"unexpected fetchrow: {normalized}")

    def _challenge(self, challenge_id: int) -> dict:
        return next(item for item in self.challenges if item["id"] == challenge_id)


def test_otp_hash_uses_exact_contract_and_code_is_six_digit_csprng(
    monkeypatch,
) -> None:
    from app.api.auth import otp

    monkeypatch.setattr(otp.secrets, "randbelow", lambda upper: 42)

    assert otp.generate_otp_code() == "000042"
    assert otp.hash_otp_code(
        channel="email",
        normalized_target="person@example.com",
        purpose="login",
        code="000042",
        pepper="pepper",
    ) == "60e2cfec5853acebf0ecdedc24620ceb37130f62872c509bb1bc118087bf5a2b"


@pytest.mark.parametrize(
    ("channel", "target", "normalized"),
    [
        ("email", " Person@Example.COM ", "person@example.com"),
        ("email", " Straße@Example.COM ", "straße@example.com"),
        ("phone", "+447700900123", "+447700900123"),
    ],
)
def test_otp_targets_have_one_canonical_form(channel, target, normalized) -> None:
    from app.api.auth.otp import normalize_target

    assert normalize_target(channel, target) == normalized


@pytest.mark.asyncio
async def test_issue_otp_locks_global_ip_target_and_never_stores_plaintext(
    monkeypatch,
) -> None:
    from app.api.auth import otp

    now = datetime(2026, 8, 5, tzinfo=UTC)
    connection = _OtpConnection(now=now)
    monkeypatch.setattr(otp, "generate_otp_code", lambda: "123456")

    issued = await otp.issue_otp(
        channel="email",
        target=" Person@Example.COM ",
        client_ip="127.0.0.1",
        pool=_Pool(connection),
        now=now,
        pepper="pepper",
    )

    assert issued.code == "123456"
    assert issued.normalized_target == "person@example.com"
    assert [namespace for namespace, _key in connection.locks] == [
        otp.LOCK_NAMESPACE_GLOBAL,
        otp.LOCK_NAMESPACE_IP,
        otp.LOCK_NAMESPACE_TARGET,
    ]
    stored = connection.challenges[0]
    assert stored["code_hash"] == otp.hash_otp_code(
        channel="email",
        normalized_target="person@example.com",
        purpose="login",
        code="123456",
        pepper="pepper",
    )
    assert "123456" not in repr(stored)
    assert stored["expires_at"] == now + timedelta(minutes=5)


@pytest.mark.asyncio
async def test_issue_otp_rate_limit_is_checked_before_insert() -> None:
    from app.api.auth.otp import OtpRateLimited, issue_otp

    now = datetime(2026, 8, 5, tzinfo=UTC)
    connection = _OtpConnection(now=now)
    connection.rate_counts["target_minute"] = 1

    with pytest.raises(OtpRateLimited):
        await issue_otp(
            channel="phone",
            target="+447700900123",
            client_ip="127.0.0.1",
            pool=_Pool(connection),
            now=now,
            pepper="pepper",
        )

    assert connection.challenges == []


@pytest.mark.asyncio
async def test_expired_otp_requires_resend() -> None:
    from app.api.auth.otp import OtpExpired, hash_otp_code, verify_otp

    now = datetime(2026, 8, 5, tzinfo=UTC)
    connection = _OtpConnection(now=now)
    connection.challenges.append(
        {
            "id": 1,
            "channel": "email",
            "normalized_target": "person@example.com",
            "purpose": "login",
            "code_hash": hash_otp_code(
                channel="email",
                normalized_target="person@example.com",
                purpose="login",
                code="123456",
                pepper="pepper",
            ),
            "attempts": 0,
            "expires_at": now - timedelta(seconds=1),
            "consumed_at": None,
            "created_at": now - timedelta(minutes=6),
        }
    )

    with pytest.raises(OtpExpired):
        await verify_otp(
            channel="email",
            target="person@example.com",
            code="123456",
            pool=_Pool(connection),
            now=now,
            pepper="pepper",
        )


@pytest.mark.asyncio
async def test_fifth_wrong_code_invalidates_challenge() -> None:
    from app.api.auth.otp import OtpInvalid, hash_otp_code, verify_otp

    now = datetime(2026, 8, 5, tzinfo=UTC)
    connection = _OtpConnection(now=now)
    connection.challenges.append(
        {
            "id": 1,
            "channel": "phone",
            "normalized_target": "+447700900123",
            "purpose": "login",
            "code_hash": hash_otp_code(
                channel="phone",
                normalized_target="+447700900123",
                purpose="login",
                code="123456",
                pepper="pepper",
            ),
            "attempts": 0,
            "expires_at": now + timedelta(minutes=5),
            "consumed_at": None,
            "created_at": now,
        }
    )

    for _ in range(5):
        with pytest.raises(OtpInvalid):
            await verify_otp(
                channel="phone",
                target="+447700900123",
                code="000000",
                pool=_Pool(connection),
                now=now,
                pepper="pepper",
            )

    assert connection.challenges[0]["attempts"] == 5
    assert connection.challenges[0]["consumed_at"] == now


@pytest.mark.asyncio
async def test_otp_is_consumed_once_with_conditional_update() -> None:
    from app.api.auth.otp import OtpInvalid, hash_otp_code, verify_otp

    now = datetime(2026, 8, 5, tzinfo=UTC)
    connection = _OtpConnection(now=now)
    connection.challenges.append(
        {
            "id": 1,
            "channel": "email",
            "normalized_target": "person@example.com",
            "purpose": "login",
            "code_hash": hash_otp_code(
                channel="email",
                normalized_target="person@example.com",
                purpose="login",
                code="123456",
                pepper="pepper",
            ),
            "attempts": 0,
            "expires_at": now + timedelta(minutes=5),
            "consumed_at": None,
            "created_at": now,
        }
    )

    assert await verify_otp(
        channel="email",
        target="person@example.com",
        code="123456",
        pool=_Pool(connection),
        now=now,
        pepper="pepper",
    ) == "person@example.com"
    with pytest.raises(OtpInvalid):
        await verify_otp(
            channel="email",
            target="person@example.com",
            code="123456",
            pool=_Pool(connection),
            now=now,
            pepper="pepper",
        )
    consume_sql = next(
        sql for sql in connection.statements if "consumed_at = now()" in sql
    )
    assert re.search(r"WHERE id = \$1.*consumed_at IS NULL", consume_sql)


@pytest.mark.asyncio
async def test_consumed_newest_challenge_never_reactivates_older_code() -> None:
    from app.api.auth.otp import OtpInvalid, hash_otp_code, verify_otp

    now = datetime(2026, 8, 5, tzinfo=UTC)
    connection = _OtpConnection(now=now)
    for challenge_id, code, created_at in (
        (1, "111111", now - timedelta(minutes=1)),
        (2, "222222", now),
    ):
        connection.challenges.append(
            {
                "id": challenge_id,
                "channel": "email",
                "normalized_target": "person@example.com",
                "purpose": "login",
                "code_hash": hash_otp_code(
                    channel="email",
                    normalized_target="person@example.com",
                    purpose="login",
                    code=code,
                    pepper="pepper",
                ),
                "attempts": 0,
                "expires_at": now + timedelta(minutes=5),
                "consumed_at": None,
                "created_at": created_at,
            }
        )

    await verify_otp(
        channel="email",
        target="person@example.com",
        code="222222",
        pool=_Pool(connection),
        now=now,
        pepper="pepper",
    )
    with pytest.raises(OtpInvalid):
        await verify_otp(
            channel="email",
            target="person@example.com",
            code="111111",
            pool=_Pool(connection),
            now=now,
            pepper="pepper",
        )
    assert connection.challenges[0]["consumed_at"] is None


@pytest.mark.asyncio
async def test_failed_delivery_challenge_removal_keeps_prior_code_verifiable() -> None:
    from app.api.auth import otp

    now = datetime(2026, 8, 5, tzinfo=UTC)
    connection = _OtpConnection(now=now)
    for challenge_id, code, created_at in (
        (1, "111111", now - timedelta(minutes=1)),
        (2, "222222", now),
    ):
        connection.challenges.append(
            {
                "id": challenge_id,
                "channel": "email",
                "normalized_target": "person@example.com",
                "purpose": "login",
                "code_hash": otp.hash_otp_code(
                    channel="email",
                    normalized_target="person@example.com",
                    purpose="login",
                    code=code,
                    pepper="pepper",
                ),
                "attempts": 0,
                "expires_at": now + timedelta(minutes=5),
                "consumed_at": None,
                "created_at": created_at,
            }
        )

    removed = await otp.invalidate_otp_challenge(
        2,
        pool=_Pool(connection),
    )

    assert removed is True
    assert [item["id"] for item in connection.challenges] == [1]
    assert await otp.verify_otp(
        channel="email",
        target="person@example.com",
        code="111111",
        pool=_Pool(connection),
        now=now,
        pepper="pepper",
    ) == "person@example.com"


@pytest.mark.asyncio
async def test_cleanup_removes_expired_challenges_and_verify_buckets() -> None:
    from app.api.auth.otp import cleanup_expired_otp_data

    connection = _OtpConnection(now=datetime(2026, 8, 5, tzinfo=UTC))
    deleted = await cleanup_expired_otp_data(pool=_Pool(connection))

    assert deleted == {"challenges": 2, "verify_attempts": 3}
    assert any("DELETE FROM otp_challenges" in sql for sql in connection.statements)
    assert any(
        "DELETE FROM otp_verify_attempts" in sql for sql in connection.statements
    )


@pytest.mark.asyncio
async def test_verify_time_bucket_rejects_eleventh_attempt() -> None:
    from app.api.auth.otp import OtpInvalid, OtpRateLimited, verify_otp

    now = datetime(2026, 8, 5, tzinfo=UTC)
    connection = _OtpConnection(now=now)
    for _ in range(10):
        with pytest.raises(OtpInvalid):
            await verify_otp(
                channel="email",
                target="person@example.com",
                code="123456",
                pool=_Pool(connection),
                now=now,
                pepper="pepper",
            )

    with pytest.raises(OtpRateLimited):
        await verify_otp(
            channel="email",
            target="person@example.com",
            code="123456",
            pool=_Pool(connection),
            now=now,
            pepper="pepper",
        )
