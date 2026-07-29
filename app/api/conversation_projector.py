from __future__ import annotations

import json
from collections import Counter
from typing import Any

from app.api.v1.schemas import ConversationMessageResponse
from app.domain.results import ProductResult
from app.domain.run import MatchRun, RunStage, RunStatus, TERMINAL_STATUSES


_STAGE_ORDER = {
    RunStage.PLAN: 0,
    RunStage.INTENT: 1,
    RunStage.RETRIEVAL: 2,
    RunStage.STRATEGY: 3,
    RunStage.VERIFICATION: 4,
    RunStage.FINALIZATION: 5,
}

_DISPLAY_NAMES = {
    "intent_consultant": "需求顾问·小意",
    "job_scout": "岗位顾问·小检",
    "strategist": "规划师·小策",
    "pm": "项目经理·PM",
}

_WARNING_TEXT = {
    "implicit_space_unavailable": (
        "隐式案例空间暂时不可用，本次结果仅依据显式岗位匹配生成。"
    ),
    "recommendation_missing_job_id": (
        "部分推荐因缺少岗位编号未发布，已从 Results 页结果中移除。"
    ),
    "no_publishable_recommendations": (
        "本次没有通过发布核查的岗位，请调整条件后重新尝试。"
    ),
    "invalid_resume_advice_dropped": (
        "部分格式不完整的简历建议未发布，其余可用建议不受影响。"
    ),
    "invalid_skill_gap_dropped": (
        "部分格式不完整的能力缺口未发布，其余分析不受影响。"
    ),
    "invalid_career_path_dropped": (
        "部分格式不完整的职业路径建议未发布，其余分析不受影响。"
    ),
}

_ERROR_TEXT = {
    "run_execution_failed": (
        "本次服务在执行过程中出现异常，请稍后重试或联系支持"
        "（代码：run_execution_failed）。"
    ),
    "run_cancelled": "本次服务已取消（代码：run_cancelled）。",
}


def project_run_conversation(
    *,
    run: MatchRun,
    recovery_events: list[dict[str, Any]],
    result: ProductResult | None,
) -> list[ConversationMessageResponse]:
    """Project public run data into a deterministic conversation timeline."""
    messages: list[ConversationMessageResponse] = []

    def add(
        persona: str,
        kind: str,
        text: str,
        stage: str,
    ) -> None:
        messages.append(
            ConversationMessageResponse(
                seq=len(messages) + 1,
                persona=persona,
                display_name=_DISPLAY_NAMES[persona],
                kind=kind,
                text=text,
                stage=stage,
            )
        )

    add(
        "pm",
        "intro",
        (
            "欢迎来到职业规划服务群。我是项目经理 PM，本次由需求顾问小意、"
            "岗位顾问小检和规划师小策协作，依次完成需求确认、岗位检索、"
            "策略规划与发布核查。我们会如实说明匹配依据与限制，建议不代表"
            " offer 承诺。"
        ),
        "intent",
    )

    if _has_reached(run, RunStage.INTENT):
        add(
            "intent_consultant",
            "brief",
            _brief_message(run.approved_plan),
            "intent",
        )

    if _has_reached(run, RunStage.RETRIEVAL):
        add(
            "job_scout",
            "progress",
            (
                "岗位检索正在执行：SQL 硬过滤 → BM25/Dense 并行 → "
                "job_id 级 RRF 融合。硬约束由数据库严格执行，"
                "不会交给模型猜测。"
            ),
            "retrieval",
        )
    if _has_completed_stage(run, RunStage.RETRIEVAL):
        candidate_text = (
            f"，最终形成 {len(result.recommended_roles)} 个可发布候选岗位"
            if result is not None
            else ""
        )
        add(
            "job_scout",
            "progress",
            f"检索与融合已完成{candidate_text}，现已交给规划师继续分析。",
            "retrieval",
        )

    if _has_reached(run, RunStage.STRATEGY):
        add(
            "strategist",
            "progress",
            (
                "我正在基于候选岗位开展能力缺口分析，并生成有证据约束的"
                "简历建议与职业路径；所有建议只基于已核验信息，"
                "不补写未经证实的经历。"
            ),
            "strategy",
        )
    if _has_completed_stage(run, RunStage.STRATEGY):
        add(
            "strategist",
            "progress",
            "缺口分析与简历建议已生成，现提交 PM 做最终发布核查。",
            "strategy",
        )

    if _has_reached(run, RunStage.VERIFICATION):
        add(
            "pm",
            "checkpoint",
            (
                "进入最终核查检查点：检查硬约束、JD/简历证据可追溯性、"
                "建议可执行性与结果完整性。必要时只允许一次受控重检索"
                "或修复。"
            ),
            "verification",
        )
        for event in recovery_events:
            event_stage = event.get("stage")
            if event_stage == "reretrieval_loop":
                add(
                    "pm",
                    "recovery",
                    (
                        "核查发现候选覆盖仍需加强，触发了一次受控重检索"
                        "（有界，最多一次）。"
                    ),
                    "verification",
                )
            elif event_stage == "repair_loop":
                add(
                    "pm",
                    "recovery",
                    (
                        "核查发现发布内容需要校正，触发了一次受控修复"
                        "（有界，最多一次）。"
                    ),
                    "verification",
                )

    warning_codes = _warning_codes(run, result)
    if run.status in {RunStatus.COMPLETED, RunStatus.COMPLETED_WITH_WARNINGS}:
        tier_counts = _tier_counts(result)
        add(
            "pm",
            "result",
            (
                "本次规划已完成："
                f"Now Fit {tier_counts['now_fit']} 个、"
                f"Stretch Fit {tier_counts['stretch_fit']} 个、"
                f"Bridge Role {tier_counts['bridge_role']} 个；"
                f"warning {len(warning_codes)} 项。"
                "请前往 Results 页查看岗位证据、缺口分析、简历建议与"
                "职业路径详情。匹配结果仅供求职决策参考，不构成 offer 承诺。"
            ),
            "result",
        )
        for code in warning_codes:
            add("pm", "warning", _warning_message(code), "result")
    elif run.status in TERMINAL_STATUSES:
        for code in warning_codes:
            add("pm", "warning", _warning_message(code), "result")
        add(
            "pm",
            "error",
            _terminal_error_message(run.status, run.error_code),
            run.stage.value if run.stage is not None else "result",
        )

    return messages


def _has_reached(run: MatchRun, stage: RunStage) -> bool:
    if run.stage is None:
        return False
    return _STAGE_ORDER[run.stage] >= _STAGE_ORDER[stage]


def _has_completed_stage(run: MatchRun, stage: RunStage) -> bool:
    if run.stage is None:
        return False
    return _STAGE_ORDER[run.stage] > _STAGE_ORDER[stage]


def _brief_message(approved_plan: dict[str, Any]) -> str:
    career_goal = str(approved_plan.get("career_goal") or "待确认").strip()
    hard_constraints = _format_public_value(
        approved_plan.get("hard_constraints"),
        empty_text="无额外限制",
    )
    soft_preferences = _format_public_value(
        approved_plan.get("soft_preferences"),
        empty_text="无额外偏好",
    )
    avoid_roles = _format_public_value(
        approved_plan.get("avoid_roles"),
        empty_text="无",
    )
    result_count = approved_plan.get("result_count") or 5
    return (
        f"我已复核本次 Match Brief：目标是“{career_goal}”。"
        f"硬约束为 {hard_constraints}，已锁定并将由 SQL/metadata 严格过滤；"
        f"软偏好为 {soft_preferences}，用于排序加权；"
        f"暂不考虑的岗位为 {avoid_roles}；计划返回最多 {result_count} 个结果。"
    )


def _format_public_value(value: Any, *, empty_text: str) -> str:
    if value in (None, "", [], {}):
        return empty_text
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _warning_codes(
    run: MatchRun,
    result: ProductResult | None,
) -> list[str]:
    values = list(run.warning_codes)
    if result is not None:
        values.extend(result.warnings)
    return list(dict.fromkeys(str(value) for value in values if value))


def _tier_counts(result: ProductResult | None) -> Counter[str]:
    if result is None:
        return Counter()
    return Counter(role.tier for role in result.recommended_roles)


def _warning_message(code: str) -> str:
    if code in _WARNING_TEXT:
        return _WARNING_TEXT[code]
    if code.startswith("hard_constraint_failed:"):
        job_id = code.partition(":")[2]
        return f"岗位 {job_id} 未通过硬约束核查，已从发布结果中移除。"
    if code.startswith("recommendation_missing_jd_evidence:"):
        job_id = code.partition(":")[2]
        return f"岗位 {job_id} 缺少可追溯的 JD 证据，已从发布结果中移除。"
    return (
        "本次服务带有一项系统提示，请在 Results 页核对详情"
        f"（代码：{code}）。"
    )


def _terminal_error_message(
    status: RunStatus,
    error_code: str | None,
) -> str:
    if error_code in _ERROR_TEXT:
        return _ERROR_TEXT[error_code]
    if error_code:
        return (
            "本次服务未能完成，请稍后重试或联系支持"
            f"（代码：{error_code}）。"
        )
    if status is RunStatus.CANCELLED:
        return "本次服务已取消。"
    if status is RunStatus.STALE:
        return "本次服务已超过可恢复时限，请重新提交任务。"
    return "本次服务未能完成，请稍后重试或联系支持。"
