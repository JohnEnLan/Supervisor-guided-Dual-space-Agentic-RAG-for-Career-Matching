from __future__ import annotations

from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import dataclass
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.agents.base import coerce_dict, coerce_list
from app.agents.intent_agent import (
    _filter_hard_constraints,
    _filter_long_term_goal,
    _filter_soft_preferences,
)
from app.config import settings
from app.llm import deepseek
from app.llm.context_budget import fit_user_prompt_to_budget
from app.state.schema import CareerState, SharedState


ConsultPhase = Literal["template", "resume_clarify", "deepen", "explore"]
ConsultMode = Literal["targeted", "explore"]
ClarificationAction = Literal["answered", "skip_current", "skip_remaining"]
ChatFunction = Callable[..., Awaitable[str]]
MAX_USER_MESSAGE_CHARS = 2_000
TRANSCRIPT_CONTEXT_ROUNDS = 4
HARD_MAX_CONSULT_ROUNDS = 15
# LLM 坏输出的有界重试次数（总尝试数，含首次）
CONSULT_LLM_ATTEMPTS = 2
_SUMMARY_FALLBACK_CHARS = 240
_SKIP_RESIDUAL_CHARS = 8

CONSULT_PROMPT = """PHASE_C2_CONSULT_ADVISOR
You are a warm, professional career consultant in a group chat. Current consultation phase: {phase} (template=structured slot questions; deepen=targeted follow-ups on given answers; explore=divergent career-development coaching). Ask exactly ONE heuristic question per turn, in Chinese, warm and concise (question max 80 Chinese characters). Never invent facts about the user. Extract profile updates ONLY from what the user actually said.
Return strict JSON:
{
  "assistant_reply": string (Chinese empathetic reflection, max 120 Chinese characters),
  "next_question": string,
  "profile_updates": {
    "current_goal": [string] (the role or direction the user wants NOW, e.g. ["后端工程师"]),
    "long_term_goal": [string],
    "hard_constraints": {"locations": [string], "role_clusters": [string], "companies": [string], "need_visa_sponsor": boolean, "remote": boolean, "degree_required": string, "work_mode": string, "max_years_exp": integer},
    "soft_preferences": {"preferred_locations": [string], "preferred_role_clusters": [string], "preferred_companies": [string], "title_keywords": [string]},
    "avoid_roles": [string]
  },
  Use EXACTLY these key names inside hard_constraints and soft_preferences; include only keys the user actually stated (e.g. 不需要签证担保 -> "need_visa_sponsor": false; 想去科技大厂 -> "preferred_companies" or "title_keywords"). Unknown or renamed keys will be discarded.
  role_clusters / preferred_role_clusters values MUST come from this fixed vocabulary: software_engineering, data_ai, product_management, marketing_sales, healthcare, legal, education, operations, finance, customer_support. Map the user's wording onto it (e.g. 后端开发/平台工程 -> software_engineering; 数据分析/算法 -> data_ai). Keep the user's literal role words in current_goal and put useful English search words into title_keywords (e.g. ["backend", "platform"]).
  "phase_suggestion": "template" | "deepen" | "explore"
}"""

_CONSULT_CLARIFY_PROMPT_SUFFIX = """

RESUME_CLARIFY branch (active only when the server supplies clarification_context):
- answer_target is target T whose answer must be extracted from the current user_message.
- question_target is target T+1. Ask one concrete question about T+1 and cite its supplied resume evidence. Never bind T's answer to T+1.
- answer_summary is optional and MUST be extractive: reuse only content words that occur in the user's raw answer; do not paraphrase or infer.
- clarification_action is optional and must be one of: answered | skip_current | skip_remaining.
- If extraction is uncertain, omit both optional fields; the target remains open and the turn must still succeed.
Add only these optional top-level JSON fields:
  "answer_summary": string,
  "clarification_action": "answered" | "skip_current" | "skip_remaining"
When clarification_action is skip_remaining, do not ask another resume clarification question.
"""


class ConsultError(ValueError):
    pass


class ConsultRoundLimitReached(ConsultError):
    pass


class ConsultResponseError(ConsultError):
    pass


class _ConsultProfileUpdates(BaseModel):
    model_config = ConfigDict(extra="ignore")

    current_goal: list[str] = Field(default_factory=list)
    long_term_goal: list[str] = Field(default_factory=list)
    hard_constraints: dict[str, Any] = Field(default_factory=dict)
    soft_preferences: dict[str, Any] = Field(default_factory=dict)
    avoid_roles: list[str] = Field(default_factory=list)


class _ConsultLLMResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    assistant_reply: str = Field(min_length=1, max_length=120)
    next_question: str = Field(min_length=1, max_length=80)
    profile_updates: _ConsultProfileUpdates = Field(
        default_factory=_ConsultProfileUpdates
    )
    phase_suggestion: ConsultPhase
    answer_summary: str | None = None
    clarification_action: ClarificationAction | None = None

    @field_validator("assistant_reply", "next_question")
    @classmethod
    def strip_nonempty_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("consultation text must not be blank")
        return stripped

    @field_validator("answer_summary", mode="before")
    @classmethod
    def tolerate_invalid_optional_summary(cls, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        stripped = value.strip()
        return stripped[:_SUMMARY_FALLBACK_CHARS] or None

    @field_validator("clarification_action", mode="before")
    @classmethod
    def tolerate_invalid_optional_action(
        cls, value: Any
    ) -> ClarificationAction | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip().casefold()
        if normalized not in {"answered", "skip_current", "skip_remaining"}:
            return None
        return normalized


@dataclass(frozen=True)
class ConsultTurn:
    assistant_reply: str
    next_question: str
    phase: ConsultPhase
    completeness: float
    can_finalize: bool
    round: int
    profile_draft: dict[str, Any]
    # Internal Feature-A facts. API response assembly deliberately selects only
    # public DTO fields, so these never change OpenAPI or response payloads.
    pending_clarification_at_round_start: bool = False
    issued_clarification_question: bool = False
    clarification_turn_active: bool = False
    clarification_target_refs: tuple[str, ...] = ()
    clarification_action: ClarificationAction | None = None
    clarification_raw_answer: str | None = None
    clarification_answer_summary: str | None = None


def format_consult_prompt(phase: ConsultPhase) -> str:
    baseline = CONSULT_PROMPT.replace("{phase}", phase)
    if not settings.resume_clarify_enabled:
        return baseline
    return f"{baseline}{_CONSULT_CLARIFY_PROMPT_SUFFIX}"


def can_finalize(career: CareerState) -> bool:
    return _required_slots_filled(career) == 3


def calculate_completeness(career: CareerState) -> float:
    required_score = _required_slots_filled(career) / 3 * 0.6
    preference_count = sum(
        1
        for value in career.soft_preferences.values()
        if value not in (None, "", [], {})
    )
    preference_score = min(preference_count, 4) / 4 * 0.4
    return round(required_score + preference_score, 6)


def determine_phase(
    state_or_career: SharedState | CareerState,
    *,
    mode: ConsultMode,
) -> ConsultPhase:
    state = state_or_career if isinstance(state_or_career, SharedState) else None
    career = state.career_state if state is not None else state_or_career
    if not can_finalize(career):
        return "template"
    if (
        settings.resume_clarify_enabled
        and state is not None
        and state.resume_state.questions_used < settings.resume_clarify_max
        and _next_open_clarification_target(state) is not None
    ):
        return "resume_clarify"
    if mode == "explore":
        return "explore"
    preference_count = sum(
        1
        for value in career.soft_preferences.values()
        if value not in (None, "", [], {})
    )
    if preference_count < 2 or not _has_avoid_roles_statement(career):
        return "deepen"
    return "explore"


def profile_draft(career: CareerState) -> dict[str, Any]:
    return {
        "current_goal": list(career.current_goal),
        "long_term_goal": list(career.long_term_goal),
        "hard_constraints": dict(career.hard_constraints),
        "soft_preferences": dict(career.soft_preferences),
        "avoid_roles": list(career.avoid_roles),
    }


def build_brief_draft(
    career: CareerState,
    *,
    result_count: int = 5,
) -> dict[str, Any]:
    if not can_finalize(career):
        raise ConsultError("consultation profile is incomplete")
    current_goal = "、".join(_clean_strings(career.current_goal))
    career_goal = f"希望匹配的职业方向：{current_goal}"
    long_term_goal = "、".join(_clean_strings(career.long_term_goal))
    if long_term_goal:
        career_goal = f"{career_goal}；长期方向：{long_term_goal}"
    return {
        "career_goal": career_goal,
        "hard_constraints": dict(career.hard_constraints),
        "soft_preferences": dict(career.soft_preferences),
        "avoid_roles": list(career.avoid_roles),
        "result_count": result_count,
    }


def build_consult_user_prompt(
    state: SharedState,
    *,
    message: str,
    phase: ConsultPhase,
    remembered_profile: dict[str, Any] | None = None,
    answer_target: dict[str, Any] | None = None,
    question_target: dict[str, Any] | None = None,
    max_chars: int | None = None,
) -> str:
    bounded_message = str(message).strip()[:MAX_USER_MESSAGE_CHARS]
    payload = {
        "phase": phase,
        "user_message": bounded_message,
        "profile_summary": profile_draft(state.career_state),
        "next_template_slot": _next_template_slot(state.career_state),
        "recent_transcript": [
            {
                key: deepcopy(value)
                for key, value in entry.items()
                if key != "supervisor_notes"
            }
            for entry in state.career_state.consult_transcript[
                -TRANSCRIPT_CONTEXT_ROUNDS:
            ]
            if isinstance(entry, dict)
        ],
    }
    remembered_draft = _remembered_profile_draft(remembered_profile)
    if state.career_state.consult_rounds_used == 0 and remembered_draft:
        payload["remembered_profile_draft"] = {
            "source": "user_profiles",
            "requires_confirmation": True,
            "profile": remembered_draft,
        }
        payload["remembered_profile_instruction"] = (
            "Present this source-labeled draft and ask the user to confirm it. "
            "Do not copy remembered values into profile_updates this turn."
        )
    if settings.resume_clarify_enabled and (answer_target or question_target):
        clarification_context: dict[str, Any] = {}
        if answer_target:
            clarification_context["answer_target"] = _target_prompt_payload(
                state,
                answer_target,
            )
        if question_target:
            clarification_context["question_target"] = _target_prompt_payload(
                state,
                question_target,
            )
        payload["clarification_context"] = clarification_context
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return fit_user_prompt_to_budget(
        serialized,
        max_chars=max_chars or settings.llm_user_prompt_max_chars,
    )


async def run_consult_round(
    state: SharedState,
    *,
    mode: ConsultMode,
    message: str,
    max_rounds: int | None = None,
    remembered_profile: dict[str, Any] | None = None,
    resume_version: int = 0,
    chat: ChatFunction | None = None,
) -> ConsultTurn:
    career = state.career_state
    configured_limit = (
        settings.max_consult_rounds if max_rounds is None else int(max_rounds)
    )
    round_limit = min(max(configured_limit, 1), HARD_MAX_CONSULT_ROUNDS)
    if career.consult_rounds_used >= round_limit:
        raise ConsultRoundLimitReached("consultation round limit reached")

    bounded_message = str(message).strip()[:MAX_USER_MESSAGE_CHARS]
    pending_at_round_start = bool(
        settings.resume_clarify_enabled
        and state.resume_state.pending_clarification_question
    )
    answer_target: dict[str, Any] | None = None
    question_target: dict[str, Any] | None = None
    processed_target_refs: tuple[str, ...] = ()
    processed_action: ClarificationAction | None = None
    deterministic_skip: ClarificationAction | None = None
    if settings.resume_clarify_enabled:
        pending = state.resume_state.pending_clarification_question
        pending_target = _pending_open_target(state)
        deterministic_skip = detect_clarification_skip(
            bounded_message,
            has_pending=pending_target is not None,
        )
        if deterministic_skip is not None and pending_target is not None:
            processed_target_refs = _apply_clarification_action(
                state,
                target_ref=str(pending_target["target_ref"]),
                action=deterministic_skip,
            )
            processed_action = deterministic_skip
            state.resume_state.pending_clarification_question = None
            phase = determine_phase(state, mode=mode)
            if phase == "resume_clarify":
                question_target = _next_open_clarification_target(state)
        elif pending is not None and pending_target is not None:
            answer_target = dict(pending_target)
            provisional = state.model_copy(deep=True)
            provisional_target = _pending_open_target(provisional)
            if provisional_target is not None:
                provisional_target["status"] = "answered"
            provisional.resume_state.pending_clarification_question = None
            phase = determine_phase(provisional, mode=mode)
            if phase == "resume_clarify":
                question_target = _next_open_clarification_target(provisional)
        else:
            phase = determine_phase(state, mode=mode)
            if phase == "resume_clarify":
                question_target = _next_open_clarification_target(state)
    else:
        phase = determine_phase(career, mode=mode)
    remembered_draft = _remembered_profile_draft(remembered_profile)
    showing_remembered_draft = bool(
        career.consult_rounds_used == 0 and remembered_draft
    )
    user_prompt = build_consult_user_prompt(
        state,
        message=bounded_message,
        phase=phase,
        remembered_profile=remembered_draft,
        answer_target=answer_target,
        question_target=question_target,
    )
    chat_function = chat or deepseek.chat
    # 真实 LLM 偶发一次坏输出不该直接把 502 甩给用户：有界重试一次，
    # 两次都不合法才报错。调用方传入的是工作副本，因此失败轮不会持久化；
    # 确定性 skip 可能已先更新该副本，以满足“先 skip、再重算 phase”的顺序。
    parsed: _ConsultLLMResponse | None = None
    merged_career: CareerState | None = None
    last_error: Exception | None = None
    for _attempt in range(CONSULT_LLM_ATTEMPTS):
        try:
            raw = await chat_function(
                format_consult_prompt(phase),
                user_prompt,
                json_mode=True,
            )
            candidate = _ConsultLLMResponse.model_validate(
                deepseek.extract_json_response(raw)
            )
        except (json.JSONDecodeError, TypeError, ValidationError) as exc:
            last_error = exc
            continue
        if showing_remembered_draft:
            parsed = candidate
            break
        attempt_career = career.model_copy(deep=True)
        try:
            _merge_profile_updates(
                attempt_career,
                updates=candidate.profile_updates.model_dump(),
                user_message=bounded_message,
            )
        except (TypeError, ValueError) as exc:
            last_error = exc
            continue
        parsed = candidate
        merged_career = attempt_career
        break
    if parsed is None:
        raise ConsultResponseError("invalid consultation response") from last_error

    if merged_career is not None:
        for field_name in (
            "current_goal",
            "long_term_goal",
            "hard_constraints",
            "soft_preferences",
            "avoid_roles",
        ):
            setattr(career, field_name, getattr(merged_career, field_name))
    answer_summary: str | None = None
    if (
        settings.resume_clarify_enabled
        and answer_target is not None
        and deterministic_skip is None
        and parsed.clarification_action is not None
    ):
        processed_action = parsed.clarification_action
        processed_target_refs = _apply_clarification_action(
            state,
            target_ref=str(answer_target["target_ref"]),
            action=processed_action,
        )
        state.resume_state.pending_clarification_question = None
        if processed_action == "answered":
            answer_summary = validated_answer_summary(
                parsed.answer_summary,
                bounded_message,
            )

    next_round = career.consult_rounds_used + 1
    issued_clarification_question = False
    recorded_phase = phase
    if settings.resume_clarify_enabled:
        phase_after_action = determine_phase(state, mode=mode)
        if processed_action == "skip_remaining":
            recorded_phase = phase_after_action
        if (
            state.resume_state.pending_clarification_question is None
            and phase_after_action == "resume_clarify"
            and phase == "resume_clarify"
            and question_target is not None
        ):
            latest_question_target = _target_by_ref(
                state,
                str(question_target.get("target_ref") or ""),
            )
            if latest_question_target is not None and latest_question_target.get(
                "status"
            ) == "open":
                state.resume_state.questions_used += 1
                state.resume_state.pending_clarification_question = {
                    "target_ref": str(latest_question_target["target_ref"]),
                    "asked_round": next_round,
                    "baseline_version": int(resume_version),
                }
                issued_clarification_question = True
    career.consult_rounds_used = next_round
    career.consult_transcript.append(
        {
            "round": next_round,
            "user_message": bounded_message,
            "assistant_reply": parsed.assistant_reply.strip(),
            "next_question": parsed.next_question.strip(),
            "phase": recorded_phase,
        }
    )
    career.intent_mode = mode
    career.intent_assistant_message = parsed.assistant_reply.strip()
    career.intent_clarification_used = min(next_round, 1)
    career.intent_needs_clarification = not can_finalize(career)
    career.intent_clarification_question = (
        parsed.next_question.strip()
        if career.intent_needs_clarification
        else None
    )
    career.intent_consulted = False

    return ConsultTurn(
        assistant_reply=parsed.assistant_reply.strip(),
        next_question=parsed.next_question.strip(),
        phase=recorded_phase,
        completeness=calculate_completeness(career),
        can_finalize=can_finalize(career),
        round=next_round,
        profile_draft=profile_draft(career),
        pending_clarification_at_round_start=pending_at_round_start,
        issued_clarification_question=issued_clarification_question,
        clarification_turn_active=(
            pending_at_round_start or issued_clarification_question
        ),
        clarification_target_refs=processed_target_refs,
        clarification_action=processed_action,
        clarification_raw_answer=(
            bounded_message if processed_action == "answered" else None
        ),
        clarification_answer_summary=answer_summary,
    )


def detect_clarification_skip(
    message: str,
    *,
    has_pending: bool,
) -> ClarificationAction | None:
    if not has_pending:
        return None
    normalized = str(message).strip().casefold()
    remaining_phrases = (
        "剩余全部跳过",
        "剩下全部跳过",
        "全部跳过",
        "都跳过",
        "都不补充",
        "skip all",
    )
    current_phrases = (
        "先不补充",
        "不想说",
        "下一个",
        "跳过",
        "skip",
    )
    action: ClarificationAction | None = None
    matched: list[str] = []
    for phrase in remaining_phrases:
        if phrase in normalized:
            action = "skip_remaining"
            matched.append(phrase)
    if action is None:
        for phrase in current_phrases:
            if phrase in normalized:
                action = "skip_current"
                matched.append(phrase)
    if action is None:
        return None
    residual = normalized
    for phrase in sorted(set(matched), key=len, reverse=True):
        residual = residual.replace(phrase, "")
    residual = re.sub(r"[^\w\u4e00-\u9fff]+", "", residual)
    return action if len(residual) < _SKIP_RESIDUAL_CHARS else None


def validated_answer_summary(summary: Any, raw_answer: str) -> str:
    bounded_raw = str(raw_answer).strip()[:MAX_USER_MESSAGE_CHARS]
    candidate = str(summary).strip() if isinstance(summary, str) else ""
    candidate = candidate[:_SUMMARY_FALLBACK_CHARS]
    summary_tokens = _content_tokens(candidate)
    raw_tokens = _content_tokens(bounded_raw)
    if candidate and summary_tokens and summary_tokens.issubset(raw_tokens):
        return candidate
    return bounded_raw[:_SUMMARY_FALLBACK_CHARS]


def _content_tokens(value: str) -> set[str]:
    tokens: set[str] = set()
    for chunk in re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]+", value.casefold()):
        if re.fullmatch(r"[A-Za-z0-9]+", chunk):
            if len(chunk) > 1:
                tokens.add(chunk)
            continue
        cleaned = "".join(char for char in chunk if char not in "我的了和与并在将把是")
        if len(cleaned) == 1:
            tokens.add(cleaned)
        else:
            tokens.update(
                cleaned[index : index + 2]
                for index in range(len(cleaned) - 1)
            )
    return tokens


def _apply_clarification_action(
    state: SharedState,
    *,
    target_ref: str,
    action: ClarificationAction,
) -> tuple[str, ...]:
    affected: list[str] = []
    if action == "skip_remaining":
        for target in state.resume_state.clarification_targets:
            if target.get("status") != "open":
                continue
            target["status"] = "skipped"
            affected.append(str(target.get("target_ref") or ""))
        return tuple(ref for ref in affected if ref)
    target = _target_by_ref(state, target_ref)
    if target is None or target.get("status") != "open":
        return ()
    target["status"] = "answered" if action == "answered" else "skipped"
    return (target_ref,)


def _pending_open_target(state: SharedState) -> dict[str, Any] | None:
    pending = state.resume_state.pending_clarification_question
    if not isinstance(pending, dict):
        return None
    target = _target_by_ref(state, str(pending.get("target_ref") or ""))
    if target is None or target.get("status") != "open":
        return None
    return target


def _next_open_clarification_target(
    state: SharedState,
) -> dict[str, Any] | None:
    return next(
        (
            target
            for target in state.resume_state.clarification_targets
            if isinstance(target, dict) and target.get("status") == "open"
        ),
        None,
    )


def _target_by_ref(state: SharedState, target_ref: str) -> dict[str, Any] | None:
    return next(
        (
            target
            for target in state.resume_state.clarification_targets
            if isinstance(target, dict)
            and str(target.get("target_ref") or "") == target_ref
        ),
        None,
    )


def _target_prompt_payload(
    state: SharedState,
    target: dict[str, Any],
) -> dict[str, Any]:
    span_by_id = {
        str(span.get("span_id") or span.get("id") or ""): span
        for span in state.resume_state.original_evidence_spans
        if isinstance(span, dict)
    }
    evidence = [
        {
            "span_id": span_id,
            "text": str(span_by_id[span_id].get("text") or ""),
        }
        for raw_id in target.get("evidence_span_ids") or []
        if (span_id := str(raw_id)) in span_by_id
    ]
    return {
        "target_ref": str(target.get("target_ref") or ""),
        "field_path": str(target.get("field_path") or ""),
        "issue": str(target.get("issue") or ""),
        "evidence": evidence,
    }


def _required_slots_filled(career: CareerState) -> int:
    hard = career.hard_constraints
    current_goal = bool(_clean_strings(career.current_goal))
    locations = _is_nonempty_string_list(hard.get("locations"))
    remote = hard.get("remote") is True
    visa = isinstance(hard.get("need_visa_sponsor"), bool)
    return sum((current_goal, locations or remote, visa))


def _has_avoid_roles_statement(career: CareerState) -> bool:
    if _clean_strings(career.avoid_roles):
        return True
    markers = ("没有需要避开", "没有特别想避开", "无避开", "暂无避开")
    return any(
        marker in str(entry.get("user_message") or "")
        for entry in career.consult_transcript
        for marker in markers
    )


def _next_template_slot(career: CareerState) -> str | None:
    hard = career.hard_constraints
    if not _clean_strings(career.current_goal):
        return "current_goal"
    if not _clean_strings(hard.get("locations")) and hard.get("remote") is not True:
        return "locations_or_remote"
    if "need_visa_sponsor" not in hard or hard["need_visa_sponsor"] is None:
        return "need_visa_sponsor"
    if "max_years_exp" not in hard:
        return "max_years_exp"
    if "work_mode" not in hard:
        return "work_mode"
    if not _has_avoid_roles_statement(career):
        return "avoid_roles"
    return None


def _merge_profile_updates(
    career: CareerState,
    *,
    updates: dict[str, Any],
    user_message: str,
) -> None:
    raw = coerce_dict(updates)
    career.current_goal = _merge_strings(
        career.current_goal,
        coerce_list(raw.get("current_goal")),
    )
    long_term_updates = _filter_long_term_goal(
        user_message,
        coerce_list(raw.get("long_term_goal")),
    )
    career.long_term_goal = _merge_strings(
        career.long_term_goal,
        long_term_updates,
    )
    career.hard_constraints.update(
        _validated_consult_hard_constraints(
            coerce_dict(raw.get("hard_constraints"))
        )
    )
    career.soft_preferences.update(
        _validated_consult_soft_preferences(
            coerce_dict(raw.get("soft_preferences"))
        )
    )
    career.avoid_roles = _merge_strings(
        career.avoid_roles,
        coerce_list(raw.get("avoid_roles")),
    )


def _remembered_profile_draft(value: Any) -> dict[str, Any]:
    raw = coerce_dict(value)
    if not raw:
        return {}
    draft: dict[str, Any] = {}
    list_fields = ("current_goal", "long_term_goal", "avoid_roles")
    for field_name in list_fields:
        values = _clean_strings(raw.get(field_name))
        if values:
            draft[field_name] = values
    hard_constraints: dict[str, Any] = {}
    for key, item in coerce_dict(raw.get("hard_constraints")).items():
        try:
            hard_constraints.update(
                _validated_consult_hard_constraints({key: item})
            )
        except (TypeError, ValueError):
            continue
    if hard_constraints:
        draft["hard_constraints"] = hard_constraints
    soft_preferences: dict[str, Any] = {}
    for key, item in coerce_dict(raw.get("soft_preferences")).items():
        try:
            soft_preferences.update(
                _validated_consult_soft_preferences({key: item})
            )
        except (TypeError, ValueError):
            continue
    if soft_preferences:
        draft["soft_preferences"] = soft_preferences
    return draft


# 检索层 role_cluster 的受控词表（scripts/load_jobs.py 入库口径）。
# 词表外的簇值会让 SQL 硬过滤清空全部候选，必须在进 state 前丢弃。
ROLE_CLUSTER_VOCABULARY = frozenset(
    {
        "software_engineering",
        "data_ai",
        "product_management",
        "marketing_sales",
        "healthcare",
        "legal",
        "education",
        "operations",
        "finance",
        "customer_support",
        "other",
    }
)


def _filter_role_cluster_values(out: dict[str, Any], *keys: str) -> None:
    for key in keys:
        value = out.get(key)
        if _is_string_list(value):
            kept = [
                item.strip()
                for item in value
                if item.strip().lower() in ROLE_CLUSTER_VOCABULARY
            ]
            if kept:
                out[key] = kept
            else:
                out.pop(key)
        elif isinstance(value, str):
            if value.strip().lower() not in ROLE_CLUSTER_VOCABULARY:
                out.pop(key)


_HARD_SINGULAR_TO_PLURAL = {
    "location": "locations",
    "role_cluster": "role_clusters",
    "company": "companies",
}
_SOFT_SINGULAR_TO_PLURAL = {
    "preferred_location": "preferred_locations",
    "preferred_role_cluster": "preferred_role_clusters",
    "preferred_company": "preferred_companies",
    "title_keyword": "title_keywords",
}


def _canonicalize_llm_variants(
    raw: dict[str, Any],
    *,
    singular_to_plural: dict[str, str],
    list_fields: set[str],
) -> dict[str, Any]:
    # 真实 LLM 常把单数键写成字符串列表（如 location: ["上海","北京"]）、
    # 把复数键写成单个字符串；进白名单校验前先归一，避免整轮咨询报废。
    out = dict(raw)
    for singular, plural in singular_to_plural.items():
        value = out.get(singular)
        if _is_string_list(value):
            existing = out.get(plural)
            out[plural] = _merge_strings(
                existing if _is_string_list(existing) else [],
                value,
            )
            out.pop(singular)
    for key in list_fields:
        value = out.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = [value]
    return out


def _validated_consult_hard_constraints(
    raw: dict[str, Any],
) -> dict[str, Any]:
    list_fields = {"locations", "role_clusters", "companies"}
    raw = _canonicalize_llm_variants(
        raw,
        singular_to_plural=_HARD_SINGULAR_TO_PLURAL,
        list_fields=list_fields,
    )
    _filter_role_cluster_values(raw, "role_clusters", "role_cluster")
    string_fields = {
        "location",
        "role_cluster",
        "degree_required",
        "work_mode",
    }
    boolean_fields = {"need_visa_sponsor", "remote"}
    for key in list_fields & raw.keys():
        value = raw[key]
        if value is None:
            continue
        if not _is_string_list(value):
            raise ValueError(f"{key} must be a list of strings")
    for key in string_fields & raw.keys():
        value = raw[key]
        if value is not None and (
            not isinstance(value, str) or not value.strip()
        ):
            raise ValueError(f"{key} must be a non-empty string")
    for key in boolean_fields & raw.keys():
        value = raw[key]
        if value is not None and not isinstance(value, bool):
            raise ValueError(f"{key} must be a boolean")
    if "max_years_exp" in raw and raw["max_years_exp"] is not None:
        value = raw["max_years_exp"]
        if type(value) is not int or value < 0:
            raise ValueError("max_years_exp must be a non-negative integer")

    cleaned = _filter_hard_constraints(raw)
    for key in list_fields & cleaned.keys():
        cleaned[key] = [item.strip() for item in cleaned[key]]
    for key in string_fields & cleaned.keys():
        cleaned[key] = cleaned[key].strip()
    return cleaned


def _validated_consult_soft_preferences(
    raw: dict[str, Any],
) -> dict[str, Any]:
    allowed = {
        "preferred_locations",
        "preferred_role_clusters",
        "preferred_companies",
        "title_keywords",
    }
    raw = _canonicalize_llm_variants(
        raw,
        singular_to_plural=_SOFT_SINGULAR_TO_PLURAL,
        list_fields=allowed,
    )
    _filter_role_cluster_values(raw, "preferred_role_clusters")
    for key in allowed & raw.keys():
        value = raw[key]
        if value is None:
            continue
        if not _is_string_list(value):
            raise ValueError(f"{key} must be a list of strings")
    cleaned = _filter_soft_preferences(raw)
    return {
        key: [item.strip() for item in values]
        for key, values in cleaned.items()
    }


def _is_nonempty_string_list(value: Any) -> bool:
    return bool(value) and _is_string_list(value)


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, str) and bool(item.strip()) for item in value
    )


def _merge_strings(existing: list[Any], incoming: list[Any]) -> list[str]:
    merged = _clean_strings(existing)
    seen = set(merged)
    for value in _clean_strings(incoming):
        if value in seen:
            continue
        seen.add(value)
        merged.append(value)
    return merged


def _clean_strings(values: Any) -> list[str]:
    if not isinstance(values, list):
        values = [] if values is None else [values]
    return [text for value in values if (text := str(value).strip())]
