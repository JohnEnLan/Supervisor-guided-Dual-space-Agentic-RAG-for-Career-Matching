from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.domain.run import MatchRun, RunStatus
from app.domain.results import ProductResult


PUBLIC_PATHS = {
    "/api/v1/capabilities",
    "/api/v1/sessions",
    "/api/v1/sessions/{session_id}/resume",
    "/api/v1/sessions/{session_id}/resume-upload",
    "/api/v1/sessions/{session_id}/resume/parse",
    "/api/v1/sessions/{session_id}/resume-progress",
    "/api/v1/sessions/{session_id}/resume-preview",
    "/api/v1/sessions/{session_id}/resume-confirm",
    "/api/v1/sessions/{session_id}/consult",
    "/api/v1/sessions/{session_id}/consult/finalize",
    "/api/v1/sessions/{session_id}/match-brief",
    "/api/v1/runs/{run_id}/execute",
    "/api/v1/runs/{run_id}/status",
    "/api/v1/runs/{run_id}/conversation",
    "/api/v1/runs/{run_id}/result",
    "/api/v1/runs/{run_id}/explain",
    "/api/v1/runs/{run_id}/reaction",
    "/api/v1/monitoring/overview",
    "/api/v1/monitoring/runs",
    "/api/v1/admin/overview",
    "/api/v1/admin/users",
    "/api/v1/admin/users/{user_id}/resume",
    "/api/v1/admin/runs/{run_id}/explain",
    "/api/v1/admin/sessions/{session_id}/reset-parse-count",
}


@pytest.mark.asyncio
async def test_normalize_resume_persists_resume_and_version_atomically(
    monkeypatch,
    tmp_path,
):
    from app.api.v1 import sessions
    from app.state.schema import ResumeState, SharedState

    calls = []
    cleanup_calls = []
    normalized_resume = ResumeState(skills=["Python"])

    async def fake_normalize_text(_raw_text, _spans):
        return normalized_resume

    async def save_normalized_resume(**kwargs):
        calls.append(kwargs)
        return {"resume_version": 1}

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("normalization must use the compound atomic write")

    async def missing(_session_id):
        return None

    async def cleanup(**kwargs):
        cleanup_calls.append(kwargs)

    progress_events = []

    async def record_progress(**kwargs):
        progress_events.append(kwargs)

    monkeypatch.setattr(sessions, "normalize_resume_text", fake_normalize_text)
    monkeypatch.setattr(
        sessions,
        "save_normalized_resume",
        save_normalized_resume,
        raising=False,
    )
    monkeypatch.setattr(sessions, "save_state", forbidden)
    monkeypatch.setattr(sessions, "load_state", missing)
    monkeypatch.setattr(sessions, "clear_resume_upload_content", cleanup)
    monkeypatch.setattr(sessions, "record_intake_progress", record_progress)

    await sessions._normalize_resume(
        session_id="session-1",
        user_id="user-1",
        raw_text="Python resume",
        expected_generation=7,
    )

    assert calls[0]["session_id"] == "session-1"
    assert calls[0]["resume_state"].skills == ["Python"]
    assert len(calls[0]["content_hash"]) == 64
    assert calls[0]["expected_generation"] == 7
    # B3：终态 done 事件随 save 的 CAS 事务写入（intake 回调不落终态）
    assert calls[0]["terminal_event"].step == "done"
    assert "用时" in calls[0]["terminal_event"].text
    # B2：任务收尾定向清理 BYTEA 与临时提取副本
    assert cleanup_calls == [{"session_id": "session-1", "generation": 7}]
    # B3 叙事回调序列：received → extracted → normalizing → validated，
    # seq 任务内单调，首事件带 first=True（触发旧代清理）
    assert [event["step"] for event in progress_events] == [
        "received", "extracted", "normalizing", "validated",
    ]
    assert [event["seq"] for event in progress_events] == [1, 2, 3, 4]
    assert [event["first"] for event in progress_events] == [
        True, False, False, False,
    ]
    assert all(
        event["session_id"] == "session-1" and event["generation"] == 7
        for event in progress_events
    )


@pytest.mark.asyncio
async def test_normalize_resume_failure_updates_only_status_atomically(monkeypatch):
    from app.api.v1 import sessions

    calls = []
    refunds = []

    async def failing_normalize(_raw_text, _spans):
        raise ValueError("bad resume")

    async def mark_error(*, session_id: str, expected_generation: int, terminal_event=None):
        calls.append(
            (
                session_id,
                expected_generation,
                terminal_event.step if terminal_event else None,
            )
        )
        return True

    async def refund(*, session_id: str):
        refunds.append(session_id)

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("failure fallback must not whole-save stale state")

    async def cleanup(**_kwargs):
        return None

    async def record_progress(**_kwargs):
        return None

    monkeypatch.setattr(sessions, "normalize_resume_text", failing_normalize)
    monkeypatch.setattr(sessions, "mark_resume_error", mark_error)
    monkeypatch.setattr(sessions, "refund_parse_count", refund)
    monkeypatch.setattr(sessions, "clear_resume_upload_content", cleanup)
    monkeypatch.setattr(sessions, "load_state", forbidden)
    monkeypatch.setattr(sessions, "save_state", forbidden)
    monkeypatch.setattr(sessions, "record_intake_progress", record_progress)

    await sessions._normalize_resume(
        session_id="session-1",
        user_id="user-1",
        raw_text="Python resume with enough text to build spans",
        expected_generation=11,
    )

    # B3：错误终态事件经 terminal_event 随 mark 的 CAS 事务写入
    assert calls == [("session-1", 11, "error")]
    # LLM 外呼已发起（normalize 阶段）才失败 → 不返还解析额度
    assert refunds == []


@pytest.mark.asyncio
async def test_save_terminal_failure_falls_back_to_error_marking(monkeypatch):
    """C1/C2 裁决闭环（口径按 Codex 二轮 m1 收窄）：本测试证明的是"save
    因任意异常失败 → 任务唯一 except 分支必然尝试 mark_resume_error 落
    error 终态、不返还（LLM 外呼已发生）、上传内容照常清理"。mark 自身
    也撞 seq=100 PK 的双冲突场景在代码内不可达（每代至多一次入队+一次
    终态，见方案 §1.2 论证），属部署/手工救济不变量——运维红线已记
    方案 §5.3（同代重置必须连删该代进度行）。"""
    from app.api.v1 import sessions
    from app.state.schema import ResumeState

    marks = []
    cleanup_calls = []

    async def fake_normalize_text(_raw_text, _spans):
        return ResumeState(skills=["Python"])

    async def failing_save(**_kwargs):
        # 中性异常文本（Codex 三轮 m3）：本测试覆盖"任意 save 失败"，
        # 不要伪装成已被排除的 seq=100 双 PK 冲突场景
        raise RuntimeError("save failed")

    async def mark_error(*, session_id, expected_generation, terminal_event=None):
        marks.append(
            (
                session_id,
                expected_generation,
                terminal_event.step if terminal_event else None,
            )
        )
        return True

    async def forbidden_refund(*, session_id):
        raise AssertionError("post-LLM failure must not refund the parse count")

    async def cleanup(**kwargs):
        cleanup_calls.append(kwargs)

    async def record_progress(**_kwargs):
        return None

    monkeypatch.setattr(sessions, "normalize_resume_text", fake_normalize_text)
    monkeypatch.setattr(sessions, "save_normalized_resume", failing_save)
    monkeypatch.setattr(sessions, "mark_resume_error", mark_error)
    monkeypatch.setattr(sessions, "refund_parse_count", forbidden_refund)
    monkeypatch.setattr(sessions, "clear_resume_upload_content", cleanup)
    monkeypatch.setattr(sessions, "record_intake_progress", record_progress)

    await sessions._normalize_resume(
        session_id="session-1",
        user_id="user-1",
        raw_text="Python resume with enough text to build spans",
        expected_generation=9,
    )

    assert marks == [("session-1", 9, "error")]
    assert cleanup_calls == [{"session_id": "session-1", "generation": 9}]


def _app() -> FastAPI:
    from app.api.v1.router import router

    app = FastAPI()
    app.include_router(router)
    return app


def _run(*, status: RunStatus, result=None) -> MatchRun:
    now = datetime.now(UTC)
    return MatchRun(
        run_id="run-1",
        session_id="session-1",
        status=status,
        stage=None,
        plan_version=1,
        approved_plan={},
        result_snapshot=result,
        created_at=now,
        updated_at=now,
    )


def test_all_public_routes_have_response_models() -> None:
    app = _app()
    public_routes = app.openapi()["paths"]

    assert PUBLIC_PATHS <= set(public_routes)
    for path in PUBLIC_PATHS:
        for operation in public_routes[path].values():
            success = next(
                response
                for code, response in operation["responses"].items()
                if code.startswith("2")
            )
            assert "schema" in success["content"]["application/json"]


def test_w4_transition_contracts_are_absent_from_openapi() -> None:
    schema = _app().openapi()

    assert "/api/v1/sessions/{session_id}/intent-consult" not in schema["paths"]
    component_schemas = schema["components"]["schemas"]
    assert {
        "CareerDirectionResponse",
        "IntentConsultRequest",
        "IntentConsultResponse",
    }.isdisjoint(component_schemas)
    session_create = component_schemas["SessionCreateRequest"]
    assert "user_id" not in session_create.get("properties", {})


def test_match_brief_requires_confirmed_resume(monkeypatch) -> None:
    from app.api.v1 import sessions

    async def not_confirmed(_session_id: str):
        return {"exists": True, "resume_version": 1, "confirmed_resume_version": None}

    monkeypatch.setattr(sessions, "get_resume_metadata", not_confirmed)

    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/sessions/session-1/match-brief",
            json={
                "career_goal": "Find evidence-grounded analyst roles",
                "hard_constraints": {"locations": ["Birmingham"]},
                "soft_preferences": {},
                "avoid_roles": [],
                "result_count": 5,
            },
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "resume must be confirmed"


def test_match_brief_persists_approved_career_state_before_run_snapshot(
    monkeypatch,
) -> None:
    from app.api.v1 import sessions
    from app.state.schema import SharedState

    state = SharedState(session_id="session-1", user_id="private-user")
    call_order: list[str] = []

    async def confirmed(_session_id: str):
        return {
            "exists": True,
            "resume_version": 1,
            "confirmed_resume_version": 1,
        }

    async def mutate(*, session_id: str, mutator, status: str):
        assert session_id == "session-1"
        current = state.model_copy(deep=True)
        current.feedback_state.user_feedback.append(
            {"feedback_id": 7, "job_id": "job-7", "outcome": "offer"}
        )
        result = mutator(current)
        call_order.append("mutate_state")
        assert status == "match_brief_approved"
        assert current.career_state.current_goal == [
            "Find evidence-grounded platform engineering roles"
        ]
        assert current.career_state.hard_constraints == {
            "companies": ["OpenAI"]
        }
        assert current.career_state.soft_preferences == {
            "preferred_companies": ["DeepMind"]
        }
        assert current.career_state.avoid_roles == ["sales"]
        assert current.career_state.intent_consulted is True
        assert current.feedback_state.user_feedback[0]["feedback_id"] == 7
        return result

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("match brief must not whole-save stale state")

    async def create(*, session_id: str):
        call_order.append("create_run")
        assert session_id == "session-1"
        assert call_order == ["mutate_state", "create_run"]
        return _run(status=RunStatus.DRAFT)

    async def save_brief(**_kwargs):
        return _run(status=RunStatus.PLAN_READY)

    monkeypatch.setattr(sessions, "get_resume_metadata", confirmed)
    monkeypatch.setattr(sessions, "load_state", forbidden)
    monkeypatch.setattr(sessions, "save_state", forbidden)
    monkeypatch.setattr(sessions, "mutate_state_atomically", mutate)
    monkeypatch.setattr(sessions, "create_run", create)
    monkeypatch.setattr(sessions, "save_match_brief", save_brief)

    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/sessions/session-1/match-brief",
            json={
                "career_goal": "Find evidence-grounded platform engineering roles",
                "hard_constraints": {"companies": ["OpenAI"]},
                "soft_preferences": {"preferred_companies": ["DeepMind"]},
                "avoid_roles": ["sales"],
                "result_count": 5,
            },
        )

    assert response.status_code == 201
    assert call_order == ["mutate_state", "create_run"]


def test_execute_rejects_stale_plan(monkeypatch) -> None:
    from app.api.v1 import runs
    from app.db.run_store import RunConflict

    async def conflict(**_kwargs):
        raise RunConflict("run must be plan_ready")

    monkeypatch.setattr(runs, "queue_run", conflict)

    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/runs/run-1/execute",
            json={"plan_version": 1, "plan_hash": "a" * 64},
        )

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_execute_graph_path_passes_lifespan_checkpointer_to_runner(
    monkeypatch,
) -> None:
    from fastapi import BackgroundTasks

    from app.api.v1 import runs
    from app.api.v1.schemas import ExecuteRunRequest

    queued = _run(status=RunStatus.QUEUED)
    checkpointer = object()

    async def queue(**_kwargs):
        return queued

    async def graph_executor(*, run_id: str, checkpointer):
        del run_id, checkpointer

    monkeypatch.setattr(runs, "queue_run", queue)
    monkeypatch.setattr(runs, "run_graph_match", graph_executor)
    monkeypatch.setattr(
        runs.settings,
        "langgraph_orchestrator_enabled",
        True,
    )
    background_tasks = BackgroundTasks()
    http_request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(langgraph_checkpointer=checkpointer)
        )
    )

    response = await runs.execute_run(
        run_id="run-1",
        request=ExecuteRunRequest(
            plan_version=1,
            plan_hash="a" * 64,
        ),
        background_tasks=background_tasks,
        http_request=http_request,
    )

    assert response.status == RunStatus.QUEUED.value
    assert len(background_tasks.tasks) == 1
    task = background_tasks.tasks[0]
    assert task.func is runs._run_with_usage_scope
    assert task.args == ("run-1", graph_executor)
    assert task.kwargs == {
        "run_id": "run-1",
        "checkpointer": checkpointer,
    }


def test_resume_confirm_distinguishes_missing_session(monkeypatch) -> None:
    from app.api.v1 import sessions

    async def missing(**_kwargs):
        raise KeyError("missing")

    monkeypatch.setattr(sessions, "confirm_resume", missing)

    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/sessions/missing/resume-confirm"
        )

    assert response.status_code == 404


def test_result_endpoint_returns_only_product_snapshot(monkeypatch) -> None:
    from app.api.v1 import runs

    result = ProductResult(summary="No safe roles").model_dump(mode="json")

    async def completed(**_kwargs):
        return _run(status=RunStatus.COMPLETED, result=result)

    monkeypatch.setattr(runs, "get_run", completed)

    with TestClient(_app()) as client:
        response = client.get("/api/v1/runs/run-1/result")

    assert response.status_code == 200
    payload = response.json()
    assert payload["result"] == result
    assert "state" not in payload
    assert "user_id" not in str(payload)


def test_completed_with_warnings_result_is_readable(monkeypatch) -> None:
    from app.api.v1 import runs

    result = ProductResult(
        summary="Partial result", warnings=["implicit_space_unavailable"]
    ).model_dump(mode="json")

    async def completed(**_kwargs):
        return _run(status=RunStatus.COMPLETED_WITH_WARNINGS, result=result)

    monkeypatch.setattr(runs, "get_run", completed)

    with TestClient(_app()) as client:
        response = client.get("/api/v1/runs/run-1/result")

    assert response.status_code == 200
    assert response.json()["status"] == "completed_with_warnings"


def test_nonterminal_result_returns_recovery_hint(monkeypatch) -> None:
    from app.api.v1 import runs

    async def running(**_kwargs):
        return _run(status=RunStatus.RUNNING)

    monkeypatch.setattr(runs, "get_run", running)

    with TestClient(_app()) as client:
        response = client.get("/api/v1/runs/run-1/result")

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "message": "run result is not ready",
        "recovery": {
            "action": "poll_status",
            "status_url": "/api/v1/runs/run-1/status",
        },
    }


def test_explain_endpoint_allow_list_blocks_private_and_provider_data(monkeypatch) -> None:
    from app.api.v1 import runs
    from app.state.schema import ResumeState, SharedState

    state = SharedState(
        session_id="session-1",
        user_id="private-user",
        resume_state=ResumeState(normalized_base_resume="full private resume"),
        supervisor_log=[
            {
                "stage": "final_verification",
                "prompt": "private prompt",
                "provider_error": "private provider error",
            }
        ],
    )

    async def completed(**_kwargs):
        return _run(
            status=RunStatus.COMPLETED,
            result=ProductResult(summary="Done").model_dump(mode="json"),
        )

    async def snapshot(**_kwargs):
        return state.model_dump(mode="json")

    monkeypatch.setattr(runs, "get_run", completed)
    monkeypatch.setattr(runs, "load_state_snapshot", snapshot)
    monkeypatch.setattr(runs.settings, "evaluation_capability_enabled", True)

    with TestClient(_app()) as client:
        response = client.get("/api/v1/runs/run-1/explain")

    assert response.status_code == 200
    serialized = response.text
    for private_value in (
        "private-user",
        "full private resume",
        "supervisor_log",
        "private prompt",
        "private provider error",
    ):
        assert private_value not in serialized


def test_explain_is_hidden_when_evaluation_capability_is_disabled(monkeypatch) -> None:
    from app.api.v1 import runs

    monkeypatch.setattr(runs.settings, "evaluation_capability_enabled", False)

    with TestClient(_app()) as client:
        response = client.get("/api/v1/runs/run-1/explain")

    assert response.status_code == 404


def test_contact_redaction_preserves_year_ranges_but_hides_phone_numbers() -> None:
    from app.api.v1.sessions import _redact_contact_text

    redacted = _redact_contact_text(
        "Experience: 2019-2023. Phone: +44 7700 900123."
    )

    assert "2019-2023" in redacted
    assert "+44 7700 900123" not in redacted
    assert "[phone hidden]" in redacted


def test_openapi_v1_snapshot_is_current() -> None:
    from scripts.export_openapi import build_openapi_v1

    snapshot_path = Path("tests/snapshots/openapi_v1.json")
    assert json.loads(snapshot_path.read_text(encoding="utf-8")) == build_openapi_v1()
