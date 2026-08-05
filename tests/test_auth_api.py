from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest


def _app() -> FastAPI:
    from app.api.auth.routes import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return app


def _user(*, user_id: str = "11111111-1111-1111-1111-111111111111"):
    from app.api.auth.sessions import AuthedUser

    return AuthedUser(
        user_id=user_id,
        display_name=None,
        avatar_url=None,
        status="active",
        token_version=0,
        is_admin=False,
        created_at=datetime(2026, 8, 5, tzinfo=UTC),
        last_login_at=datetime(2026, 8, 5, tzinfo=UTC),
    )


def test_otp_request_returns_same_202_for_sent_and_rate_limited(
    monkeypatch,
) -> None:
    from app.api.auth import routes
    from app.api.auth.otp import IssuedOtp, OtpRateLimited

    delivered: list[tuple[str, str, str]] = []

    async def issued(**_kwargs):
        return IssuedOtp(
            challenge_id=1,
            normalized_target="person@example.com",
            code="123456",
            expires_at=datetime(2026, 8, 5, tzinfo=UTC),
        )

    async def send(*, channel: str, target: str, code: str):
        delivered.append((channel, target, code))

    monkeypatch.setattr(routes, "issue_otp", issued)
    monkeypatch.setattr(routes, "send_otp", send)
    with TestClient(_app()) as client:
        sent = client.post(
            "/api/v1/auth/otp/request",
            json={"channel": "email", "target": " Person@Example.COM "},
        )

    async def limited(**_kwargs):
        raise OtpRateLimited("limited")

    monkeypatch.setattr(routes, "issue_otp", limited)
    with TestClient(_app()) as client:
        rate_limited = client.post(
            "/api/v1/auth/otp/request",
            json={"channel": "email", "target": "person@example.com"},
        )

    assert sent.status_code == rate_limited.status_code == 202
    assert sent.json() == rate_limited.json() == {"status": "otp_accepted"}
    assert delivered == [("email", "person@example.com", "123456")]


def test_otp_request_rejects_a_disabled_channel_before_creating_challenge(
    monkeypatch,
) -> None:
    from app.api.auth import routes

    async def forbidden_issue(**_kwargs):
        raise AssertionError("disabled channel must not create an OTP challenge")

    monkeypatch.setattr(
        routes,
        "settings",
        SimpleNamespace(
            email_otp_provider="disabled",
            sms_otp_provider="console",
        ),
        raising=False,
    )
    monkeypatch.setattr(routes, "issue_otp", forbidden_issue)

    with TestClient(_app(), raise_server_exceptions=False) as client:
        response = client.post(
            "/api/v1/auth/otp/request",
            json={"channel": "email", "target": "anyone@example.com"},
        )

    assert response.status_code == 409
    assert response.json() == {"detail": "otp_channel_disabled"}


def test_otp_verify_logs_in_and_sets_host_cookie(monkeypatch) -> None:
    from app.api.auth import routes

    user = _user()

    async def verified(**_kwargs):
        return "person@example.com"

    async def login(**kwargs):
        assert kwargs == {
            "provider": "email",
            "provider_uid": "person@example.com",
        }
        return user

    monkeypatch.setattr(routes, "verify_otp", verified)
    monkeypatch.setattr(routes, "login_or_register", login)
    monkeypatch.setattr(routes, "issue_session_token", lambda _user: "signed.jwt")

    with TestClient(_app(), base_url="https://testserver") as client:
        response = client.post(
            "/api/v1/auth/otp/verify",
            json={
                "channel": "email",
                "target": "person@example.com",
                "code": "123456",
            },
        )

    assert response.status_code == 200
    assert response.json()["user_id"] == user.user_id
    assert response.json()["is_admin"] is False
    assert response.headers["set-cookie"].startswith(
        "__Host-app_session=signed.jwt"
    )


def test_otp_verify_does_not_issue_cookie_for_banned_account(monkeypatch) -> None:
    from app.api.auth import routes

    banned = _user()
    banned = banned.__class__(**{**banned.__dict__, "status": "banned"})

    async def verified(**_kwargs):
        return "person@example.com"

    async def login(**_kwargs):
        return banned

    monkeypatch.setattr(routes, "verify_otp", verified)
    monkeypatch.setattr(routes, "login_or_register", login)
    monkeypatch.setattr(routes, "issue_session_token", lambda _user: "token")
    with TestClient(_app(), raise_server_exceptions=False) as client:
        response = client.post(
            "/api/v1/auth/otp/verify",
            json={
                "channel": "email",
                "target": "person@example.com",
                "code": "123456",
            },
        )

    assert response.status_code == 401
    assert "set-cookie" not in response.headers


def test_otp_delivery_failure_response_and_logs_do_not_expose_target_or_code(
    monkeypatch, caplog
) -> None:
    from app.api.auth import routes
    from app.api.auth.otp import IssuedOtp

    async def issued(**_kwargs):
        return IssuedOtp(
            challenge_id=1,
            normalized_target="private@example.com",
            code="987654",
            expires_at=datetime(2026, 8, 5, tzinfo=UTC),
        )

    async def failed_delivery(**_kwargs):
        raise RuntimeError("private@example.com could not receive 987654")

    invalidated: list[int] = []

    async def invalidate(challenge_id: int):
        invalidated.append(challenge_id)
        return True

    monkeypatch.setattr(routes, "issue_otp", issued)
    monkeypatch.setattr(routes, "send_otp", failed_delivery)
    monkeypatch.setattr(
        routes,
        "invalidate_otp_challenge",
        invalidate,
        raising=False,
    )
    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/auth/otp/request",
            json={"channel": "email", "target": "private@example.com"},
        )

    assert response.status_code == 202
    assert invalidated == [1]
    assert "private@example.com" not in caplog.text
    assert "987654" not in caplog.text


@pytest.mark.parametrize(
    ("error_type", "status_code"),
    [("invalid", 401), ("expired", 410), ("limited", 429)],
)
def test_otp_verify_maps_lifecycle_failures(monkeypatch, error_type, status_code):
    from app.api.auth import routes
    from app.api.auth.otp import OtpExpired, OtpInvalid, OtpRateLimited

    errors = {
        "invalid": OtpInvalid("invalid"),
        "expired": OtpExpired("expired"),
        "limited": OtpRateLimited("limited"),
    }

    async def rejected(**_kwargs):
        raise errors[error_type]

    monkeypatch.setattr(routes, "verify_otp", rejected)
    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/auth/otp/verify",
            json={
                "channel": "phone",
                "target": "+447700900123",
                "code": "123456",
            },
        )

    assert response.status_code == status_code


def test_logout_clears_host_cookie() -> None:
    with TestClient(_app(), base_url="https://testserver") as client:
        response = client.post("/api/v1/auth/logout")

    assert response.status_code == 204
    header = response.headers["set-cookie"]
    assert header.startswith('__Host-app_session=""')
    assert "Max-Age=0" in header
    assert "Path=/" in header


def test_me_profile_and_session_list_are_bound_to_current_user(monkeypatch) -> None:
    from app.api.auth import routes
    from app.api.auth.deps import current_user

    user = _user()
    now = datetime(2026, 8, 5, tzinfo=UTC)
    calls = []

    async def profile(user_id: str):
        assert user_id == user.user_id
        return {"profile": {"role": "analyst"}, "updated_at": now}

    async def patch(user_id: str, updates: dict):
        calls.append((user_id, updates))
        return {"profile": {"role": "engineer"}, "updated_at": now}

    async def sessions(user_id: str, *, page: int, page_size: int):
        assert (user_id, page, page_size) == (user.user_id, 2, 50)
        return (
            [
                {
                    "session_id": "session-2",
                    "status": "resume_ready",
                    "updated_at": now,
                }
            ],
            False,
        )

    monkeypatch.setattr(routes, "load_profile", profile)
    monkeypatch.setattr(routes, "merge_profile", patch)
    monkeypatch.setattr(routes, "list_owned_sessions", sessions)
    app = _app()
    app.dependency_overrides[current_user] = lambda: user

    with TestClient(app) as client:
        me = client.get("/api/v1/me")
        current_profile = client.get("/api/v1/me/profile")
        updated_profile = client.patch(
            "/api/v1/me/profile", json={"profile": {"role": "engineer"}}
        )
        listed = client.get(
            "/api/v1/me/sessions?page=2&page_size=50"
        )
        oversized = client.get(
            "/api/v1/me/sessions?page=1&page_size=51"
        )

    assert me.status_code == 200 and me.json()["user_id"] == user.user_id
    assert current_profile.json()["profile"] == {"role": "analyst"}
    assert updated_profile.json()["profile"] == {"role": "engineer"}
    assert calls == [(user.user_id, {"role": "engineer"})]
    assert listed.json() == {
        "sessions": [
            {
                "session_id": "session-2",
                "status": "resume_ready",
                "updated_at": now.isoformat().replace("+00:00", "Z"),
            }
        ],
        "page": 2,
        "page_size": 50,
        "has_more": False,
    }
    assert oversized.status_code == 422


def test_insecure_demo_cookie_switch_changes_name_and_secure_flag(monkeypatch):
    # A.3：跨机器 http 演示时 __Host-（强制 Secure）在非 localhost 会被浏览器拒收
    from fastapi.responses import Response

    from app.api.auth import sessions as auth_sessions
    from app.config import settings as runtime_settings

    assert auth_sessions.session_cookie_name() == "__Host-app_session"
    assert auth_sessions.session_cookie_secure() is True

    monkeypatch.setattr(runtime_settings, "auth_cookie_insecure", True)
    assert auth_sessions.session_cookie_name() == "app_session"
    assert auth_sessions.session_cookie_secure() is False

    response = Response()
    auth_sessions.set_session_cookie(response, "token-value", ttl_days=1)
    header = response.headers["set-cookie"]
    assert header.startswith("app_session=")
    assert "Secure" not in header
    assert "HttpOnly" in header


def test_production_refuses_insecure_cookie_switch():
    from app.config import validate_runtime_security, Settings

    runtime = Settings(
        app_env="production",
        auth_enforced=True,
        auth_secret_key="a" * 32,
        otp_pepper="b" * 32,
        email_otp_provider="smtp",
        sms_otp_provider="disabled",
        smtp_host="smtp.example.com",
        smtp_from_email="noreply@example.com",
        auth_cookie_insecure=True,
    )
    import pytest as _pytest

    with _pytest.raises(RuntimeError, match="AUTH_COOKIE_INSECURE"):
        validate_runtime_security(runtime)
