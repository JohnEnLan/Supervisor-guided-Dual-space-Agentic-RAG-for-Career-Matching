"""B5 M0：ADMIN_EMAILS 解析规范（方案 §5.2 逐字：逗号分隔、trim、
casefold、去重；空=空集 fail-closed）。"""

from __future__ import annotations

from app.config import Settings, parse_admin_emails


def test_parse_admin_emails_normalizes_trims_and_dedupes() -> None:
    parsed = parse_admin_emails(
        " Alice@Example.COM , bob@x.cn ,alice@example.com,, ,BOB@X.CN "
    )
    assert parsed == frozenset({"alice@example.com", "bob@x.cn"})


def test_parse_admin_emails_empty_forms_yield_empty_set() -> None:
    assert parse_admin_emails("") == frozenset()
    assert parse_admin_emails("  ,  , ") == frozenset()


def test_admin_emails_setting_defaults_empty() -> None:
    config = Settings(
        _env_file=None,
        database_url="postgresql://test",
        deepseek_api_key="test",
        qwen_api_key="test",
    )
    assert config.admin_emails == ""
    assert parse_admin_emails(config.admin_emails) == frozenset()
