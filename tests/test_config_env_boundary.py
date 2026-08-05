from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest
from pydantic import ValidationError

from app.config import Settings


ROOT = Path(__file__).resolve().parents[1]


def test_empty_env_file_override_disables_dotenv_loading() -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "CAREER_RAG_ENV_FILE": "",
            "DATABASE_URL": "postgresql://test:test@localhost:5432/test",
            "DEEPSEEK_API_KEY": "sk-test-isolated",
            "QWEN_API_KEY": "sk-test-isolated",
        }
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from app.config import Settings; "
                "assert Settings.model_config.get('env_file') is None"
            ),
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("field_name", ["llm_max_concurrency", "embed_max_concurrency"])
def test_provider_concurrency_must_be_positive(field_name: str) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field_name: 0})


def test_checkpoint_sweep_interval_defaults_and_can_be_disabled() -> None:
    example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert Settings().checkpoint_sweep_interval_seconds == 3600
    assert (
        Settings(checkpoint_sweep_interval_seconds=0)
        .checkpoint_sweep_interval_seconds
        == 0
    )
    assert "CHECKPOINT_SWEEP_INTERVAL_SECONDS=3600" in example


def test_langgraph_defaults_enabled_with_documented_rollback() -> None:
    settings = Settings()
    example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert settings.langgraph_orchestrator_enabled is True
    assert "LANGGRAPH_ORCHESTRATOR_ENABLED=true" in example
    # F7：LANGGRAPH_STRICT_MSGPACK 是无效开关（Settings 无该字段且加载时机太晚），
    # 反序列化安全由 app/api/main.py 的显式类型 allowlist 控制。
    assert "LANGGRAPH_STRICT_MSGPACK" not in example
    assert "false" in example.lower()
    assert "旧" in example or "legacy" in example.lower()


def test_w3_auth_defaults_are_compatibility_safe_and_documented() -> None:
    settings = Settings()
    example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert settings.app_env == "development"
    assert settings.auth_enforced is False
    assert settings.auth_session_ttl_days == 7
    assert settings.email_otp_provider == "console"
    assert settings.sms_otp_provider == "console"
    assert settings.monitoring_admin_mode is False
    for name in (
        "APP_ENV",
        "AUTH_SECRET_KEY",
        "OTP_PEPPER",
        "AUTH_SESSION_TTL_DAYS",
        "EMAIL_OTP_PROVIDER",
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "SMTP_FROM_EMAIL",
        "SMS_OTP_PROVIDER",
        "AUTH_ENFORCED",
        "MONITORING_ADMIN_MODE",
        "DEMO_CORPUS_ENABLED",
    ):
        assert f"{name}=" in example


def _secure_production_settings(**overrides) -> Settings:
    values = {
        "app_env": "production",
        "auth_enforced": True,
        "auth_secret_key": "a" * 32,
        "otp_pepper": "b" * 32,
        "email_otp_provider": "smtp",
        "sms_otp_provider": "disabled",
    }
    values.update(overrides)
    return Settings(**values)


def test_production_refuses_compatibility_mode() -> None:
    from app.config import validate_runtime_security

    compatibility = Settings(app_env="production", auth_enforced=False)
    with pytest.raises(RuntimeError, match="AUTH_ENFORCED"):
        validate_runtime_security(compatibility)


def test_production_accepts_smtp_with_sms_disabled() -> None:
    from app.config import validate_runtime_security

    validate_runtime_security(_secure_production_settings())


@pytest.mark.parametrize(
    "providers",
    [
        {"email_otp_provider": "console", "sms_otp_provider": "disabled"},
        {"email_otp_provider": "smtp", "sms_otp_provider": "console"},
    ],
)
def test_production_refuses_console_for_any_enabled_channel(providers) -> None:
    from app.config import validate_runtime_security

    console = _secure_production_settings(**providers)
    with pytest.raises(RuntimeError, match="console"):
        validate_runtime_security(console)


def test_production_refuses_both_otp_channels_disabled() -> None:
    from app.config import validate_runtime_security

    runtime = _secure_production_settings(
        email_otp_provider="disabled",
        sms_otp_provider="disabled",
    )
    with pytest.raises(RuntimeError, match="at least one OTP"):
        validate_runtime_security(runtime)


def test_non_production_otp_provider_behavior_is_unchanged() -> None:
    from app.config import validate_runtime_security

    validate_runtime_security(Settings(app_env="development"))
    validate_runtime_security(
        Settings(
            app_env="test",
            email_otp_provider="disabled",
            sms_otp_provider="disabled",
        )
    )


def test_production_rejects_documented_development_secrets() -> None:
    from app.config import validate_runtime_security

    runtime = Settings(
        app_env="production",
        auth_enforced=True,
        email_otp_provider="smtp",
    )

    with pytest.raises(RuntimeError, match="AUTH_SECRET_KEY"):
        validate_runtime_security(runtime)


def test_production_requires_explicit_demo_switch_for_active_demo_rows() -> None:
    from app.config import validate_runtime_security

    secure = _secure_production_settings()

    with pytest.raises(RuntimeError, match="DEMO_CORPUS_ENABLED"):
        validate_runtime_security(secure, active_demo_corpus=True)

    object.__setattr__(secure, "demo_corpus_enabled", True)
    validate_runtime_security(secure, active_demo_corpus=True)
