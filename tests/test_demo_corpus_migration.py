from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "app/db/migrations/0006_demo_corpus.sql"
ROLLBACK = ROOT / "app/db/migrations/rollback_0006_demo_corpus.sql"


def test_demo_migration_adds_provenance_columns_and_window_ledger() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    snapshot = (ROOT / "app/db/schema.sql").read_text(encoding="utf-8")

    for sql in (migration, snapshot):
        assert re.search(
            r"demo_synthetic\s+boolean\s+not null\s+default false",
            sql,
            flags=re.IGNORECASE,
        )
        assert re.search(r"country_code\s+text", sql, flags=re.IGNORECASE)
        assert re.search(r"source_tag\s+text", sql, flags=re.IGNORECASE)
        assert re.search(r"source_metadata\s+jsonb", sql, flags=re.IGNORECASE)
        assert "job_import_windows" in sql
        for field in (
            "source_tag",
            "window_number",
            "row_start",
            "row_end",
            "status",
            "embedding_fingerprint",
            "job_count",
            "chunk_count",
            "attempts",
            "error_detail",
        ):
            assert field in sql


def test_demo_migration_is_idempotent_and_has_manual_rollback() -> None:
    migration = MIGRATION.read_text(encoding="utf-8").casefold()
    rollback = ROLLBACK.read_text(encoding="utf-8").casefold()

    assert migration.count("add column if not exists") >= 4
    assert "create table if not exists job_import_windows" in migration
    assert "create index if not exists" in migration
    assert "drop table if exists job_import_windows" in rollback
    for field in ("source_metadata", "source_tag", "country_code", "demo_synthetic"):
        assert f"drop column if exists {field}" in rollback
    assert "delete from schema_migrations" in rollback
    assert "0006_demo_corpus.sql" in rollback
