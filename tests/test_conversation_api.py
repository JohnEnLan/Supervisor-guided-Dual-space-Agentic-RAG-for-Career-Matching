from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domain.run import MatchRun, RunStage, RunStatus
from app.domain.results import EvidenceItem, ProductResult, RecommendationResult


PRIVATE_RESUME_TEXT = "这是一段绝不能泄露的简历原文"


def _app() -> FastAPI:
    from app.api.v1.router import router

    app = FastAPI()
    app.include_router(router)
    return app


def _run(
    *,
    status: RunStatus,
    stage: RunStage | None = None,
    result: ProductResult | None = None,
    warning_codes: list[str] | None = None,
    error_code: str | None = None,
) -> MatchRun:
    now = datetime.now(UTC)
    return MatchRun(
        run_id="run-1",
        session_id="session-private",
        status=status,
        stage=stage,
        plan_version=1,
        plan_hash="a" * 64,
        approved_plan={
            "career_goal": "寻找数据分析与商业智能岗位",
            "hard_constraints": {
                "locations": ["Birmingham"],
                "visa_sponsorship": True,
            },
            "soft_preferences": {"industries": ["technology"]},
            "avoid_roles": ["sales"],
            "result_count": 5,
        },
        result_snapshot=(
            result.model_dump(mode="json") if result is not None else None
        ),
        warning_codes=warning_codes or [],
        error_code=error_code,
        created_at=now,
        updated_at=now,
    )


def _completed_result(*, warnings: list[str] | None = None) -> ProductResult:
    return ProductResult(
        summary="Three roles",
        recommended_roles=[
            RecommendationResult(
                job_id="job-now",
                tier="now_fit",
                concise_explanation="当前匹配",
            ),
            RecommendationResult(
                job_id="job-stretch",
                tier="stretch_fit",
                concise_explanation="进阶匹配",
            ),
            RecommendationResult(
                job_id="job-bridge",
                tier="bridge_role",
                concise_explanation="过渡匹配",
            ),
        ],
        warnings=warnings or [],
    )


def test_completed_conversation_has_four_personas_and_stable_order(
    monkeypatch,
) -> None:
    from app.api.v1 import runs

    async def completed(**_kwargs):
        return _run(
            status=RunStatus.COMPLETED,
            stage=RunStage.FINALIZATION,
            result=_completed_result(),
        )

    async def snapshot(**_kwargs):
        return {
            "supervisor_log": [
                {
                    "stage": "supervisor_checkpoint",
                    "checkpoint": "matching_input",
                    "status": "passed",
                    "metrics": {"top_k": 5},
                },
                {
                    "stage": "supervisor_checkpoint",
                    "checkpoint": "matching_output",
                    "status": "passed",
                    "metrics": {
                        "candidate_count": 7,
                        "ranking_count": 7,
                        "evidence_count": 6,
                    },
                },
            ]
        }

    monkeypatch.setattr(runs, "get_run", completed)
    monkeypatch.setattr(runs, "load_state_snapshot", snapshot)

    with TestClient(_app()) as client:
        response = client.get("/api/v1/runs/run-1/conversation")

    assert response.status_code == 200
    payload = response.json()
    messages = payload["messages"]
    assert payload["next_poll_ms"] is None
    assert [message["seq"] for message in messages] == list(
        range(1, len(messages) + 1)
    )
    assert list(dict.fromkeys(message["persona"] for message in messages)) == [
        "pm",
        "intent_consultant",
        "job_scout",
        "strategist",
    ]
    assert [message["kind"] for message in messages] == [
        "intro",
        "brief",
        "checkpoint",
        "progress",
        "progress",
        "checkpoint",
        "progress",
        "progress",
        "checkpoint",
        "result",
    ]
    assert messages[2]["persona"] == "pm"
    assert messages[2]["stage"] == "intent"
    assert "小检接收的约束与确认单一致" in messages[2]["text"]
    assert "job_id 级 RRF 融合" in messages[3]["text"]
    assert "你要求的 Birmingham 我已锁定为硬条件，绝不放宽" in messages[3][
        "text"
    ]
    assert messages[5]["persona"] == "pm"
    assert messages[5]["stage"] == "retrieval"
    assert "小检返回了 7 个候选" in messages[5]["text"]
    assert "排序记录 7 条、证据记录 6 条" in messages[5]["text"]
    assert "我核对了候选集、排序与证据完整性" in messages[5]["text"]
    assert "3 个可发布候选岗位" not in response.text
    assert "硬约束由数据库严格执行" not in response.text
    assert "已锁定并将由 SQL/metadata 严格过滤" not in response.text
    assert "我已复核本次 Match Brief" not in response.text
    assert "所有建议只基于已核验信息" not in response.text
    assert "基于某个岗位细化简历" in messages[7]["text"]
    assert "Now Fit 1 个、Stretch Fit 1 个、Bridge Role 1 个" in messages[-1][
        "text"
    ]
    assert "Results 页" in messages[-1]["text"]


def test_conversation_announces_allowlisted_recovery_events(monkeypatch) -> None:
    from app.api.v1 import runs

    async def completed(**_kwargs):
        return _run(
            status=RunStatus.COMPLETED,
            stage=RunStage.FINALIZATION,
            result=_completed_result(),
        )

    async def snapshot(**_kwargs):
        return {
            "supervisor_log": [
                {
                    "stage": "reretrieval_loop",
                    "reason": "too_few_results",
                    "loop_used": 1,
                    "max_loops": 1,
                    "prompt": "private prompt",
                },
                {
                    "stage": "repair_loop",
                    "reason": "unsupported_resume_advice",
                    "loop_used": 1,
                    "max_loops": 1,
                    "provider_error": "private provider error",
                },
                {
                    "stage": "final_verification",
                    "reason": "must not be projected",
                },
            ]
        }

    monkeypatch.setattr(runs, "get_run", completed)
    monkeypatch.setattr(runs, "load_state_snapshot", snapshot)

    with TestClient(_app()) as client:
        response = client.get("/api/v1/runs/run-1/conversation")

    recovery = [
        message
        for message in response.json()["messages"]
        if message["kind"] == "recovery"
    ]
    assert [message["stage"] for message in recovery] == [
        "verification",
        "verification",
    ]
    assert "触发了一次受控重检索" in recovery[0]["text"]
    assert "触发了一次受控修复" in recovery[1]["text"]
    assert all("有界，最多一次" in message["text"] for message in recovery)
    assert "private prompt" not in response.text
    assert "private provider error" not in response.text


def test_completed_with_warnings_translates_known_and_unknown_codes(
    monkeypatch,
) -> None:
    from app.api.v1 import runs

    result = _completed_result(
        warnings=[
            "implicit_space_unavailable",
            "future_warning_code",
        ]
    )

    async def completed(**_kwargs):
        return _run(
            status=RunStatus.COMPLETED_WITH_WARNINGS,
            stage=RunStage.FINALIZATION,
            result=result,
            warning_codes=[
                "implicit_space_unavailable",
                "future_warning_code",
            ],
        )

    async def snapshot(**_kwargs):
        return {"supervisor_log": []}

    monkeypatch.setattr(runs, "get_run", completed)
    monkeypatch.setattr(runs, "load_state_snapshot", snapshot)

    with TestClient(_app()) as client:
        response = client.get("/api/v1/runs/run-1/conversation")

    warning_messages = [
        message["text"]
        for message in response.json()["messages"]
        if message["kind"] == "warning"
    ]
    assert len(warning_messages) == 2
    assert "隐式案例空间暂时不可用" in warning_messages[0]
    assert (
        warning_messages[1]
        == "本次服务带有一项系统提示，请在 Results 页核对详情"
        "（代码：future_warning_code）。"
    )
    assert "warning 2 项" in next(
        message["text"]
        for message in response.json()["messages"]
        if message["kind"] == "result"
    )


def test_conversation_returns_404_for_unknown_run(monkeypatch) -> None:
    from app.api.v1 import runs

    async def missing(**_kwargs):
        return None

    monkeypatch.setattr(runs, "get_run", missing)

    with TestClient(_app()) as client:
        response = client.get("/api/v1/runs/missing/conversation")

    assert response.status_code == 404
    assert response.json()["detail"] == "run_id not found"


def test_nonterminal_conversation_returns_incremental_messages(monkeypatch) -> None:
    from app.api.v1 import runs

    async def running(**_kwargs):
        return _run(status=RunStatus.RUNNING, stage=RunStage.RETRIEVAL)

    async def snapshot(**_kwargs):
        return {"supervisor_log": []}

    monkeypatch.setattr(runs, "get_run", running)
    monkeypatch.setattr(runs, "load_state_snapshot", snapshot)

    with TestClient(_app()) as client:
        response = client.get("/api/v1/runs/run-1/conversation")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "running"
    assert payload["stage"] == "retrieval"
    assert payload["next_poll_ms"] == 1500
    assert [message["persona"] for message in payload["messages"]] == [
        "pm",
        "intent_consultant",
        "pm",
        "job_scout",
    ]
    assert payload["messages"][2]["kind"] == "checkpoint"
    assert payload["messages"][2]["stage"] == "intent"
    serialized_messages = str(payload["messages"])
    assert "正在执行" in serialized_messages
    assert "检索与融合已完成" not in serialized_messages
    assert "缺口分析" not in serialized_messages


def test_conversation_response_does_not_expose_private_state(monkeypatch) -> None:
    from app.api.v1 import runs

    result = _completed_result()
    result.recommended_roles[0].resume_evidence = [
        EvidenceItem(
            evidence_span_id="resume-private",
            field="resume",
            content=PRIVATE_RESUME_TEXT,
        )
    ]

    async def completed(**_kwargs):
        return _run(
            status=RunStatus.COMPLETED,
            stage=RunStage.FINALIZATION,
            result=result,
        )

    async def snapshot(**_kwargs):
        return {
            "user_id": "private-user-id",
            "resume_state": {
                "normalized_base_resume": PRIVATE_RESUME_TEXT,
            },
            "retrieval_state": {
                "filter_log": [PRIVATE_RESUME_TEXT],
            },
            "supervisor_log": [
                {
                    "stage": "supervisor_checkpoint",
                    "checkpoint": "matching_input",
                    "status": "passed",
                    "metrics": {
                        "top_k": 5,
                        "private_metric": PRIVATE_RESUME_TEXT,
                    },
                    "private_prompt": PRIVATE_RESUME_TEXT,
                },
                {
                    "stage": "supervisor_checkpoint",
                    "checkpoint": "matching_output",
                    "status": "passed",
                    "metrics": {
                        "candidate_count": 2,
                        "ranking_count": 2,
                        "evidence_count": 2,
                        "private_metric": PRIVATE_RESUME_TEXT,
                    },
                    "private_resume": PRIVATE_RESUME_TEXT,
                },
                {
                    "stage": "final_verification",
                    "private_resume": PRIVATE_RESUME_TEXT,
                    "metrics": {"candidate_count": 999},
                }
            ],
        }

    monkeypatch.setattr(runs, "get_run", completed)
    monkeypatch.setattr(runs, "load_state_snapshot", snapshot)

    with TestClient(_app()) as client:
        response = client.get("/api/v1/runs/run-1/conversation")

    assert response.status_code == 200
    serialized = response.text
    assert "normalized_base_resume" not in serialized
    assert "user_id" not in serialized
    assert "private-user-id" not in serialized
    assert PRIVATE_RESUME_TEXT not in serialized
    assert "小检返回了 2 个候选" in serialized
    assert "999 个候选" not in serialized
    assert "filter_log" not in serialized


def test_missing_snapshot_uses_count_free_architecture_handoff(monkeypatch) -> None:
    from app.api.v1 import runs

    async def running(**_kwargs):
        return _run(status=RunStatus.RUNNING, stage=RunStage.STRATEGY)

    async def missing_snapshot(**_kwargs):
        return None

    monkeypatch.setattr(runs, "get_run", running)
    monkeypatch.setattr(runs, "load_state_snapshot", missing_snapshot)

    with TestClient(_app()) as client:
        response = client.get("/api/v1/runs/run-1/conversation")

    handoff = next(
        message
        for message in response.json()["messages"]
        if message["persona"] == "pm"
        and message["kind"] == "checkpoint"
        and message["stage"] == "retrieval"
    )
    assert handoff["text"] == "小检已完成本轮检索，候选集已交给小策继续分析。"
    assert "个候选" not in handoff["text"]
    assert "排序记录" not in handoff["text"]
    assert "我核对了" not in handoff["text"]


@pytest.mark.parametrize(
    ("status", "metrics", "expected_count", "expected_metrics"),
    [
        ("passed", {}, None, None),
        (
            "warning",
            {"candidate_count": 0, "ranking_count": 0, "evidence_count": 0},
            "小检返回了 0 个候选",
            "排序记录 0 条、证据记录 0 条",
        ),
        (
            "passed",
            {"candidate_count": 4, "ranking_count": 3, "evidence_count": 2},
            "小检返回了 4 个候选",
            "排序记录 3 条、证据记录 2 条",
        ),
    ],
)
def test_matching_output_checkpoint_preserves_missing_zero_and_positive_counts(
    monkeypatch,
    status,
    metrics,
    expected_count,
    expected_metrics,
) -> None:
    from app.api.v1 import runs

    async def running(**_kwargs):
        return _run(status=RunStatus.RUNNING, stage=RunStage.STRATEGY)

    async def snapshot(**_kwargs):
        return {
            "supervisor_log": [
                {
                    "stage": "supervisor_checkpoint",
                    "checkpoint": "matching_input",
                    "status": "passed",
                    "metrics": {"top_k": 5},
                },
                {
                    "stage": "supervisor_checkpoint",
                    "checkpoint": "matching_output",
                    "status": status,
                    "metrics": metrics,
                },
            ]
        }

    monkeypatch.setattr(runs, "get_run", running)
    monkeypatch.setattr(runs, "load_state_snapshot", snapshot)

    with TestClient(_app()) as client:
        response = client.get("/api/v1/runs/run-1/conversation")

    handoff = next(
        message
        for message in response.json()["messages"]
        if message["persona"] == "pm"
        and message["kind"] == "checkpoint"
        and message["stage"] == "retrieval"
    )
    if expected_count is None:
        assert "个候选" not in handoff["text"]
        assert "排序记录" not in handoff["text"]
    else:
        assert expected_count in handoff["text"]
        assert expected_metrics in handoff["text"]
    if status == "warning":
        assert "检查带有提示" in handoff["text"]
        assert "我核对了候选集、排序与证据完整性" not in handoff["text"]
    else:
        assert "检查带有提示" not in handoff["text"]
        assert "我核对了候选集、排序与证据完整性" in handoff["text"]


def test_warning_matching_input_does_not_reuse_passed_handoff_copy(
    monkeypatch,
) -> None:
    from app.api.v1 import runs

    async def running(**_kwargs):
        return _run(status=RunStatus.RUNNING, stage=RunStage.RETRIEVAL)

    async def snapshot(**_kwargs):
        return {
            "supervisor_log": [
                {
                    "stage": "supervisor_checkpoint",
                    "checkpoint": "matching_input",
                    "status": "warning",
                    "metrics": {"top_k": 5},
                }
            ]
        }

    monkeypatch.setattr(runs, "get_run", running)
    monkeypatch.setattr(runs, "load_state_snapshot", snapshot)

    with TestClient(_app()) as client:
        response = client.get("/api/v1/runs/run-1/conversation")

    handoff = next(
        message
        for message in response.json()["messages"]
        if message["persona"] == "pm"
        and message["kind"] == "checkpoint"
        and message["stage"] == "intent"
    )
    assert handoff["kind"] == "checkpoint"
    assert "检索输入检查带有提示" in handoff["text"]
    assert "我确认小检接收的约束与确认单一致" not in handoff["text"]


def test_controlled_reretrieval_handoff_omits_ambiguous_checkpoint_counts(
    monkeypatch,
) -> None:
    from app.api.v1 import runs

    async def running(**_kwargs):
        return _run(status=RunStatus.RUNNING, stage=RunStage.VERIFICATION)

    async def snapshot(**_kwargs):
        return {
            "supervisor_log": [
                {
                    "stage": "supervisor_checkpoint",
                    "checkpoint": "matching_input",
                    "status": "passed",
                    "metrics": {"top_k": 5},
                },
                {
                    "stage": "supervisor_checkpoint",
                    "checkpoint": "matching_output",
                    "status": "passed",
                    "metrics": {
                        "candidate_count": 8,
                        "ranking_count": 8,
                        "evidence_count": 8,
                    },
                },
                {
                    "stage": "reretrieval_loop",
                    "reason": "too_few_results",
                    "loop_used": 1,
                    "max_loops": 1,
                },
            ]
        }

    monkeypatch.setattr(runs, "get_run", running)
    monkeypatch.setattr(runs, "load_state_snapshot", snapshot)

    with TestClient(_app()) as client:
        response = client.get("/api/v1/runs/run-1/conversation")

    handoff = next(
        message
        for message in response.json()["messages"]
        if message["persona"] == "pm"
        and message["kind"] == "checkpoint"
        and message["stage"] == "retrieval"
    )
    assert "8 个候选" not in handoff["text"]
    assert "排序记录 8 条" not in handoff["text"]
    assert "我核对了候选集、排序与证据完整性" in handoff["text"]


def test_remote_retrieval_copy_does_not_call_remote_a_sql_hard_filter(
    monkeypatch,
) -> None:
    from app.api.v1 import runs

    run = _run(status=RunStatus.RUNNING, stage=RunStage.RETRIEVAL)
    run.approved_plan["hard_constraints"] = {
        "remote": True,
        "locations": ["Birmingham"],
    }

    async def running(**_kwargs):
        return run

    async def snapshot(**_kwargs):
        return {
            "supervisor_log": [
                {
                    "stage": "supervisor_checkpoint",
                    "checkpoint": "matching_input",
                    "status": "passed",
                    "metrics": {"top_k": 5},
                }
            ]
        }

    monkeypatch.setattr(runs, "get_run", running)
    monkeypatch.setattr(runs, "load_state_snapshot", snapshot)

    with TestClient(_app()) as client:
        response = client.get("/api/v1/runs/run-1/conversation")

    scout = next(
        message
        for message in response.json()["messages"]
        if message["persona"] == "job_scout"
    )
    assert "你选择了远程方向，我按此筛选" in scout["text"]
    assert "远程方向" in scout["text"]
    assert "绝不放宽" not in scout["text"]
    assert "硬约束为" not in response.text
    assert "硬约束由数据库严格执行" not in response.text


def test_failed_conversation_translates_unknown_error_code(monkeypatch) -> None:
    from app.api.v1 import runs

    async def failed(**_kwargs):
        return _run(
            status=RunStatus.FAILED,
            stage=RunStage.RETRIEVAL,
            error_code="future_execution_error",
        )

    async def snapshot(**_kwargs):
        return {"supervisor_log": []}

    monkeypatch.setattr(runs, "get_run", failed)
    monkeypatch.setattr(runs, "load_state_snapshot", snapshot)

    with TestClient(_app()) as client:
        response = client.get("/api/v1/runs/run-1/conversation")

    assert response.status_code == 200
    payload = response.json()
    assert payload["next_poll_ms"] is None
    assert payload["messages"][-1]["kind"] == "error"
    assert payload["messages"][-1]["text"] == (
        "本次服务未能完成，请稍后重试或联系支持"
        "（代码：future_execution_error）。"
    )
