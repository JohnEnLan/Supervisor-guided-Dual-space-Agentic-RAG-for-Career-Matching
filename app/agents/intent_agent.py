from __future__ import annotations

import json
from typing import Any

from app.agents.base import BaseAgent
from app.domain.intent import CareerDirection, IntentConsultInput
from app.state.schema import SharedState


class IntentAgent(BaseAgent):
    name = "intent_agent"
    system_prompt = """
PHASE_C_INTENT_AGENT
You are the Intent & Career Profile Agent in a lightweight Agentic RAG system.
Extract the user's career intent from the normalized resume and the explicit user goal.
Separate hard constraints from soft preferences.

Return strict JSON with:
{
  "current_goal": [string],
  "long_term_goal": [string],
  "hard_constraints": {
    "location": string optional,
    "locations": [string] optional,
    "need_visa_sponsor": boolean optional,
    "max_years_exp": integer optional,
    "role_cluster": string optional,
    "role_clusters": [string] optional,
    "degree_required": string optional
  },
  "soft_preferences": {
    "preferred_locations": [string] optional,
    "preferred_role_clusters": [string] optional,
    "title_keywords": [string] optional
  },
  "avoid_roles": [string]
}
Do not invent constraints that the user did not state.
"""

    def __init__(self, user_goal_text: str):
        self.user_goal_text = user_goal_text

    def build_user_prompt(self, state: SharedState) -> str:
        resume = state.resume_state
        return json.dumps(
            {
                "user_goal_text": self.user_goal_text,
                "normalized_base_resume": resume.normalized_base_resume,
                "skills": resume.skills,
                "education": resume.education,
                "experience": resume.experience,
                "projects": resume.projects,
            },
            ensure_ascii=False,
        )

    def apply(self, state: SharedState, parsed: dict) -> SharedState:
        state.career_state.current_goal = _as_list(parsed.get("current_goal"))
        state.career_state.long_term_goal = _filter_long_term_goal(
            self.user_goal_text, _as_list(parsed.get("long_term_goal"))
        )
        state.career_state.hard_constraints = _filter_hard_constraints(
            _as_dict(parsed.get("hard_constraints"))
        )
        state.career_state.soft_preferences = _filter_soft_preferences(
            _as_dict(parsed.get("soft_preferences"))
        )
        state.career_state.avoid_roles = _as_list(parsed.get("avoid_roles"))
        return state


async def run_intent_agent(state: SharedState, user_goal_text: str) -> SharedState:
    return await IntentAgent(user_goal_text=user_goal_text).run(state)


class IntentConsultAgent(BaseAgent):
    name = "intent_consult_agent"
    system_prompt = """
VISIBLE_INTENT_CONSULT_AGENT
You help a user form or validate a career direction before matching.
Use only the supplied structured resume fields and resume evidence.

Return strict JSON with:
{
  "assistant_message": string,
  "current_goal": [string],
  "long_term_goal": [string],
  "hard_constraints": object,
  "soft_preferences": object,
  "avoid_roles": [string],
  "directions": [{
    "role_family": string,
    "title": string,
    "rationale": string,
    "resume_evidence_span_ids": [string],
    "primary_gap": string,
    "entry_role": string
  }],
  "needs_clarification": boolean,
  "clarification_question": string or null
}

For targeted mode, normalize target roles and separate hard constraints from
soft preferences. For explore mode, return at most three evidence-grounded
directions. Ask at most one clarification about location, visa sponsorship,
or acceptance of bridge roles. Do not invent resume evidence or promise a
hiring outcome.
"""

    def __init__(self, request: IntentConsultInput):
        self.request = request

    def build_user_prompt(self, state: SharedState) -> str:
        resume = state.resume_state
        return json.dumps(
            {
                "request": self.request.model_dump(mode="json"),
                "resume": {
                    "education": resume.education,
                    "experience": resume.experience,
                    "projects": resume.projects,
                    "skills": resume.skills,
                    "evidence": [
                        {
                            "span_id": span.get("span_id") or span.get("id"),
                            "text": span.get("text"),
                        }
                        for span in resume.original_evidence_spans
                        if span.get("span_id") or span.get("id")
                    ],
                },
            },
            ensure_ascii=False,
        )

    def apply(self, state: SharedState, parsed: dict) -> SharedState:
        career = state.career_state
        career.intent_mode = self.request.mode
        career.intent_assistant_message = str(
            parsed.get("assistant_message") or ""
        ).strip()
        career.current_goal = _as_list(parsed.get("current_goal"))
        career.long_term_goal = _filter_long_term_goal(
            self.request.goal_text or "",
            _as_list(parsed.get("long_term_goal")),
        )

        hard_constraints = _filter_hard_constraints(
            _as_dict(parsed.get("hard_constraints"))
        )
        hard_constraints.pop("companies", None)
        if self.request.company_exclusive and self.request.target_companies:
            hard_constraints["companies"] = list(self.request.target_companies)
        career.hard_constraints = hard_constraints

        soft_preferences = _filter_soft_preferences(
            _as_dict(parsed.get("soft_preferences"))
        )
        if self.request.target_companies:
            soft_preferences["preferred_companies"] = list(
                self.request.target_companies
            )
        career.soft_preferences = soft_preferences
        career.avoid_roles = _as_list(parsed.get("avoid_roles"))
        career.intent_directions = _validated_directions(
            parsed.get("directions")
        )

        if self.request.clarification_answer:
            career.intent_clarification_used = 1
        can_clarify = career.intent_clarification_used < 1
        career.intent_needs_clarification = bool(
            parsed.get("needs_clarification") and can_clarify
        )
        question = str(parsed.get("clarification_question") or "").strip()
        career.intent_clarification_question = (
            question if career.intent_needs_clarification and question else None
        )
        career.intent_consulted = not career.intent_needs_clarification
        return state


async def run_visible_intent_consultation(
    state: SharedState,
    request: IntentConsultInput,
) -> SharedState:
    if (
        request.clarification_answer
        and state.career_state.intent_clarification_used >= 1
    ):
        raise ValueError("clarification limit reached")
    return await IntentConsultAgent(request).run(state)


def _filter_hard_constraints(raw: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "location",
        "locations",
        "need_visa_sponsor",
        "max_years_exp",
        "role_cluster",
        "role_clusters",
        "degree_required",
        "companies",
    }
    cleaned = {key: value for key, value in raw.items() if key in allowed}
    if "locations" in cleaned:
        cleaned["locations"] = _as_list(cleaned["locations"])
    if "role_clusters" in cleaned:
        cleaned["role_clusters"] = _as_list(cleaned["role_clusters"])
    if "companies" in cleaned:
        cleaned["companies"] = _as_list(cleaned["companies"])
    if "max_years_exp" in cleaned and cleaned["max_years_exp"] is not None:
        cleaned["max_years_exp"] = int(cleaned["max_years_exp"])
    return {key: value for key, value in cleaned.items() if value not in (None, [], "")}


def _filter_soft_preferences(raw: dict[str, Any]) -> dict[str, Any]:
    allowed_list_fields = {
        "preferred_locations",
        "preferred_role_clusters",
        "preferred_companies",
        "title_keywords",
    }
    cleaned = {
        key: _as_list(value)
        for key, value in raw.items()
        if key in allowed_list_fields
    }
    return {key: value for key, value in cleaned.items() if value}


def _filter_long_term_goal(user_goal_text: str, values: list[Any]) -> list[Any]:
    if not _has_explicit_long_term_signal(user_goal_text):
        return []
    return values


def _has_explicit_long_term_signal(text: str) -> bool:
    normalized = text.casefold()
    markers = (
        "long-term",
        "long term",
        "longterm",
        "future goal",
        "career goal",
        "eventually",
        "in the future",
        "长期",
        "长远",
        "未来",
    )
    return any(marker in normalized for marker in markers)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _validated_directions(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    directions: list[dict[str, Any]] = []
    for item in value[:3]:
        if not isinstance(item, dict):
            continue
        try:
            direction = CareerDirection.model_validate(item)
        except ValueError:
            continue
        directions.append(direction.model_dump(mode="json"))
    return directions
