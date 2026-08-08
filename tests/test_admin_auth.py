from __future__ import annotations

import base64
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
import json
from types import SimpleNamespace

from fastapi import HTTPException
import pytest


USER_ID = "11111111-1111-1111-1111-111111111111"
SECRET = "s" * 32


def _user(
    *,
    token_version: int = 0,
    is_admin: bool = False,
    provider: str | None = None,
):
    from app.api.auth.sessions import AuthedUser

    values = {
        "user_id": USER_ID,
        "display_name": None,
        "avatar_url": None,
        "status": "active",
        "token_version": token_version,
        "is_admin": is_admin,
        "created_at": datetime(2026, 8, 9, tzinfo=UTC),
        "last_login_at": None,
    }
    if provider is not None:
        values["provider"] = provider
    return AuthedUser(**values)


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


class _AdminConnection:
    def __init__(self, *, is_admin: bool, emails: list[str]):
        self.rows = [
            {"is_admin": is_admin, "provider_uid": email}
            for email in emails
        ] or [{"is_admin": is_admin, "provider_uid": None}]
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetch(self, sql: str, *args):
        normalized = " ".join(sql.split())
        self.calls.append((normalized, args))
        assert "JOIN user_identities" in normalized
        assert "identity.provider = 'email'" in normalized
        assert args == (USER_ID,)
        return list(self.rows)


def _signed_token_with_idp(idp: object) -> str:
    from app.api.auth import sessions

    now = datetime.now(UTC)
    return str(
        sessions._jwt_library().encode(
            {
                "user_id": USER_ID,
                "iat": int(now.timestamp()),
                "exp": int((now + timedelta(days=1)).timestamp()),
                "jti": "fixed-jti",
                "token_version": 0,
                "idp": idp,
            },
            SECRET,
            algorithm=sessions.JWT_ALGORITHM,
        )
    )


@pytest.mark.parametrize("idp", ["email", "phone"])
def test_session_token_round_trips_valid_idp_without_requiring_it(idp) -> None:
    from app.api.auth import sessions

    token = sessions.issue_session_token(
        _user(),
        idp=idp,
        secret_key=SECRET,
        now=datetime.now(UTC),
    )
    assert sessions.decode_session_token(token, secret_key=SECRET)["idp"] == idp

    legacy = sessions.issue_session_token(
        _user(),
        secret_key=SECRET,
        now=datetime.now(UTC),
    )
    assert "idp" not in sessions.decode_session_token(legacy, secret_key=SECRET)


def test_tampering_idp_invalidates_the_signature() -> None:
    from app.api.auth import sessions

    token = sessions.issue_session_token(
        _user(),
        idp="email",
        secret_key=SECRET,
        now=datetime.now(UTC),
    )
    header, encoded_payload, signature = token.split(".")
    payload = json.loads(
        base64.urlsafe_b64decode(encoded_payload + "=" * (-len(encoded_payload) % 4))
    )
    payload["idp"] = "phone"
    tampered_payload = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).rstrip(b"=").decode()

    with pytest.raises(ValueError, match="invalid session token"):
        sessions.decode_session_token(
            f"{header}.{tampered_payload}.{signature}", secret_key=SECRET
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("idp", ["oauth", "", 7, ["email"], {"idp": "email"}])
async def test_signed_but_invalid_idp_is_a_401(monkeypatch, idp) -> None:
    from app.api.auth import deps, sessions

    token = _signed_token_with_idp(idp)
    request = SimpleNamespace(cookies={sessions.session_cookie_name(): token})
    monkeypatch.setattr(deps.settings, "auth_secret_key", SECRET)

    async def forbidden_load(_user_id: str):
        raise AssertionError("invalid idp must fail before loading the user")

    monkeypatch.setattr(deps, "load_user", forbidden_load)
    with pytest.raises(HTTPException) as error:
        await deps.optional_current_user(request)
    assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_provider_comes_only_from_verified_claim(monkeypatch) -> None:
    from app.api.auth import deps, sessions

    user = _user(is_admin=True)

    async def load(_user_id: str):
        return user

    monkeypatch.setattr(deps, "load_user", load)
    monkeypatch.setattr(
        deps,
        "decode_session_token",
        lambda _token: {
            "user_id": USER_ID,
            "token_version": 0,
            "idp": "phone",
        },
    )
    request = SimpleNamespace(cookies={sessions.session_cookie_name(): "token"})

    authenticated = await deps.optional_current_user(request)

    assert authenticated is not None
    assert authenticated.provider == "phone"


@pytest.mark.asyncio
async def test_legacy_session_is_valid_for_regular_auth_but_not_admin(
    monkeypatch,
) -> None:
    from app.api.auth import deps, sessions

    user = _user(is_admin=True)
    token = sessions.issue_session_token(user, secret_key=SECRET)

    async def load(_user_id: str):
        return user

    async def forbidden_pool():
        raise AssertionError("legacy sessions must not query admin identities")

    monkeypatch.setattr(deps, "load_user", load)
    monkeypatch.setattr(deps, "get_pool", forbidden_pool)
    monkeypatch.setattr(deps.settings, "auth_secret_key", SECRET)
    authenticated = await deps.optional_current_user(
        SimpleNamespace(cookies={sessions.session_cookie_name(): token})
    )

    assert authenticated is not None
    assert authenticated.provider is None
    with pytest.raises(HTTPException) as error:
        await deps.require_admin(authenticated)
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_token_version_mismatch_is_401_before_admin_identity_query(
    monkeypatch,
) -> None:
    from app.api.auth import deps, sessions

    token = sessions.issue_session_token(
        _user(token_version=2),
        idp="email",
        secret_key=SECRET,
    )

    async def load(_user_id: str):
        return _user(token_version=3, is_admin=True)

    async def forbidden_pool():
        raise AssertionError("invalid token version must not query identities")

    monkeypatch.setattr(deps, "load_user", load)
    monkeypatch.setattr(deps, "get_pool", forbidden_pool)
    monkeypatch.setattr(deps.settings, "auth_secret_key", SECRET)
    with pytest.raises(HTTPException) as error:
        await deps.optional_current_user(
            SimpleNamespace(cookies={sessions.session_cookie_name(): token})
        )
    assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_legacy_and_phone_sessions_are_never_admin(monkeypatch) -> None:
    from app.api.auth import deps

    async def forbidden_pool():
        raise AssertionError("non-email sessions must not query admin identities")

    monkeypatch.setattr(deps, "get_pool", forbidden_pool)
    with pytest.raises(HTTPException) as error:
        await deps.require_admin(None)
    assert error.value.status_code == 401
    for user in (_user(is_admin=True), _user(is_admin=True, provider="phone")):
        with pytest.raises(HTTPException) as error:
            await deps.require_admin(user)
        assert error.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("runtime_admin", "emails", "allowlist", "expected_status"),
    [
        (True, ["ADMIN@example.com"], " admin@EXAMPLE.com ", None),
        (False, ["admin@example.com"], "admin@example.com", 403),
        (True, ["removed@example.com"], "admin@example.com", 403),
        (True, ["admin@example.com"], "", 403),
    ],
)
async def test_require_admin_uses_live_flag_and_any_email_in_one_snapshot(
    monkeypatch,
    runtime_admin,
    emails,
    allowlist,
    expected_status,
) -> None:
    from app.api.auth import deps

    connection = _AdminConnection(is_admin=runtime_admin, emails=emails)

    async def get_pool():
        return _Pool(connection)

    monkeypatch.setattr(deps, "get_pool", get_pool)
    monkeypatch.setattr(deps.settings, "admin_emails", allowlist)
    outcome = (
        nullcontext()
        if expected_status is None
        else pytest.raises(HTTPException)
    )
    with outcome as captured:
        await deps.require_admin(_user(is_admin=not runtime_admin, provider="email"))

    if expected_status is not None:
        assert captured.value.status_code == expected_status
    expected_queries = 0 if not allowlist else 1
    assert len(connection.calls) == expected_queries


class _LoginTransaction:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        self.connection.in_transaction = True
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        self.connection.in_transaction = False
        return False


class _LoginConnection:
    def __init__(
        self,
        *,
        provider: str,
        provider_uid: str,
        emails: list[str],
        is_admin: bool,
        token_version: int,
    ) -> None:
        self.user = dict(_user(token_version=token_version, is_admin=is_admin).__dict__)
        self.identities = {(provider, provider_uid): USER_ID}
        for email in emails:
            self.identities[("email", email)] = USER_ID
        self.in_transaction = False
        self.email_reads = 0
        self.update_sql = ""
        self.update_args: tuple[object, ...] = ()
        self.update_was_in_transaction = False

    def transaction(self):
        return _LoginTransaction(self)

    async def execute(self, sql: str, *args):
        if "UPDATE user_identities" in sql:
            return "UPDATE 1"
        raise AssertionError("unexpected execute: " + " ".join(sql.split()))

    async def fetch(self, sql: str, *args):
        normalized = " ".join(sql.split())
        assert "FROM user_identities" in normalized
        assert "provider = 'email'" in normalized
        assert args == (USER_ID,)
        self.email_reads += 1
        return [
            {"provider_uid": uid}
            for (provider, uid), user_id in self.identities.items()
            if provider == "email" and user_id == USER_ID
        ]

    async def fetchrow(self, sql: str, *args):
        normalized = " ".join(sql.split())
        if "FROM user_identities AS identity" in normalized:
            user_id = self.identities.get((str(args[0]), str(args[1])))
            return dict(self.user) if user_id else None
        if "UPDATE users" in normalized and "RETURNING" in normalized:
            self.update_was_in_transaction = self.in_transaction
            self.update_sql = normalized
            self.update_args = args
            if len(args) == 2:
                recalculated = bool(args[1])
                if self.user["is_admin"] != recalculated:
                    self.user["token_version"] += 1
                self.user["is_admin"] = recalculated
            self.user["last_login_at"] = datetime(2026, 8, 9, tzinfo=UTC)
            return dict(self.user)
        raise AssertionError("unexpected fetchrow: " + normalized)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("initial_admin", "allowlist", "expected_admin", "expected_version"),
    [
        (False, "admin@example.com", True, 4),
        (True, "other@example.com", False, 4),
        (False, "other@example.com", False, 3),
        (True, "admin@example.com", True, 3),
    ],
)
async def test_email_login_recomputes_admin_and_bumps_version_only_on_flip(
    monkeypatch,
    initial_admin,
    allowlist,
    expected_admin,
    expected_version,
) -> None:
    from app.api.auth import deps, sessions

    connection = _LoginConnection(
        provider="email",
        provider_uid="admin@example.com",
        emails=["admin@example.com"],
        is_admin=initial_admin,
        token_version=3,
    )
    old_user = _user(token_version=3, is_admin=initial_admin, provider="email")
    old_token = sessions.issue_session_token(
        old_user, idp="email", secret_key=SECRET
    )
    monkeypatch.setattr(sessions.settings, "admin_emails", allowlist)

    logged_in = await sessions.login_or_register(
        provider="email",
        provider_uid="admin@example.com",
        pool=_Pool(connection),
    )

    assert logged_in.is_admin is expected_admin
    assert logged_in.token_version == expected_version
    assert connection.email_reads == 1
    assert connection.update_was_in_transaction is True
    assert "IS DISTINCT FROM" in connection.update_sql
    assert "RETURNING" in connection.update_sql
    assert connection.update_args == (USER_ID, expected_admin)

    async def load(_user_id: str):
        return logged_in

    monkeypatch.setattr(deps, "load_user", load)
    monkeypatch.setattr(deps.settings, "auth_secret_key", SECRET)
    old_request = SimpleNamespace(
        cookies={sessions.session_cookie_name(): old_token}
    )
    if expected_version == 4:
        with pytest.raises(HTTPException) as error:
            await deps.optional_current_user(old_request)
        assert error.value.status_code == 401
    else:
        assert await deps.optional_current_user(old_request) is not None

    new_token = sessions.issue_session_token(
        logged_in, idp="email", secret_key=SECRET
    )
    current = await deps.optional_current_user(
        SimpleNamespace(cookies={sessions.session_cookie_name(): new_token})
    )
    assert current is not None
    assert current.provider == "email"

    admin_connection = _AdminConnection(
        is_admin=expected_admin,
        emails=["admin@example.com"],
    )

    async def admin_pool():
        return _Pool(admin_connection)

    monkeypatch.setattr(deps, "get_pool", admin_pool)
    if expected_admin:
        await deps.require_admin(current)
    else:
        with pytest.raises(HTTPException) as error:
            await deps.require_admin(current)
        assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_email_alias_login_keeps_admin_when_any_identity_is_allowed(
    monkeypatch,
) -> None:
    from app.api.auth import sessions

    connection = _LoginConnection(
        provider="email",
        provider_uid="alias@example.com",
        emails=["alias@example.com", "admin@example.com"],
        is_admin=False,
        token_version=8,
    )
    monkeypatch.setattr(sessions.settings, "admin_emails", "admin@example.com")

    logged_in = await sessions.login_or_register(
        provider="email",
        provider_uid="alias@example.com",
        pool=_Pool(connection),
    )

    assert logged_in.is_admin is True
    assert logged_in.token_version == 9


@pytest.mark.asyncio
async def test_phone_login_does_not_recompute_admin(monkeypatch) -> None:
    from app.api.auth import sessions

    connection = _LoginConnection(
        provider="phone",
        provider_uid="+447700900123",
        emails=["admin@example.com"],
        is_admin=True,
        token_version=5,
    )
    monkeypatch.setattr(sessions.settings, "admin_emails", "")

    logged_in = await sessions.login_or_register(
        provider="phone",
        provider_uid="+447700900123",
        pool=_Pool(connection),
    )

    assert logged_in.is_admin is True
    assert logged_in.token_version == 5
    assert connection.email_reads == 0
    assert connection.update_args == (USER_ID,)
