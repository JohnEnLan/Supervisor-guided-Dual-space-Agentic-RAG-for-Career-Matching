from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import json
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
ChatFunction = Callable[..., Awaitable[str]]
MAX_USER_MESSAGE_CHARS = 2_000
TRANSCRIPT_CONTEXT_ROUNDS = 4
HARD_MAX_CONSULT_ROUNDS = 15
# LLM 坏输出的有界重试次数（总尝试数，含首次）
CONSULT_LLM_ATTEMPTS = 2

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

    @field_validator("assistant_reply", "next_question")
    @classmethod
    def strip_nonempty_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("consultation text must not be blank")
        return stripped


@dataclass(frozen=True)
class ConsultTurn:
    assistant_reply: str
    next_question: str
    phase: ConsultPhase
    completeness: float
    can_finalize: bool
    round: int
    profile_draft: dict[str, Any]


def format_consult_prompt(phase: ConsultPhase) -> str:
    return CONSULT_PROMPT.replace("{phase}", phase)


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
    career: CareerState,
    *,
    mode: ConsultMode,
) -> ConsultPhase:
    if not can_finalize(career):
        return "template"
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
    max_chars: int | None = None,
) -> str:
    bounded_message = str(message).strip()[:MAX_USER_MESSAGE_CHARS]
    payload = {
        "phase": phase,
        "user_message": bounded_message,
        "profile_summary": profile_draft(state.career_state),
        "next_template_slot": _next_template_slot(state.career_state),
        "recent_transcript": state.career_state.consult_transcript[
            -TRANSCRIPT_CONTEXT_ROUNDS:
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
    chat: ChatFunction | None = None,
) -> ConsultTurn:
    career = state.career_state
    configured_limit = (
        settings.max_consult_rounds if max_rounds is None else int(max_rounds)
    )
    round_limit = min(max(configured_limit, 1), HARD_MAX_CONSULT_ROUNDS)
    if career.consult_rounds_used >= round_limit:
        raise ConsultRoundLimitReached("consultation round limit reached")

    phase = determine_phase(career, mode=mode)
    bounded_message = str(message).strip()[:MAX_USER_MESSAGE_CHARS]
    remembered_draft = _remembered_profile_draft(remembered_profile)
    showing_remembered_draft = bool(
        career.consult_rounds_used == 0 and remembered_draft
    )
    user_prompt = build_consult_user_prompt(
        state,
        message=bounded_message,
        phase=phase,
        remembered_profile=remembered_draft,
    )
    chat_function = chat or deepseek.chat
    # 真实 LLM 偶发一次坏输出不该直接把 502 甩给用户：有界重试一次，
    # 两次都不合法才报错（重试只覆盖 LLM 调用与解析，state 尚未被改动）。
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
    next_round = career.consult_rounds_used + 1
    career.consult_rounds_used = next_round
    career.consult_transcript.append(
        {
            "round": next_round,
            "user_message": bounded_message,
            "assistant_reply": parsed.assistant_reply.strip(),
            "next_question": parsed.next_question.strip(),
            "phase": phase,
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
        phase=phase,
        completeness=calculate_completeness(career),
        can_finalize=can_finalize(career),
        round=next_round,
        profile_draft=profile_draft(career),
    )


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
