from __future__ import annotations

import json
from typing import Any

from app.agents.base import BaseAgent
from app.state.schema import SharedState


class StrategyAgent(BaseAgent):
    name = "strategy_agent"
    system_prompt = """
PHASE_C_STRATEGY_AGENT
You are the Resume & Career Strategy Agent in a lightweight Agentic RAG system.
Produce skill gaps, resume revision advice, and short/medium/long career path.
Resume advice must be grounded in original resume evidence spans.
Do not invent experience, employers, metrics, tools, or outcomes.

Return strict JSON:
{
  "skill_gap_analysis": [object],
  "resume_revision_plan": [
    {
      "section": string,
      "suggestion": string,
      "evidence_span_ids": [resume evidence span id]
    }
  ],
  "career_path": [object]
}
"""

    def build_user_prompt(self, state: SharedState) -> str:
        return json.dumps(
            {
                "resume_state": {
                    "normalized_base_resume": state.resume_state.normalized_base_resume,
                    "skills": state.resume_state.skills,
                    "original_evidence_spans": state.resume_state.original_evidence_spans,
                },
                "recommended_roles": state.strategy_state.recommended_roles,
                "retrieval_state": state.retrieval_state.model_dump(),
            },
            ensure_ascii=False,
        )

    def apply(self, state: SharedState, parsed: dict) -> SharedState:
        state.strategy_state.skill_gap_analysis = _as_list(
            parsed.get("skill_gap_analysis")
        )
        state.strategy_state.career_path = _as_list(parsed.get("career_path"))

        valid_advice, dropped = _filter_resume_revision_plan(
            state, _as_list(parsed.get("resume_revision_plan"))
        )
        state.strategy_state.resume_revision_plan = valid_advice
        state.supervisor_log.append(
            {
                "stage": "strategy_agent",
                "dropped_unsupported_advice": dropped,
            }
        )
        return state


async def run_strategy_agent(state: SharedState) -> SharedState:
    return await StrategyAgent().run(state)


def _filter_resume_revision_plan(
    state: SharedState, items: list[Any]
) -> tuple[list[dict[str, Any]], int]:
    known = _resume_evidence_ids(state)
    kept = []
    dropped = 0
    for item in items:
        if not isinstance(item, dict):
            dropped += 1
            continue
        evidence_ids = {str(value) for value in item.get("evidence_span_ids") or []}
        if evidence_ids and evidence_ids <= known:
            kept.append(item)
        else:
            dropped += 1
    return kept, dropped


def _resume_evidence_ids(state: SharedState) -> set[str]:
    ids = set()
    for span in state.resume_state.original_evidence_spans:
        span_id = span.get("span_id") or span.get("id")
        if span_id:
            ids.add(str(span_id))
    return ids


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]
