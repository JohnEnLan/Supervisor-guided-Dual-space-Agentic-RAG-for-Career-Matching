from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
from types import SimpleNamespace
import uuid

from fastapi import FastAPI, Response
from fastapi.testclient import TestClient
import pytest


class _TestJwt:
    class PyJWTError(Exception):
        pass

    @staticmethod
    def encode(payload, key, algorithm):
        assert algorithm == "HS256"
        body = base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":")).encode()
        ).rstrip(b"=")
        signature = hmac.new(key.encode(), body, hashlib.sha256).digest()
        return (
            body.decode()
            + "."
            + base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
        )

    @classmethod
    def decode(cls, token, key, algorithms, options):
        assert algorithms == ["HS256"]
        assert set(options["require"]) == {
            "exp",
            "iat",
            "jti",
            "user_id",
            "token_version",
        }
        try:
            encoded, encoded_signature = token.split(".", 1)
            expected = hmac.new(
                key.encode(), encoded.encode(), hashlib.sha256
            ).digest()
            signature = base64.urlsafe_b64decode(
                encoded_signature + "=" * (-len(encoded_signature) % 4)
            )
            if not hmac.compare_digest(expected, signature):
                raise cls.PyJWTError("bad signature")
            payload = json.loads(
                base64.urlsafe_b64decode(
                    encoded + "=" * (-len(encoded) % 4)
                )
            )
        except cls.PyJWTError:
            raise
        except Exception as exc:
            raise cls.PyJWTError("invalid token") from exc
        return payload


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


class _AccountConnection:
    def __init__(self) -> None:
        self.users: dict[str, dict] = {}
        self.identities: dict[tuple[str, str], str] = {}
        self.profiles: set[str] = set()

    def transaction(self):
        return _Transaction()

    async def execute(self, sql: str, *args):
        if "INSERT INTO users" in sql:
            user_id = str(args[0])
            self.users[user_id] = {
                "user_id": user_id,
                "display_name": None,
                "avatar_url": None,
                "status": "active",
                "token_version": 0,
                "is_admin": False,
                "created_at": datetime(2026, 8, 5, tzinfo=UTC),
                "last_login_at": None,
            }
            return "INSERT 0 1"
        if "DELETE FROM users" in sql:
            self.users.pop(str(args[0]), None)
            return "DELETE 1"
        if "INSERT INTO user_profiles" in sql:
            self.profiles.add(str(args[0]))
            return "INSERT 0 1"
        if "UPDATE user_identities" in sql:
            return "UPDATE 1"
        raise AssertionError("unexpected execute: " + " ".join(sql.split()))

    async def fetch(self, sql: str, *args):
        if "FROM user_identities" in sql and "provider = 'email'" in sql:
            user_id = str(args[0])
            return [
                {"provider_uid": provider_uid}
                for (provider, provider_uid), owner_id in self.identities.items()
                if provider == "email" and owner_id == user_id
            ]
        raise AssertionError("unexpected fetch: " + " ".join(sql.split()))

    async def fetchrow(self, sql: str, *args):
        if "FROM user_identities AS identity" in sql:
            user_id = self.identities.get((str(args[0]), str(args[1])))
            return dict(self.users[user_id]) if user_id else None
        if "INSERT INTO user_identities" in sql:
            user_id, provider, provider_uid = map(str, args[:3])
            key = (provider, provider_uid)
            if key in self.identities:
                return None
            self.identities[key] = user_id
            return {"user_id": user_id}
        if "UPDATE users" in sql and "RETURNING" in sql:
            user = self.users[str(args[0])]
            if len(args) == 2:
                recalculated = bool(args[1])
                if user["is_admin"] != recalculated:
                    user["token_version"] += 1
                user["is_admin"] = recalculated
            user["last_login_at"] = datetime(2026, 8, 5, tzinfo=UTC)
            return dict(user)
        raise AssertionError("unexpected fetchrow: " + " ".join(sql.split()))


def _user(*, token_version: int = 0, status: str = "active", is_admin=False):
    from app.api.auth.sessions import AuthedUser

    return AuthedUser(
        user_id="11111111-1111-1111-1111-111111111111",
        display_name=None,
        avatar_url=None,
        status=status,
        token_version=token_version,
        is_admin=is_admin,
        created_at=datetime(2026, 8, 5, tzinfo=UTC),
        last_login_at=None,
    )


def test_session_jwt_claims_sign_verify_and_cookie_contract(monkeypatch) -> None:
    from app.api.auth import sessions

    monkeypatch.setattr(sessions, "jwt", _TestJwt)
    now = datetime(2026, 8, 5, tzinfo=UTC)
    user = _user(token_version=3)
    token = sessions.issue_session_token(
        user,
        secret_key="s" * 32,
        ttl_days=7,
        now=now,
        jti="fixed-jti",
    )
    payload = sessions.decode_session_token(token, secret_key="s" * 32)

    assert payload["user_id"] == user.user_id
    assert payload["token_version"] == 3
    assert payload["jti"] == "fixed-jti"
    assert payload["exp"] - payload["iat"] == int(timedelta(days=7).total_seconds())

    app = FastAPI()

    @app.get("/cookie")
    async def cookie(response: Response):
        sessions.set_session_cookie(response, token, ttl_days=7)
        return {"ok": True}
    with TestClient(app, base_url="https://testserver") as client:
        response = client.get("/cookie")

    header = response.headers["set-cookie"]
    assert header.startswith("__Host-app_session=")
    for attribute in ("HttpOnly", "Secure", "SameSite=lax", "Path=/"):
        assert attribute in header
    assert "Domain=" not in header

    with pytest.raises(ValueError, match="invalid session token"):
        sessions.decode_session_token(token + "tampered", secret_key="s" * 32)


@pytest.mark.asyncio
async def test_login_or_register_is_idempotent_for_same_identity(monkeypatch) -> None:
    from app.api.auth import sessions

    connection = _AccountConnection()
    values = iter(
        [
            uuid.UUID("11111111-1111-1111-1111-111111111111"),
            uuid.UUID("22222222-2222-2222-2222-222222222222"),
        ]
    )
    monkeypatch.setattr(sessions.uuid, "uuid4", lambda: next(values))
    monkeypatch.setattr(sessions.settings, "admin_emails", "")

    first = await sessions.login_or_register(
        provider="email",
        provider_uid="person@example.com",
        pool=_Pool(connection),
    )
    second = await sessions.login_or_register(
        provider="email",
        provider_uid="person@example.com",
        pool=_Pool(connection),
    )

    assert first.user_id == second.user_id
    assert len(connection.users) == 1
    assert connection.profiles == {first.user_id}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "provider_uid", "expected_admin", "expected_version"),
    [
        ("email", "admin@example.com", True, 1),
        ("phone", "+447700900123", False, 0),
    ],
)
async def test_new_account_admin_state_depends_only_on_email_login(
    monkeypatch,
    provider,
    provider_uid,
    expected_admin,
    expected_version,
) -> None:
    from app.api.auth import sessions

    connection = _AccountConnection()
    monkeypatch.setattr(
        sessions.uuid,
        "uuid4",
        lambda: uuid.UUID("11111111-1111-1111-1111-111111111111"),
    )
    monkeypatch.setattr(sessions.settings, "admin_emails", "admin@example.com")

    user = await sessions.login_or_register(
        provider=provider,
        provider_uid=provider_uid,
        pool=_Pool(connection),
    )

    assert user.is_admin is expected_admin
    assert user.token_version == expected_version


@pytest.mark.asyncio
async def test_current_user_rechecks_status_and_token_version(monkeypatch) -> None:
    from fastapi import HTTPException
    from app.api.auth import deps, sessions

    monkeypatch.setattr(sessions, "jwt", _TestJwt)
    user = _user(token_version=2)
    token = sessions.issue_session_token(
        user,
        secret_key="s" * 32,
        ttl_days=7,
    )
    request = SimpleNamespace(cookies={sessions.SESSION_COOKIE: token})
    monkeypatch.setattr(deps.settings, "auth_secret_key", "s" * 32)

    async def active(_user_id: str):
        return user

    monkeypatch.setattr(deps, "load_user", active)
    assert (await deps.optional_current_user(request)).user_id == user.user_id

    async def version_changed(_user_id: str):
        return _user(token_version=3)

    monkeypatch.setattr(deps, "load_user", version_changed)
    with pytest.raises(HTTPException) as error:
        await deps.optional_current_user(request)
    assert error.value.status_code == 401

    async def banned(_user_id: str):
        return _user(token_version=2, status="banned")

    monkeypatch.setattr(deps, "load_user", banned)
    with pytest.raises(HTTPException) as error:
        await deps.optional_current_user(request)
    assert error.value.status_code == 401


def test_origin_middleware_protects_cookie_authenticated_mutations() -> None:
    from app.api.auth.sessions import OriginCheckMiddleware, SESSION_COOKIE

    app = FastAPI()
    app.add_middleware(OriginCheckMiddleware)

    @app.post("/mutate")
    async def mutate():
        return {"ok": True}

    cookie = {"Cookie": f"{SESSION_COOKIE}=token"}
    with TestClient(app, base_url="https://testserver") as client:
        unauthenticated_missing = client.post("/mutate")
        missing = client.post("/mutate", headers=cookie)
        wrong = client.post(
            "/mutate",
            headers={**cookie, "Origin": "https://attacker.example"},
        )
        accepted = client.post(
            "/mutate", headers={**cookie, "Origin": "https://testserver"}
        )

    assert unauthenticated_missing.status_code == 403
    assert missing.status_code == 403
    assert wrong.status_code == 403
    assert accepted.status_code == 200
