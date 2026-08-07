from __future__ import annotations

import json
import asyncio
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError


class _Acquire:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Pool:
    def __init__(self, connection):
        self.connection = connection

    def acquire(self):
        return _Acquire(self.connection)


class _Transaction:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _old_state_json() -> str:
    return json.dumps(
        {
            "session_id": "session-1",
            "user_id": "user-1",
            "resume_state": {
                "skills": ["Python"],
                "normalized_base_resume": "Legacy resume",
            },
        }
    )


def _api_app() -> FastAPI:
    from app.api.v1.router import router

    app = FastAPI()
    app.include_router(router)
    return app


def test_feature_a_state_contract_defaults_are_backward_compatible() -> None:
    from app.state.schema import SharedState

    state = SharedState.model_validate_json(_old_state_json())

    assert state.resume_state.quality_issues_struct == []
    assert state.resume_state.clarification_targets == []
    assert state.resume_state.pending_clarification_question is None
    assert state.resume_state.questions_used == 0
    assert state.resume_state.clarifications == []
    assert state.resume_state.clarification_evidence_spans == []
    assert state.coach_reservations == []


def test_evidence_span_accepts_only_resume_and_user_clarification_sources() -> None:
    from app.normalization.resume_intake import EvidenceSpan

    assert (
        EvidenceSpan(
            span_id="C001",
            text="I led the migration.",
            source="user_clarification",
        ).source
        == "user_clarification"
    )
    with pytest.raises(ValidationError):
        EvidenceSpan(span_id="X001", text="unknown", source="parallel_origin")


def test_feature_switch_defaults_and_limits() -> None:
    from app.config import Settings

    config = Settings(
        _env_file=None,
        database_url="postgresql://test",
        deepseek_api_key="test",
        qwen_api_key="test",
    )

    assert config.resume_clarify_enabled is False
    assert config.resume_clarify_max == 2
    assert config.consult_coach_enabled is False
    assert config.consult_coach_max == 3

    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            database_url="postgresql://test",
            deepseek_api_key="test",
            qwen_api_key="test",
            resume_clarify_max=0,
        )
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            database_url="postgresql://test",
            deepseek_api_key="test",
            qwen_api_key="test",
            resume_clarify_max=6,
        )
    for invalid_coach_max in (0, 6):
        with pytest.raises(ValidationError):
            Settings(
                _env_file=None,
                database_url="postgresql://test",
                deepseek_api_key="test",
                qwen_api_key="test",
                consult_coach_max=invalid_coach_max,
            )


def test_schema_and_migration_add_only_resume_upload_generation() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    schema = (root / "app/db/schema.sql").read_text(encoding="utf-8")
    migration = root / "app/db/migrations/0008_resume_upload_generation.sql"

    assert migration.exists()
    migration_sql = migration.read_text(encoding="utf-8")
    expected = "resume_upload_generation BIGINT NOT NULL DEFAULT 0"
    assert expected in schema
    assert expected in migration_sql
    assert migration_sql.upper().count("ADD COLUMN") == 1
    assert "quality_issues_struct" not in migration_sql
    assert "clarification_targets" not in migration_sql
    assert "coach_reservations" not in migration_sql


@pytest.mark.asyncio
async def test_load_consult_context_reads_state_and_resume_metadata_once(
    monkeypatch,
) -> None:
    from app.db import state_store

    calls = []

    class Connection:
        async def fetchrow(self, sql, *args):
            calls.append((sql, args))
            return {
                "state": _old_state_json(),
                "status": "resume_ready",
                "resume_version": 4,
                "confirmed_resume_version": 4,
                "resume_upload_generation": 7,
            }

    async def fake_get_pool():
        return _Pool(Connection())

    monkeypatch.setattr(state_store, "get_pool", fake_get_pool)

    context = await state_store.load_consult_context("session-1")

    assert context is not None
    assert context.state.resume_state.skills == ["Python"]
    assert context.status == "resume_ready"
    assert context.resume_version == 4
    assert context.confirmed_resume_version == 4
    assert context.resume_upload_generation == 7
    assert len(calls) == 1
    assert "resume_version" in calls[0][0]
    assert "confirmed_resume_version" in calls[0][0]
    assert "resume_upload_generation" in calls[0][0]


@pytest.mark.asyncio
async def test_mutate_state_atomically_exposes_locked_version_and_generation(
    monkeypatch,
) -> None:
    from app.db import state_store

    calls = []

    class Connection:
        def transaction(self):
            return _Transaction()

        async def fetchrow(self, sql, *args):
            calls.append(("fetchrow", sql, args))
            return {
                "state": _old_state_json(),
                "status": "resume_ready",
                "resume_version": 3,
                "confirmed_resume_version": 3,
                "resume_upload_generation": 9,
            }

        async def execute(self, sql, *args):
            calls.append(("execute", sql, args))

    async def fake_get_pool():
        return _Pool(Connection())

    monkeypatch.setattr(state_store, "get_pool", fake_get_pool)

    def mutate(state, resume_version, resume_upload_generation):
        state.career_state.current_goal = ["Data analyst"]
        return resume_version, resume_upload_generation

    result = await state_store.mutate_state_atomically(
        session_id="session-1",
        mutator=mutate,
    )

    assert result == (3, 9)
    assert "FOR UPDATE" in calls[0][1]


@pytest.mark.asyncio
async def test_accept_resume_upload_is_one_update_without_state_rewrite(
    monkeypatch,
) -> None:
    from app.db import state_store

    calls = []

    class Connection:
        async def fetchrow(self, sql, *args):
            calls.append((sql, args))
            return {
                "user_id": "user-1",
                "resume_upload_generation": 5,
            }

    async def fake_get_pool():
        return _Pool(Connection())

    monkeypatch.setattr(state_store, "get_pool", fake_get_pool)

    accepted = await state_store.accept_resume_upload(session_id="session-1")

    assert accepted == {
        "user_id": "user-1",
        "resume_upload_generation": 5,
    }
    assert len(calls) == 1
    sql = calls[0][0]
    assert "UPDATE session_state" in sql
    assert "status = 'resume_queued'" in sql
    assert "resume_upload_generation = resume_upload_generation + 1" in sql
    assert "confirmed_resume_version = NULL" in sql
    assert "resume_confirmed_at = NULL" in sql
    assert "state =" not in sql
    assert "version = version + 1" not in sql


@pytest.mark.asyncio
async def test_stale_normalization_success_is_a_quiet_noop(monkeypatch) -> None:
    from app.db import state_store
    from app.state.schema import ResumeState

    class Connection:
        def transaction(self):
            return _Transaction()

        async def fetchrow(self, sql, *args):
            if "FOR UPDATE" in sql:
                return {
                    "state": _old_state_json(),
                    "status": "resume_queued",
                    "resume_version": 1,
                    "confirmed_resume_version": None,
                    "resume_upload_generation": 2,
                }
            raise AssertionError("stale success must not update the row")

    async def fake_get_pool():
        return _Pool(Connection())

    monkeypatch.setattr(state_store, "get_pool", fake_get_pool)

    result = await state_store.save_normalized_resume(
        session_id="session-1",
        resume_state=ResumeState(skills=["stale"]),
        content_hash="stale-hash",
        expected_generation=1,
    )

    assert result is None


@pytest.mark.asyncio
async def test_stale_normalization_failure_is_a_quiet_noop(monkeypatch) -> None:
    from app.db import state_store

    calls = []

    class Connection:
        async def execute(self, sql, *args):
            calls.append((sql, args))
            return "UPDATE 0"

    async def fake_get_pool():
        return _Pool(Connection())

    monkeypatch.setattr(state_store, "get_pool", fake_get_pool)

    changed = await state_store.mark_resume_error(
        session_id="session-1",
        expected_generation=1,
    )

    assert changed is False
    assert len(calls) == 1
    assert "resume_upload_generation = $2" in calls[0][0]


def test_feature_a_public_dto_contract_is_additive_and_preview_is_frozen() -> None:
    from app.api.v1.schemas import (
        ClarificationProgress,
        ConsultResponse,
        ConsultStateResponse,
        ConsultTranscriptEntry,
        ResumeConfirmRequest,
        ResumeLifecycleConflictResponse,
        ResumePreviewResponse,
    )

    request = ResumeConfirmRequest()
    assert request.expected_resume_version is None
    assert ResumeConfirmRequest(expected_resume_version=3).expected_resume_version == 3
    assert ResumeConfirmRequest(expected_resume_version=0).expected_resume_version == 0
    assert ClarificationProgress().model_dump() == {
        "answered": 0,
        "skipped": 0,
        "total": 0,
        "questions_used": 0,
    }
    assert ResumeLifecycleConflictResponse(detail="resume_changed").detail == (
        "resume_changed"
    )
    assert ResumeLifecycleConflictResponse(detail="resume_processing").detail == (
        "resume_processing"
    )
    assert ResumeLifecycleConflictResponse(detail="resume_error").detail == (
        "resume_error"
    )
    assert (
        ConsultTranscriptEntry(
            round=1,
            user_message="补充说明",
            assistant_reply="谢谢补充。",
            next_question="还有量化结果吗？",
            phase="resume_clarify",
        ).phase
        == "resume_clarify"
    )

    response = ConsultResponse(
        assistant_reply="收到。",
        next_question="下一步想做什么？",
        phase="resume_clarify",
        completeness=0.5,
        can_finalize=False,
        round=1,
        profile_draft={},
    )
    state_response = ConsultStateResponse(
        profile_draft={},
        round=0,
        phase="resume_clarify",
        completeness=0,
        can_finalize=False,
    )
    assert response.clarification_progress.total == 0
    assert state_response.clarification_progress.questions_used == 0
    assert "resume_upload_generation" not in ResumePreviewResponse.model_fields


def test_upload_acceptance_passes_internal_generation_to_background_task(
    monkeypatch,
) -> None:
    from app.api.v1 import sessions

    calls = []

    async def persist(_session_id, _file):
        return Path("queued-resume.txt")

    async def accept(*, session_id):
        assert session_id == "session-1"
        return {"user_id": "user-1", "resume_upload_generation": 6}

    async def normalize(**kwargs):
        calls.append(kwargs)

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("upload acceptance must not load or rewrite state JSON")

    monkeypatch.setattr(sessions, "persist_upload", persist)
    monkeypatch.setattr(sessions, "accept_resume_upload", accept, raising=False)
    monkeypatch.setattr(sessions, "_normalize_resume", normalize)
    monkeypatch.setattr(sessions, "load_state", forbidden)
    monkeypatch.setattr(sessions, "save_state", forbidden)

    with TestClient(_api_app()) as client:
        response = client.post(
            "/api/v1/sessions/session-1/resume",
            files={"file": ("resume.txt", b"Python", "text/plain")},
        )

    assert response.status_code == 202
    assert response.json() == {
        "session_id": "session-1",
        "status": "resume_queued",
    }
    assert calls == [
        {
            "session_id": "session-1",
            "user_id": "user-1",
            "resume_path": Path("queued-resume.txt"),
            "expected_generation": 6,
        }
    ]


@pytest.mark.parametrize(
    ("status", "detail"),
    [
        ("resume_queued", "resume_processing"),
        ("resume_error", "resume_error"),
    ],
)
def test_preview_does_not_expose_stale_resume_for_incomplete_generation(
    monkeypatch,
    status,
    detail,
) -> None:
    from app.api.v1 import sessions
    from app.db.state_store import ConsultContext
    from app.state.schema import SharedState

    async def context(_session_id):
        return ConsultContext(
            state=SharedState(
                session_id="session-1",
                user_id="user-1",
                resume_state={"skills": ["old-version"]},
            ),
            status=status,
            resume_version=1,
            confirmed_resume_version=None,
            resume_upload_generation=2,
        )

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("preview must use the single-snapshot context")

    monkeypatch.setattr(sessions, "load_consult_context", context, raising=False)
    monkeypatch.setattr(sessions, "load_state", forbidden)
    monkeypatch.setattr(sessions, "get_resume_metadata", forbidden)

    with TestClient(_api_app()) as client:
        response = client.get("/api/v1/sessions/session-1/resume-preview")

    assert response.status_code == 409
    assert response.json() == {"detail": detail}
    assert "old-version" not in response.text


def test_preview_reports_resume_missing_for_never_uploaded_session(
    monkeypatch,
) -> None:
    """审计二轮阻断回归钉死：从未上传的新会话必须回 resume_missing，
    与"归一化中"可区分——否则前端会隐藏上传入口造成新用户卡死。"""
    from app.api.v1 import sessions
    from app.db.state_store import ConsultContext
    from app.state.schema import SharedState

    async def context(_session_id):
        return ConsultContext(
            state=SharedState(session_id="session-1", user_id="user-1"),
            status="awaiting_resume",
            resume_version=0,
            confirmed_resume_version=None,
            resume_upload_generation=0,
        )

    monkeypatch.setattr(sessions, "load_consult_context", context, raising=False)

    with TestClient(_api_app()) as client:
        response = client.get("/api/v1/sessions/session-1/resume-preview")

    assert response.status_code == 409
    assert response.json() == {"detail": "resume_missing"}


def test_confirm_checks_expected_version_only_when_clarification_is_enabled(
    monkeypatch,
) -> None:
    from app.api.v1 import sessions

    captured = []

    async def confirm(*, session_id, expected_resume_version):
        captured.append((session_id, expected_resume_version))
        return {
            "resume_version": 2,
            "resume_confirmed_at": None,
        }

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("confirm preconditions must be checked under one lock")

    monkeypatch.setattr(sessions, "confirm_resume", confirm)
    monkeypatch.setattr(sessions, "get_resume_metadata", forbidden)
    monkeypatch.setattr(sessions.settings, "resume_clarify_enabled", False)

    with TestClient(_api_app()) as client:
        response = client.post(
            "/api/v1/sessions/session-1/resume-confirm",
            json={"expected_resume_version": 0},
        )

    assert response.status_code == 200
    assert captured == [("session-1", None)]


@pytest.mark.parametrize("body", [None, {}])
def test_enabled_confirm_requires_expected_resume_version(
    monkeypatch,
    body,
) -> None:
    from app.api.v1 import sessions

    calls = 0

    async def confirm(**_kwargs):
        nonlocal calls
        calls += 1
        return {"resume_version": 2, "resume_confirmed_at": None}

    monkeypatch.setattr(sessions, "confirm_resume", confirm)
    monkeypatch.setattr(sessions.settings, "resume_clarify_enabled", True)

    with TestClient(_api_app()) as client:
        url = "/api/v1/sessions/session-1/resume-confirm"
        response = client.post(url) if body is None else client.post(url, json=body)

    assert response.status_code == 422
    assert response.json() == {"detail": "expected_resume_version_required"}
    assert calls == 0


def test_confirm_returns_resume_changed_for_enabled_stale_client_version(
    monkeypatch,
) -> None:
    from app.api.v1 import sessions
    from app.db.state_store import ResumeLifecycleConflict

    async def confirm(*, session_id, expected_resume_version):
        assert session_id == "session-1"
        assert expected_resume_version == 1
        raise ResumeLifecycleConflict("resume_changed")

    monkeypatch.setattr(sessions, "confirm_resume", confirm)
    monkeypatch.setattr(sessions.settings, "resume_clarify_enabled", True)

    with TestClient(_api_app()) as client:
        response = client.post(
            "/api/v1/sessions/session-1/resume-confirm",
            json={"expected_resume_version": 1},
        )

    assert response.status_code == 409
    assert response.json() == {"detail": "resume_changed"}


@pytest.mark.parametrize("detail", ["resume_processing", "resume_error"])
def test_confirm_returns_stable_lifecycle_detail(monkeypatch, detail) -> None:
    from app.api.v1 import sessions
    from app.db.state_store import ResumeLifecycleConflict

    async def confirm(**_kwargs):
        raise ResumeLifecycleConflict(detail)

    monkeypatch.setattr(sessions, "confirm_resume", confirm)

    with TestClient(_api_app()) as client:
        response = client.post(
            "/api/v1/sessions/session-1/resume-confirm",
            json={"expected_resume_version": 1},
        )

    assert response.status_code == 409
    assert response.json() == {"detail": detail}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "detail"),
    [
        ("resume_queued", "resume_processing"),
        ("resume_error", "resume_error"),
    ],
)
async def test_confirm_store_rejects_real_queued_and_error_states(
    monkeypatch,
    status,
    detail,
) -> None:
    from app.db import state_store

    class Connection:
        def __init__(self):
            self.updated = False

        def transaction(self):
            return _Transaction()

        async def fetchrow(self, sql, *_args):
            if "FOR UPDATE" in sql:
                return {
                    "state": _old_state_json(),
                    "status": status,
                    "resume_version": 1,
                    "confirmed_resume_version": None,
                    "resume_upload_generation": 2,
                }
            self.updated = True
            raise AssertionError("invalid lifecycle state must not confirm")

    connection = Connection()

    async def fake_get_pool():
        return _Pool(connection)

    monkeypatch.setattr(state_store, "get_pool", fake_get_pool)

    with pytest.raises(state_store.ResumeLifecycleConflict) as conflict:
        await state_store.confirm_resume(
            session_id="session-1",
            expected_resume_version=1,
        )

    assert conflict.value.detail == detail
    assert connection.updated is False


def test_enabled_consult_cas_rejects_upload_accepted_during_llm_wait(
    monkeypatch,
) -> None:
    from app.api.v1 import sessions
    from app.db.state_store import ConsultContext
    from app.state.schema import SharedState

    initial = SharedState(session_id="session-1", user_id="user-1")
    initial.career_state.current_goal = ["Data analyst"]
    initial.career_state.hard_constraints = {
        "locations": ["Birmingham"],
        "visa_sponsorship_required": True,
    }
    initial.career_state.soft_preferences = {"industries": ["Fintech"]}

    async def context(_session_id):
        return ConsultContext(
            state=initial,
            status="resume_ready",
            resume_version=1,
            confirmed_resume_version=1,
            resume_upload_generation=1,
        )

    async def run(working, **_kwargs):
        working.career_state.consult_rounds_used = 1
        working.career_state.consult_transcript.append({"round": 1})
        return SimpleNamespace(
            assistant_reply="收到。",
            next_question="还有偏好吗？",
            phase="deepen",
            completeness=1.0,
            can_finalize=True,
            round=1,
            profile_draft={},
        )

    rejected_candidate = None

    async def mutate(*, mutator, **_kwargs):
        nonlocal rejected_candidate
        latest = initial.model_copy(deep=True)
        try:
            return mutator(latest, 1, 2)
        finally:
            rejected_candidate = latest

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("enabled consultation must use one lifecycle snapshot")

    monkeypatch.setattr(sessions.settings, "resume_clarify_enabled", True)
    monkeypatch.setattr(sessions, "load_consult_context", context, raising=False)
    monkeypatch.setattr(sessions, "load_state", forbidden)
    monkeypatch.setattr(sessions, "run_consult_round", run)
    monkeypatch.setattr(sessions, "mutate_state_atomically", mutate)

    with TestClient(_api_app()) as client:
        response = client.post(
            "/api/v1/sessions/session-1/consult",
            json={
                "mode": "targeted",
                "message": "继续",
                "expected_round": 0,
            },
        )

    assert response.status_code == 409
    assert response.json() == {"detail": "resume_changed"}
    assert rejected_candidate is not None
    assert rejected_candidate.career_state.consult_rounds_used == 0
    assert rejected_candidate.career_state.consult_transcript == []


def test_enabled_consult_rejects_queued_resume_before_llm(monkeypatch) -> None:
    from app.api.v1 import sessions
    from app.db.state_store import ConsultContext
    from app.state.schema import SharedState

    async def context(_session_id):
        return ConsultContext(
            state=SharedState(session_id="session-1", user_id="user-1"),
            status="resume_queued",
            resume_version=1,
            confirmed_resume_version=None,
            resume_upload_generation=2,
        )

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("queued consultation must stop before the LLM")

    monkeypatch.setattr(sessions.settings, "resume_clarify_enabled", True)
    monkeypatch.setattr(sessions, "load_consult_context", context, raising=False)
    monkeypatch.setattr(sessions, "run_consult_round", forbidden)

    with TestClient(_api_app()) as client:
        response = client.post(
            "/api/v1/sessions/session-1/consult",
            json={
                "mode": "targeted",
                "message": "继续",
                "expected_round": 0,
            },
        )

    assert response.status_code == 409
    assert response.json() == {"detail": "resume_processing"}


@pytest.mark.asyncio
async def test_acceptance_concurrent_with_consult_persist_does_not_lose_turn(
    monkeypatch,
) -> None:
    from app.db import state_store
    from app.state.schema import SharedState

    class Transaction:
        def __init__(self, connection):
            self.connection = connection

        async def __aenter__(self):
            await self.connection.row_lock.acquire()

        async def __aexit__(self, exc_type, exc, tb):
            self.connection.row_lock.release()
            return False

    class Connection:
        def __init__(self):
            self.row_lock = asyncio.Lock()
            self.state = SharedState(
                session_id="session-1",
                user_id="user-1",
            )
            self.status = "resume_ready"
            self.resume_version = 1
            self.confirmed_resume_version = 1
            self.resume_upload_generation = 1
            self.consult_read_started = asyncio.Event()

        def transaction(self):
            return Transaction(self)

        def row(self):
            return {
                "state": self.state.model_dump_json(),
                "status": self.status,
                "resume_version": self.resume_version,
                "confirmed_resume_version": self.confirmed_resume_version,
                "resume_upload_generation": self.resume_upload_generation,
            }

        async def fetchrow(self, sql, *args):
            if "FOR UPDATE" in sql:
                self.consult_read_started.set()
                await asyncio.sleep(0)
                return self.row()
            if "status = 'resume_queued'" in sql:
                await self.consult_read_started.wait()
                async with self.row_lock:
                    self.status = "resume_queued"
                    self.resume_upload_generation += 1
                    self.confirmed_resume_version = None
                    return {
                        "user_id": "user-1",
                        "resume_upload_generation": self.resume_upload_generation,
                    }
            raise AssertionError(sql)

        async def execute(self, sql, *args):
            if "SET state = $1::jsonb" not in sql:
                raise AssertionError(sql)
            self.state = SharedState.model_validate_json(args[0])
            return "UPDATE 1"

    connection = Connection()

    async def fake_get_pool():
        return _Pool(connection)

    monkeypatch.setattr(state_store, "get_pool", fake_get_pool)

    def persist_turn(state, _version, _generation):
        state.career_state.consult_rounds_used = 1
        state.career_state.consult_transcript.append(
            {"round": 1, "user_message": "保留本轮"}
        )

    await asyncio.gather(
        state_store.mutate_state_atomically(
            session_id="session-1",
            mutator=persist_turn,
            status="intent_consulting",
        ),
        state_store.accept_resume_upload(session_id="session-1"),
    )

    assert connection.status == "resume_queued"
    assert connection.resume_upload_generation == 2
    assert connection.confirmed_resume_version is None
    assert connection.state.career_state.consult_rounds_used == 1
    assert connection.state.career_state.consult_transcript == [
        {"round": 1, "user_message": "保留本轮"}
    ]


@pytest.mark.asyncio
async def test_a_b_out_of_order_stale_success_and_failure_do_not_affect_b(
    monkeypatch,
) -> None:
    from app.db import state_store
    from app.state.schema import ResumeState, SharedState

    class Connection:
        def __init__(self):
            self.state = SharedState(session_id="session-1", user_id="user-1")
            self.status = "resume_queued"
            self.resume_version = 1
            self.resume_upload_generation = 2

        def transaction(self):
            return _Transaction()

        def row(self):
            return {
                "state": self.state.model_dump_json(),
                "status": self.status,
                "resume_version": self.resume_version,
                "confirmed_resume_version": None,
                "resume_upload_generation": self.resume_upload_generation,
            }

        async def fetchrow(self, sql, *args):
            if "FOR UPDATE" in sql:
                return self.row()
            if "resume_version = resume_version + 1" in sql:
                assert args[3] == self.resume_upload_generation
                self.state = SharedState.model_validate_json(args[0])
                self.resume_version += 1
                self.status = "resume_ready"
                return {
                    "resume_version": self.resume_version,
                    "confirmed_resume_version": None,
                    "resume_content_hash": args[1],
                    "resume_confirmed_at": None,
                    "resume_upload_generation": self.resume_upload_generation,
                    "status": self.status,
                }
            raise AssertionError(sql)

        async def execute(self, sql, *args):
            if "status = 'resume_error'" not in sql:
                raise AssertionError(sql)
            if (
                args[1] == self.resume_upload_generation
                and self.status == "resume_queued"
            ):
                self.status = "resume_error"
                return "UPDATE 1"
            return "UPDATE 0"

    connection = Connection()

    async def fake_get_pool():
        return _Pool(connection)

    monkeypatch.setattr(state_store, "get_pool", fake_get_pool)

    b_result = await state_store.save_normalized_resume(
        session_id="session-1",
        resume_state=ResumeState(skills=["B-current"]),
        content_hash="hash-b",
        expected_generation=2,
    )
    a_result = await state_store.save_normalized_resume(
        session_id="session-1",
        resume_state=ResumeState(skills=["A-stale"]),
        content_hash="hash-a",
        expected_generation=1,
    )
    a_error_changed = await state_store.mark_resume_error(
        session_id="session-1",
        expected_generation=1,
    )

    assert b_result is not None
    assert a_result is None
    assert a_error_changed is False
    assert connection.status == "resume_ready"
    assert connection.resume_version == 2
    assert connection.state.resume_state.skills == ["B-current"]


@pytest.mark.asyncio
async def test_confirm_checks_expected_version_while_row_is_locked(monkeypatch) -> None:
    from app.db import state_store

    class Connection:
        def __init__(self):
            self.updated = False

        def transaction(self):
            return _Transaction()

        async def fetchrow(self, sql, *args):
            if "FOR UPDATE" in sql:
                return {
                    "state": _old_state_json(),
                    "status": "resume_ready",
                    "resume_version": 2,
                    "confirmed_resume_version": None,
                    "resume_upload_generation": 4,
                }
            self.updated = True
            raise AssertionError("stale expected version must not confirm")

    connection = Connection()

    async def fake_get_pool():
        return _Pool(connection)

    monkeypatch.setattr(state_store, "get_pool", fake_get_pool)

    with pytest.raises(state_store.ResumeLifecycleConflict) as conflict:
        await state_store.confirm_resume(
            session_id="session-1",
            expected_resume_version=1,
        )

    assert conflict.value.detail == "resume_changed"
    assert connection.updated is False
