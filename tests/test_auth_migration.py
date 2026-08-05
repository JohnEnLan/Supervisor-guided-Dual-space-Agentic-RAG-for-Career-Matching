from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "app/db/migrations/0005_auth_accounts.sql"


def _table(sql: str, name: str) -> str:
    match = re.search(
        rf"CREATE TABLE(?: IF NOT EXISTS)? {name}\s*\((.*?)\);",
        sql,
        flags=re.DOTALL | re.IGNORECASE,
    )
    assert match is not None, f"missing table {name}"
    return match.group(1).casefold()


def test_auth_migration_defines_accounts_identities_and_profiles() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    users = _table(sql, "users")
    assert "token_version" in users
    assert "is_admin" in users
    assert "check (status in ('active', 'banned', 'deleted'))" in users

    identities = _table(sql, "user_identities")
    assert "references users(user_id)" in identities
    assert "check (provider in ('email', 'phone'))" in identities
    assert "unique (provider, provider_uid)" in identities

    profiles = _table(sql, "user_profiles")
    assert "user_id" in profiles and "primary key" in profiles
    assert "profile" in profiles and "jsonb" in profiles
    assert "updated_at" in profiles


def test_auth_migration_defines_otp_lifecycle_and_rate_limit_indexes() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    challenges = _table(sql, "otp_challenges")

    for field in (
        "channel",
        "normalized_target",
        "purpose",
        "code_hash",
        "attempts",
        "expires_at",
        "consumed_at",
        "client_ip",
        "created_at",
    ):
        assert field in challenges
    assert "check (channel in ('email', 'phone'))" in challenges
    assert "client_ip" in challenges and "inet" in challenges
    assert re.search(
        r"on otp_challenges\s*\(channel, normalized_target, created_at desc\)",
        sql,
        flags=re.IGNORECASE,
    )
    assert re.search(
        r"on otp_challenges\s*\(client_ip, created_at desc\)",
        sql,
        flags=re.IGNORECASE,
    )

    verify_attempts = _table(sql, "otp_verify_attempts")
    assert "channel" in verify_attempts
    assert "normalized_target" in verify_attempts
    assert "bucket_start" in verify_attempts
    assert "attempts" in verify_attempts


def test_auth_migration_adds_nullable_session_owner_and_snapshot_matches() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    snapshot = (ROOT / "app/db/schema.sql").read_text(encoding="utf-8")

    for sql in (migration, snapshot):
        assert re.search(
            r"owner_user_id\s+uuid(?:\s+references users\(user_id\))?",
            sql,
            flags=re.IGNORECASE,
        )
        assert "idx_session_owner_updated" in sql


def test_manual_rollback_removes_migration_ledger_for_reapply() -> None:
    rollback = (
        ROOT / "app/db/migrations/rollback_0005_auth_accounts.sql"
    ).read_text(encoding="utf-8")

    assert re.search(
        r"DELETE FROM schema_migrations\s+WHERE name\s*=\s*'0005_auth_accounts.sql'",
        rollback,
        flags=re.IGNORECASE,
    )
