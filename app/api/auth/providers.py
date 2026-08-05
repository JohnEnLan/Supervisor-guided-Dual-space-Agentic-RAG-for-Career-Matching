from __future__ import annotations

from email.message import EmailMessage
import importlib
from typing import Any

from app.config import settings


class OtpChannelDisabled(RuntimeError):
    pass


def otp_provider_for(*, channel: str, runtime_settings: Any = settings) -> str:
    if channel == "email":
        provider = runtime_settings.email_otp_provider
    elif channel == "phone":
        provider = runtime_settings.sms_otp_provider
    else:
        raise ValueError("unsupported OTP channel")
    if provider == "disabled":
        raise OtpChannelDisabled("OTP channel is disabled")
    return str(provider)


async def send_otp(
    *,
    channel: str,
    target: str,
    code: str,
    runtime_settings: Any = settings,
) -> None:
    provider = otp_provider_for(
        channel=channel,
        runtime_settings=runtime_settings,
    )
    if channel == "email":
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
        if provider != "console":
            raise RuntimeError("unsupported SMS OTP provider")

    if runtime_settings.app_env == "production":
        raise RuntimeError("console OTP providers are forbidden in production")
    # flush：开发/冒烟场景 stdout 常被重定向到日志文件（块缓冲），
    # 不刷会让读日志取码的一方拿不到刚签发的验证码。
    print(f"[development OTP] {channel} {target}: {code}", flush=True)


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
