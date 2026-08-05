from __future__ import annotations

from email.message import EmailMessage
import importlib
from typing import Any

from app.config import settings


async def send_otp(
    *,
    channel: str,
    target: str,
    code: str,
    runtime_settings: Any = settings,
) -> None:
    if channel == "email":
        provider = runtime_settings.email_otp_provider
        if provider == "smtp":
            await _send_email_smtp(
                target=target,
                code=code,
                runtime_settings=runtime_settings,
            )
            return
        if provider != "console":
            raise RuntimeError("unsupported email OTP provider")
    elif channel == "phone":
        provider = runtime_settings.sms_otp_provider
        if provider != "console":
            raise RuntimeError("unsupported SMS OTP provider")
    else:
        raise ValueError("unsupported OTP channel")

    if runtime_settings.app_env == "production":
        raise RuntimeError("console OTP providers are forbidden in production")
    print(f"[development OTP] {channel} {target}: {code}")


async def _send_email_smtp(
    *, target: str, code: str, runtime_settings: Any
) -> None:
    if not runtime_settings.smtp_host or not runtime_settings.smtp_from_email:
        raise RuntimeError("SMTP_HOST and SMTP_FROM_EMAIL are required")
    message = EmailMessage()
    message["From"] = runtime_settings.smtp_from_email
    message["To"] = target
    message["Subject"] = "Your Career-RAG login code"
    message.set_content(
        f"Your login code is {code}. It expires in 5 minutes."
    )
    aiosmtplib = importlib.import_module("aiosmtplib")
    await aiosmtplib.send(
        message,
        hostname=runtime_settings.smtp_host,
        port=runtime_settings.smtp_port,
        username=runtime_settings.smtp_username,
        password=runtime_settings.smtp_password,
        start_tls=runtime_settings.smtp_start_tls,
    )
