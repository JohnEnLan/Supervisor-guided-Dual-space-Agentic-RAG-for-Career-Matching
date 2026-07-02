from __future__ import annotations

import json
from typing import Any

from app.agents.base import BaseAgent
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
        state.career_state.long_term_goal = _as_list(parsed.get("long_term_goal"))
        state.career_state.hard_constraints = _filter_hard_constraints(
            _as_dict(parsed.get("hard_constraints"))
        )
        state.career_state.soft_preferences = _as_dict(parsed.get("soft_preferences"))
        state.career_state.avoid_roles = _as_list(parsed.get("avoid_roles"))
        return state


async def run_intent_agent(state: SharedState, user_goal_text: str) -> SharedState:
    return await IntentAgent(user_goal_text=user_goal_text).run(state)


def _filter_hard_constraints(raw: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "location",
        "locations",
        "need_visa_sponsor",
        "max_years_exp",
        "role_cluster",
        "role_clusters",
        "degree_required",
    }
    cleaned = {key: value for key, value in raw.items() if key in allowed}
    if "locations" in cleaned:
        cleaned["locations"] = _as_list(cleaned["locations"])
    if "role_clusters" in cleaned:
        cleaned["role_clusters"] = _as_list(cleaned["role_clusters"])
    if "max_years_exp" in cleaned and cleaned["max_years_exp"] is not None:
        cleaned["max_years_exp"] = int(cleaned["max_years_exp"])
    return {key: value for key, value in cleaned.items() if value not in (None, [], "")}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
