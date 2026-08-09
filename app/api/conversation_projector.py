from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
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

_SUMMARY_FIELD_LABELS = {
    "locations": "地点",
    "need_visa_sponsor": "签证担保",
    "preferred_locations": "偏好地点",
    "preferred_role_clusters": "岗位簇",
    "title_keywords": "关键词",
}


@dataclass(frozen=True)
class ConversationProjectionContext:
    """Privacy-safe checkpoint facts used by the conversation projector."""

    matching_input_status: str | None = None
    matching_output_status: str | None = None
    candidate_count: int | None = None
    ranking_count: int | None = None
    evidence_count: int | None = None


def project_run_conversation(
    *,
    run: MatchRun,
    recovery_events: list[dict[str, Any]],
    result: ProductResult | None,
    context: ConversationProjectionContext | None = None,
) -> list[ConversationMessageResponse]:
    """Project public run data into a deterministic conversation timeline."""
    messages: list[ConversationMessageResponse] = []
    projection_context = context or ConversationProjectionContext()

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
            "pm",
            "checkpoint",
            _matching_input_handoff(projection_context.matching_input_status),
            "intent",
        )
        add(
            "job_scout",
            "progress",
            _job_scout_start_message(run.approved_plan),
            "retrieval",
        )
    if _has_completed_stage(run, RunStage.RETRIEVAL):
        add(
            "job_scout",
            "progress",
            "检索与融合已完成，候选集已提交 PM 进行交接检查。",
            "retrieval",
        )
        add(
            "pm",
            "checkpoint",
            _matching_output_handoff(
                projection_context,
                include_counts=not _has_controlled_reretrieval(recovery_events),
            ),
            "retrieval",
        )

    if _has_reached(run, RunStage.STRATEGY):
        add(
            "strategist",
            "progress",
            (
                "我正在基于候选岗位开展能力缺口分析，并生成有证据约束的"
                "简历建议与职业路径；所有建议只引用简历原始证据和用户确认的澄清证据，"
                "不补写未经证实的经历。"
            ),
            "strategy",
        )
    if _has_completed_stage(run, RunStage.STRATEGY):
        add(
            "strategist",
            "progress",
            (
                "缺口分析与简历建议已生成，现提交 PM 做最终发布核查。"
                "如果你之后想让我基于某个岗位细化简历，可在结果卡提交反馈"
                "或开启新咨询。"
            ),
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
        for code in warning_codes:
            add("pm", "warning", _warning_message(code), "result")
        warnings_clause = (
            f"，另有 {len(warning_codes)} 条发布提示" if warning_codes else ""
        )
        add(
            "strategist",
            "result",
            (
                "岗位分析完成："
                f"Now Fit {tier_counts['now_fit']} 个、"
                f"Stretch Fit {tier_counts['stretch_fit']} 个、"
                f"Bridge Role {tier_counts['bridge_role']} 个"
                f"{warnings_clause}。下面把结果发给你，每个岗位都附证据与建议。"
            ),
            "result",
        )
        add(
            "pm",
            "result",
            (
                "结果已发布。投递后欢迎回来在对应岗位卡上提交进展（被拒/过筛/"
                "面试/Offer），这些反馈会帮助我们持续校准推荐。匹配结果仅供求职"
                "决策参考，不构成 offer 承诺。"
            ),
            "result",
        )
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
    hard_constraints = _format_summary(
        approved_plan.get("hard_constraints"),
        empty_text="无额外限制",
    )
    soft_preferences = _format_summary(
        approved_plan.get("soft_preferences"),
        empty_text="无额外偏好",
    )
    avoid_roles = _format_summary_value(approved_plan.get("avoid_roles")) or "无"
    return (
        f"本次需求已确认：目标「{career_goal}」；"
        f"硬条件——{hard_constraints}；"
        f"排序偏好——{soft_preferences}；"
        f"暂不考虑：{avoid_roles}。"
        "接下来小检会基于你的完整简历档案 + 以上条件开始检索。"
    )


def _job_scout_start_message(approved_plan: dict[str, Any]) -> str:
    message = (
        "我已接手确认单，岗位检索正在执行：适用的 metadata 条件筛选 → "
        "BM25/Dense 并行 → job_id 级 RRF 融合。"
    )
    hard_constraints = approved_plan.get("hard_constraints")
    if not isinstance(hard_constraints, Mapping):
        return message
    if hard_constraints.get("remote") is True:
        return f"{message}你选择了远程方向，我按此筛选。"
    locations = _format_locations(hard_constraints.get("locations"))
    if locations:
        return f"{message}你要求的 {locations} 我已锁定为硬条件，绝不放宽。"
    return message


def _format_locations(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, list):
        return ""
    return "、".join(
        location
        for item in value
        if (location := str(item).strip())
    )


def _matching_input_handoff(status: str | None) -> str:
    if status == "passed":
        return "我确认小检接收的约束与确认单一致，现交给小检执行。"
    if status == "warning":
        return (
            "小检接收的检索输入检查带有提示；确认单已交给小检继续执行，"
            "提示会保留供后续核查。"
        )
    return "需求确认阶段已完成，确认单已交给小检执行。"


def _matching_output_handoff(
    context: ConversationProjectionContext,
    *,
    include_counts: bool,
) -> str:
    count_text = "小检已完成本轮检索"
    metrics_text = ""
    if include_counts and context.candidate_count is not None:
        count_text = f"小检返回了 {context.candidate_count} 个候选"
    if (
        include_counts
        and context.ranking_count is not None
        and context.evidence_count is not None
    ):
        metrics_text = (
            f"（排序记录 {context.ranking_count} 条、"
            f"证据记录 {context.evidence_count} 条）"
        )

    if context.matching_output_status == "passed":
        return (
            f"{count_text}；我核对了候选集、排序与证据完整性"
            f"{metrics_text}，现交给小策。"
        )
    if context.matching_output_status == "warning":
        return (
            f"{count_text}；候选集、排序与证据完整性检查带有提示"
            f"{metrics_text}，现交给小策继续分析。"
        )
    return f"{count_text}，候选集已交给小策继续分析。"


def _has_controlled_reretrieval(
    recovery_events: list[dict[str, Any]],
) -> bool:
    return any(event.get("stage") == "reretrieval_loop" for event in recovery_events)


def _format_summary(value: Any, *, empty_text: str) -> str:
    if not isinstance(value, Mapping):
        return empty_text
    parts: list[str] = []
    for raw_key, raw_value in value.items():
        key = str(raw_key)
        if key == "need_visa_sponsor" and isinstance(raw_value, bool):
            parts.append("需要签证担保" if raw_value else "不需要签证担保")
            continue
        formatted_value = _format_summary_value(raw_value)
        if not formatted_value:
            continue
        parts.append(f"{_SUMMARY_FIELD_LABELS.get(key, key)} {formatted_value}")
    return "、".join(parts) or empty_text


def _format_summary_value(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, Mapping):
        return "、".join(
            f"{key} {formatted}"
            for key, item in value.items()
            if (formatted := _format_summary_value(item))
        )
    if isinstance(value, (list, tuple, set)):
        return "、".join(
            formatted
            for item in value
            if (formatted := _format_summary_value(item))
        )
    return str(value).strip()


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
