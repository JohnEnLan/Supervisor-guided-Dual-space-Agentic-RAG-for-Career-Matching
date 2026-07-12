from __future__ import annotations

from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _table_block(sql: str, table_name: str) -> str:
    marker = f"CREATE TABLE IF NOT EXISTS {table_name}"
    start = sql.index(marker)
    end = sql.index(";", start)
    return sql[start:end]


def test_hiring_stage_weights_are_monotonic() -> None:
    from app.memory.case_schema import HiringStage

    ordered = [
        HiringStage.APPLIED,
        HiringStage.SCREEN_PASSED,
        HiringStage.OA_PASSED,
        HiringStage.INTERVIEW,
        HiringStage.OFFER,
        HiringStage.JOINED,
    ]

    assert [stage.weight for stage in ordered] == sorted(
        stage.weight for stage in ordered
    )
    assert len({stage.weight for stage in ordered}) == len(ordered)


def test_dual_space_models_capture_anonymous_outcome_evidence() -> None:
    from app.memory.case_schema import (
        AnonymousResumeCase,
        CaseJobOutcome,
        FinalStatus,
        HiringStage,
        ImplicitEvidence,
    )

    case = AnonymousResumeCase(
        case_id="case-1",
        resume_payload={"skills": ["SQL"], "experience": [{"company": "Acme"}]},
        embedding_text="SQL analyst internship at Acme",
    )
    outcome = CaseJobOutcome(
        outcome_id="outcome-1",
        case_id=case.case_id,
        job_id="job-1",
        company="Acme",
        role_family="data",
        explicit_match_score=0.8,
        highest_stage=HiringStage.INTERVIEW,
        final_status=FinalStatus.ACTIVE,
    )
    evidence = ImplicitEvidence(
        job_id="job-1",
        score=0.7,
        confidence=0.5,
        effective_case_count=2,
        supporting_cases=[{"case_id": case.case_id}],
    )

    assert outcome.highest_stage.weight == 0.7
    assert evidence.supporting_cases == [{"case_id": "case-1"}]


def test_schema_snapshot_and_migration_define_public_implicit_tables() -> None:
    schema = (ROOT / "app/db/schema.sql").read_text(encoding="utf-8")
    migration = (
        ROOT / "app/db/migrations/0001_dual_space_read_model.sql"
    ).read_text(encoding="utf-8")

    for sql in (schema, migration):
        for table in ("anonymous_resume_cases", "case_job_outcomes"):
            block = _table_block(sql, table).casefold()
            assert "user_id" not in block
            assert "email" not in block
            assert "phone" not in block
            assert "external" not in block
        assert re.search(
            r"embedding\s+vector\(1024\)",
            _table_block(sql, "anonymous_resume_cases"),
        )
        assert "job_id" in _table_block(sql, "case_job_outcomes")
        assert "highest_stage" in _table_block(sql, "case_job_outcomes")


def test_migration_discovery_is_numbered_and_sorted() -> None:
    from app.db.migrate import discover_migrations

    paths = discover_migrations(ROOT / "app/db/migrations")

    names = [path.name for path in paths]
    assert names == sorted(names)
    assert names[0] == "0001_dual_space_read_model.sql"


@pytest.mark.asyncio
async def test_migration_runner_records_each_file_once(tmp_path: Path) -> None:
    from app.db.migrate import apply_migrations

    (tmp_path / "0002_second.sql").write_text("SELECT 2;", encoding="utf-8")
    (tmp_path / "0001_first.sql").write_text("SELECT 1;", encoding="utf-8")

    class Transaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    class Connection:
        def __init__(self) -> None:
            self.applied = {"0001_first.sql"}
            self.statements: list[tuple[str, tuple[object, ...]]] = []

        async def execute(self, sql: str, *args: object) -> None:
            self.statements.append((sql, args))
            if sql.startswith("INSERT INTO schema_migrations"):
                self.applied.add(str(args[0]))

        async def fetch(self, sql: str):
            assert "schema_migrations" in sql
            return [{"name": name} for name in sorted(self.applied)]

        def transaction(self) -> Transaction:
            return Transaction()

    class Acquire:
        def __init__(self, connection: Connection) -> None:
            self.connection = connection

        async def __aenter__(self) -> Connection:
            return self.connection

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    class Pool:
        def __init__(self, connection: Connection) -> None:
            self.connection = connection

        def acquire(self) -> Acquire:
            return Acquire(self.connection)

    connection = Connection()
    applied = await apply_migrations(
        pool=Pool(connection), migrations_dir=tmp_path
    )

    assert applied == ["0002_second.sql"]
    assert ("SELECT 2;", ()) in connection.statements
    assert "0002_second.sql" in connection.applied
