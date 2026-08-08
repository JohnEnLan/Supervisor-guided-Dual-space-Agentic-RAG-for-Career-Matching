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

    def mutate(state, resume_version, resume_upload_generation, status):
        # B2：mutator 契约扩至 4 参——行锁内的 status 供落库保护判定
        state.career_state.current_goal = ["Data analyst"]
        return resume_version, resume_upload_generation, status

    result = await state_store.mutate_state_atomically(
        session_id="session-1",
        mutator=mutate,
    )

    assert result == (3, 9, "resume_ready")
    assert "FOR UPDATE" in calls[0][1]


@pytest.mark.asyncio
async def test_accept_resume_upload_is_one_update_without_state_rewrite(
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
                "user_id": "user-1",
                "resume_upload_generation": 5,
                "resume_parse_count": 1,
            }

        async def execute(self, sql, *args):
            calls.append(("execute", sql, args))

    async def fake_get_pool():
        return _Pool(Connection())

    monkeypatch.setattr(state_store, "get_pool", fake_get_pool)

    accepted = await state_store.accept_resume_upload(
        session_id="session-1",
        filename="resume.pdf",
        suffix=".pdf",
        content=b"pdf-bytes",
        extracted_text="text",
        pages=2,
        chars=4,
        ocr_suggested=False,
    )

    assert accepted == {
        "user_id": "user-1",
        "resume_upload_generation": 5,
        "resume_parse_count": 1,
    }
    # B2：行锁 UPDATE 先行（置 resume_uploaded，不再直接入队），随后
    # DELETE 旧上传行 + INSERT 新行；SharedState JSON 仍然一个字节不碰。
    update_sql = calls[0][1]
    assert calls[0][0] == "fetchrow"
    assert "UPDATE session_state" in update_sql
    assert "status = 'resume_uploaded'" in update_sql
    assert "resume_upload_generation = resume_upload_generation + 1" in update_sql
    assert "confirmed_resume_version = NULL" in update_sql
    assert "resume_confirmed_at = NULL" in update_sql
    assert "state =" not in update_sql
    assert "version = version + 1" not in update_sql
    assert "DELETE FROM resume_uploads" in calls[1][1]
    assert "INSERT INTO resume_uploads" in calls[2][1]
    assert calls[2][2][4] == b"pdf-bytes"


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
        def transaction(self):
            return _Transaction()

        async def fetchrow(self, sql, *args):
            # B3：mark 改为单事务 UPDATE…RETURNING，miss 返回 None
            calls.append((sql, args))
            return None

        async def execute(self, sql, *args):
            raise AssertionError("CAS miss must not write any progress event")

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


def test_upload_stores_and_extracts_without_llm_or_background_task(
    monkeypatch,
) -> None:
    """B2：上传只存库+本地提取（零 LLM、零后台任务），返回 200 待确认。"""
    from app.api.v1 import sessions

    accepted_kwargs = {}

    async def accept(**kwargs):
        accepted_kwargs.update(kwargs)
        return {
            "user_id": "user-1",
            "resume_upload_generation": 6,
            "resume_parse_count": 1,
        }

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("upload must not normalize, load or rewrite state")

    monkeypatch.setattr(sessions, "accept_resume_upload", accept, raising=False)
    monkeypatch.setattr(sessions, "_normalize_resume", forbidden)
    monkeypatch.setattr(sessions, "load_state", forbidden)
    monkeypatch.setattr(sessions, "save_state", forbidden)

    with TestClient(_api_app()) as client:
        response = client.post(
            "/api/v1/sessions/session-1/resume",
            files={"file": ("resume.txt", b"Python data analysis", "text/plain")},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "resume_uploaded"
    assert payload["session_id"] == "session-1"
    assert payload["generation"] == 6
    assert payload["parses_used"] == 1
    assert payload["chars"] == len("Python data analysis")
    assert accepted_kwargs["session_id"] == "session-1"
    assert accepted_kwargs["content"] == b"Python data analysis"
    assert accepted_kwargs["suffix"] == ".txt"


def test_parse_confirm_begins_cas_and_passes_extracted_text_to_task(
    monkeypatch,
) -> None:
    """B2：确认解析走 begin_resume_parse CAS，后台任务吃上传时的提取文本。"""
    from app.api.v1 import sessions

    calls = []

    async def begin(*, session_id, generation, max_parses):
        assert session_id == "session-1"
        assert generation == 6
        assert max_parses >= 1
        return {
            "owner_user_id": "user-1",
            "resume_parse_count": 1,
            "filename": "resume.txt",
            "suffix": ".txt",
            "content": b"Python data analysis",
            "extracted_text": "Python data analysis",
            "pages": 1,
            "chars": 20,
            "ocr_suggested": False,
        }

    async def normalize(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(sessions, "begin_resume_parse", begin, raising=False)
    monkeypatch.setattr(sessions, "_normalize_resume", normalize)

    with TestClient(_api_app()) as client:
        response = client.post(
            "/api/v1/sessions/session-1/resume/parse",
            json={"generation": 6},
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
            "raw_text": "Python data analysis",
            # B4 输入契约先行贯通：原始字节与后缀随任务传递（B2 不消费）
            "suffix": ".txt",
            "content": b"Python data analysis",
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
            if "status = 'resume_uploaded'" in sql:
                # B2 accept：整个函数已在 conn.transaction()（行锁）内执行
                self.status = "resume_uploaded"
                self.resume_upload_generation += 1
                self.confirmed_resume_version = None
                return {
                    "user_id": "user-1",
                    "resume_upload_generation": self.resume_upload_generation,
                    "resume_parse_count": 0,
                }
            raise AssertionError(sql)

        async def execute(self, sql, *args):
            if "SET state = $1::jsonb" in sql:
                self.state = SharedState.model_validate_json(args[0])
                return "UPDATE 1"
            if "resume_uploads" in sql:
                # B2 accept 事务内的 DELETE/INSERT，对本测试无关紧要
                return "OK"
            raise AssertionError(sql)

    connection = Connection()

    async def fake_get_pool():
        return _Pool(connection)

    monkeypatch.setattr(state_store, "get_pool", fake_get_pool)

    def persist_turn(state, _version, _generation, _status=""):
        state.career_state.consult_rounds_used = 1
        state.career_state.consult_transcript.append(
            {"round": 1, "user_message": "保留本轮"}
        )

    consult_task = asyncio.create_task(
        state_store.mutate_state_atomically(
            session_id="session-1",
            mutator=persist_turn,
            status="intent_consulting",
        )
    )
    await connection.consult_read_started.wait()
    accept_task = asyncio.create_task(
        state_store.accept_resume_upload(
            session_id="session-1",
            filename="resume.pdf",
            suffix=".pdf",
            content=b"new-bytes",
            extracted_text="new text",
            pages=1,
            chars=8,
            ocr_suggested=False,
        )
    )
    await asyncio.gather(consult_task, accept_task)

    assert connection.status == "resume_uploaded"
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
            if "status = 'resume_error'" in sql:
                # B3：mark 走 UPDATE…RETURNING（命中行 / miss None）
                if (
                    args[1] == self.resume_upload_generation
                    and self.status == "resume_queued"
                ):
                    self.status = "resume_error"
                    return {"session_id": args[0]}
                return None
            raise AssertionError(sql)

        async def execute(self, sql, *args):
            raise AssertionError(sql)

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


# ===================== B2 对侧抽查补测：begin/refund/守卫 =====================


class _ParseConn:
    """begin_resume_parse 假连接：可配置会话行与上传行，记录执行的 SQL。"""

    def __init__(self, *, row, upload_row):
        self.row = row
        self.upload_row = upload_row
        self.calls = []

    def transaction(self):
        return _Transaction()

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        if "FOR UPDATE" in sql:
            return self.row
        if "FROM resume_uploads" in sql:
            return self.upload_row
        raise AssertionError(sql)

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))
        return "UPDATE 1"


def _parse_row(**overrides):
    row = {
        "status": "resume_uploaded",
        "resume_upload_generation": 3,
        "resume_parse_count": 0,
        "owner_user_id": "user-1",
    }
    row.update(overrides)
    return row


def _upload_row(**overrides):
    row = {
        "filename": "resume.pdf",
        "suffix": ".pdf",
        "content": b"bytes",
        "extracted_text": "text",
        "pages": 1,
        "chars": 4,
        "ocr_suggested": False,
    }
    row.update(overrides)
    return row


async def _begin(monkeypatch, conn, *, generation=3, max_parses=3):
    from app.db import state_store

    async def fake_get_pool():
        return _Pool(conn)

    monkeypatch.setattr(state_store, "get_pool", fake_get_pool)
    return await state_store.begin_resume_parse(
        session_id="session-1", generation=generation, max_parses=max_parses
    )


@pytest.mark.asyncio
async def test_begin_parse_classification_priority_limit_beats_everything(
    monkeypatch,
) -> None:
    """分类优先级写死：额度满时即使 generation 也不匹配，仍报 parse_limit。"""
    from app.db.state_store import ResumeLifecycleConflict

    conn = _ParseConn(
        row=_parse_row(resume_parse_count=3, resume_upload_generation=99),
        upload_row=_upload_row(),
    )
    with pytest.raises(ResumeLifecycleConflict) as excinfo:
        await _begin(monkeypatch, conn, generation=3)
    assert excinfo.value.detail == "resume_parse_limit"
    # 分类失败绝不扣费
    assert not [c for c in conn.calls if c[0] == "execute"]


@pytest.mark.asyncio
async def test_begin_parse_generation_mismatch_beats_status(monkeypatch) -> None:
    from app.db.state_store import ResumeLifecycleConflict

    conn = _ParseConn(
        row=_parse_row(resume_upload_generation=4, status="resume_queued"),
        upload_row=_upload_row(),
    )
    with pytest.raises(ResumeLifecycleConflict) as excinfo:
        await _begin(monkeypatch, conn, generation=3)
    assert excinfo.value.detail == "resume_changed"


@pytest.mark.asyncio
async def test_begin_parse_double_click_second_sees_processing(monkeypatch) -> None:
    """双击单扣：首个请求置 queued 后，第二个请求命中 resume_processing。"""
    from app.db.state_store import ResumeLifecycleConflict

    conn = _ParseConn(row=_parse_row(), upload_row=_upload_row())
    started = await _begin(monkeypatch, conn)
    assert started["extracted_text"] == "text"
    assert started["content"] == b"bytes"
    update_sqls = [c[1] for c in conn.calls if c[0] == "execute"]
    assert any("resume_parse_count = resume_parse_count + 1" in sql for sql in update_sqls)

    conn2 = _ParseConn(
        row=_parse_row(status="resume_queued", resume_parse_count=1),
        upload_row=_upload_row(),
    )
    with pytest.raises(ResumeLifecycleConflict) as excinfo:
        await _begin(monkeypatch, conn2)
    assert excinfo.value.detail == "resume_processing"


@pytest.mark.asyncio
async def test_begin_parse_other_status_reports_unparsed(monkeypatch) -> None:
    from app.db.state_store import ResumeLifecycleConflict

    conn = _ParseConn(row=_parse_row(status="resume_ready"), upload_row=_upload_row())
    with pytest.raises(ResumeLifecycleConflict) as excinfo:
        await _begin(monkeypatch, conn)
    assert excinfo.value.detail == "resume_unparsed"


@pytest.mark.asyncio
async def test_begin_parse_missing_upload_row_rolls_back_as_changed(
    monkeypatch,
) -> None:
    """事务内取不到字节（行缺失或 content 已清）→ resume_changed，整体回滚。"""
    from app.db.state_store import ResumeLifecycleConflict

    for upload_row in (None, _upload_row(content=None)):
        conn = _ParseConn(row=_parse_row(), upload_row=upload_row)
        with pytest.raises(ResumeLifecycleConflict) as excinfo:
            await _begin(monkeypatch, conn)
        assert excinfo.value.detail == "resume_changed"


@pytest.mark.asyncio
async def test_refund_parse_count_is_generationless_with_floor(monkeypatch) -> None:
    """返还语句：无 generation 谓词（重传竞态下也确定返还）+ GREATEST 下限。"""
    from app.db import state_store

    calls = []

    class Conn:
        async def execute(self, sql, *args):
            calls.append((sql, args))
            return "UPDATE 1"

    async def fake_get_pool():
        return _Pool(Conn())

    monkeypatch.setattr(state_store, "get_pool", fake_get_pool)
    await state_store.refund_parse_count(session_id="session-1")

    sql = calls[0][0]
    assert "GREATEST(resume_parse_count - 1, 0)" in sql
    assert "resume_upload_generation" not in sql
    assert calls[0][1] == ("session-1",)


@pytest.mark.parametrize("flag", [True, False])
@pytest.mark.parametrize(
    ("status", "detail"),
    [("resume_uploaded", "resume_unparsed"), ("resume_queued", "resume_processing")],
)
def test_consult_and_finalize_block_new_states_regardless_of_flag(
    monkeypatch, flag, status, detail
) -> None:
    """B2 无条件生命周期保护：新状态在任一 flag 配置下都不得进 LLM 路径。"""
    from app.api.v1 import sessions
    from app.db.state_store import ConsultContext
    from app.state.schema import SharedState

    async def context(_session_id):
        return ConsultContext(
            state=SharedState(session_id="session-1", user_id="user-1"),
            status=status,
            resume_version=1,
            confirmed_resume_version=1,
            resume_upload_generation=2,
        )

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("blocked lifecycle state must not reach the LLM")

    monkeypatch.setattr(sessions.settings, "resume_clarify_enabled", flag)
    monkeypatch.setattr(sessions, "load_consult_context", context)
    monkeypatch.setattr(sessions, "run_consult_round", forbidden, raising=False)
    monkeypatch.setattr(sessions, "build_brief_draft", forbidden, raising=False)

    with TestClient(_api_app()) as client:
        consult = client.post(
            "/api/v1/sessions/session-1/consult",
            json={"mode": "targeted", "message": "继续", "expected_round": 0},
        )
        finalize = client.post("/api/v1/sessions/session-1/consult/finalize")

    assert consult.status_code == 409
    assert consult.json()["detail"] == detail
    assert finalize.status_code == 409
    assert finalize.json()["detail"] == detail


@pytest.mark.asyncio
async def test_flag_off_consult_downgrades_to_transcript_only_on_regen(
    monkeypatch,
) -> None:
    """flag-off 且 LLM 等待期间换代：persist_turn 必须返回
    MutationOutcome(status_override=None)，只合并 transcript、不合并
    career 字段、不覆盖 status（B2 对侧抽查二轮 M3 点名的缺口）。"""
    from app.agents.consult_engine import ConsultTurn
    from app.api.v1 import sessions
    from app.db.state_store import ConsultContext, MutationOutcome
    from app.state.schema import SharedState

    loaded = SharedState(session_id="session-1", user_id="user-1")

    async def context(_session_id):
        return ConsultContext(
            state=loaded.model_copy(deep=True),
            status="intent_consulting",
            resume_version=1,
            confirmed_resume_version=1,
            resume_upload_generation=1,
        )

    async def advisor(working, **_kwargs):
        working.career_state.current_goal = ["Data analyst"]
        working.career_state.consult_rounds_used = 1
        working.career_state.consult_transcript.append(
            {"round": 1, "user_message": "数据分析"}
        )
        return ConsultTurn(
            assistant_reply="收到。",
            next_question="地点呢？",
            phase="template",
            completeness=0.2,
            can_finalize=False,
            round=1,
            profile_draft={},
        )

    captured = {}

    async def mutate(*, session_id, mutator, status=None, **_kwargs):
        # 模拟真实 mutate：行锁内已换代（generation 1→2）、状态为新流程态
        latest = loaded.model_copy(deep=True)
        raw = mutator(latest, 1, 2, "resume_uploaded")
        captured["raw"] = raw
        captured["latest"] = latest
        if isinstance(raw, MutationOutcome):
            return raw.result
        return raw

    monkeypatch.setattr(sessions.settings, "resume_clarify_enabled", False)
    monkeypatch.setattr(sessions.settings, "consult_coach_enabled", False)
    monkeypatch.setattr(sessions, "load_consult_context", context)
    monkeypatch.setattr(sessions, "run_consult_round", advisor, raising=False)
    monkeypatch.setattr(sessions, "mutate_state_atomically", mutate)

    with TestClient(_api_app()) as client:
        response = client.post(
            "/api/v1/sessions/session-1/consult",
            json={"mode": "targeted", "message": "数据分析", "expected_round": 0},
        )

    assert response.status_code == 200
    raw = captured["raw"]
    assert isinstance(raw, MutationOutcome)
    assert raw.status_override is None
    persisted = captured["latest"]
    assert persisted.career_state.consult_transcript, "transcript 必须落库"
    assert persisted.career_state.current_goal == [], "career 字段不得合并旧代产物"
