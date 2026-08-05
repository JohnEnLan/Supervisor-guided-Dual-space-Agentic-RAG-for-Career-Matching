from __future__ import annotations

from email.message import EmailMessage
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_console_provider_is_available_only_outside_production(
    monkeypatch, capsys
) -> None:
    from app.api.auth import providers

    development = SimpleNamespace(
        app_env="development",
        email_otp_provider="console",
        sms_otp_provider="console",
    )
    await providers.send_otp(
        channel="phone",
        target="+447700900123",
        code="123456",
        runtime_settings=development,
    )
    assert "123456" in capsys.readouterr().out

    production = SimpleNamespace(
        app_env="production",
        email_otp_provider="console",
        sms_otp_provider="console",
    )
    with pytest.raises(RuntimeError, match="console"):
        await providers.send_otp(
            channel="email",
            target="person@example.com",
            code="123456",
            runtime_settings=production,
        )


@pytest.mark.asyncio
async def test_smtp_provider_uses_aiosmtplib_without_logging_code(
    monkeypatch, caplog
) -> None:
    from app.api.auth import providers

    sent = {}

    async def fake_send(message: EmailMessage, **kwargs):
        sent["message"] = message
        sent["kwargs"] = kwargs

    monkeypatch.setattr(
        providers.importlib,
        "import_module",
        lambda name: SimpleNamespace(send=fake_send) if name == "aiosmtplib" else None,
    )
    smtp = SimpleNamespace(
        app_env="development",
        email_otp_provider="smtp",
        sms_otp_provider="console",
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_username="user",
        smtp_password="secret",
        smtp_from_email="noreply@example.com",
        smtp_start_tls=True,
    )

    await providers.send_otp(
        channel="email",
        target="person@example.com",
        code="654321",
        runtime_settings=smtp,
    )

    assert sent["message"]["To"] == "person@example.com"
    assert "654321" in sent["message"].get_content()
    assert sent["kwargs"]["hostname"] == "smtp.example.com"
    assert "654321" not in caplog.text

