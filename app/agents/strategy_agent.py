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
Every strategy item must cite evidence_span_ids from the provided evidence contract.
Resume advice must cite original resume evidence spans only.
Do not invent experience, employers, metrics, tools, or outcomes.

Return strict JSON:
{
  "skill_gap_analysis": [
    {
      "skill": string,
      "gap": string,
      "priority": "low" | "medium" | "high",
      "evidence_span_ids": [resume or job evidence span id]
    }
  ],
  "resume_revision_plan": [
    {
      "section": string,
      "suggestion": string,
      "evidence_span_ids": [resume evidence span id]
    }
  ],
  "career_path": [
    {
      "horizon": "short" | "medium" | "long",
      "action": string,
      "evidence_span_ids": [resume or job evidence span id]
    }
  ]
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
                "evidence_contract": {
                    "resume_evidence_span_ids": sorted(_resume_evidence_ids(state)),
                    "job_evidence_span_ids": sorted(_job_evidence_ids(state)),
                    "all_evidence_span_ids": sorted(_all_evidence_ids(state)),
                },
            },
            ensure_ascii=False,
        )

    def apply(self, state: SharedState, parsed: dict) -> SharedState:
        valid_gaps, dropped_gaps = _filter_supported_items(
            _as_list(parsed.get("skill_gap_analysis")),
            known_evidence_ids=_all_evidence_ids(state),
        )
        valid_path, dropped_path = _filter_supported_items(
            _as_list(parsed.get("career_path")),
            known_evidence_ids=_all_evidence_ids(state),
            allowed_horizons={"short", "medium", "long"},
        )
        state.strategy_state.skill_gap_analysis = valid_gaps
        state.strategy_state.career_path = valid_path

        valid_advice, dropped = _filter_resume_revision_plan(
            state, _as_list(parsed.get("resume_revision_plan"))
        )
        state.strategy_state.resume_revision_plan = valid_advice
        state.supervisor_log.append(
            {
                "stage": "strategy_agent",
                "dropped_unsupported_advice": dropped,
                "dropped_unsupported_skill_gaps": dropped_gaps,
                "dropped_unsupported_path_items": dropped_path,
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


def _filter_supported_items(
    items: list[Any],
    *,
    known_evidence_ids: set[str],
    allowed_horizons: set[str] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    kept = []
    dropped = 0
    for item in items:
        if not isinstance(item, dict):
            dropped += 1
            continue
        if allowed_horizons is not None and item.get("horizon") not in allowed_horizons:
            dropped += 1
            continue
        evidence_ids = {str(value) for value in item.get("evidence_span_ids") or []}
        if evidence_ids and evidence_ids <= known_evidence_ids:
            kept.append(item)
        else:
            dropped += 1
    return kept, dropped


def _all_evidence_ids(state: SharedState) -> set[str]:
    return _resume_evidence_ids(state) | _job_evidence_ids(state)


def _job_evidence_ids(state: SharedState) -> set[str]:
    ids = {str(value) for value in state.retrieval_state.evidence_span_ids}
    for score in state.retrieval_state.ranking_scores:
        ids.update(str(value) for value in score.get("evidence_span_ids") or [])
        for span in score.get("evidence_spans") or []:
            span_id = span.get("evidence_span_id") or span.get("span_id") or span.get("id")
            if span_id:
                ids.add(str(span_id))
    for role in state.strategy_state.recommended_roles:
        ids.update(str(value) for value in role.get("evidence_span_ids") or [])
        for span in role.get("evidence_spans") or []:
            span_id = span.get("evidence_span_id") or span.get("span_id") or span.get("id")
            if span_id:
                ids.add(str(span_id))
    return ids


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
