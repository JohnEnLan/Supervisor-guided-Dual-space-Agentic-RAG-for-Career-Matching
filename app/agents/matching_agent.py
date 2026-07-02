from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from app.agents.base import BaseAgent
from app.retrieval.hybrid_search import JobCandidate, hybrid_search
from app.retrieval.query_builder import build_resume_retrieval_query
from app.state.schema import SharedState


SearchFn = Callable[..., Awaitable[list[JobCandidate]]]


class MatchingAgent(BaseAgent):
    name = "matching_agent"
    system_prompt = """
PHASE_C_MATCHING_AGENT
You are the Retrieval & Matching Agent in a lightweight Agentic RAG system.
Given normalized resume context and retrieved job candidates, classify each useful
candidate into one of: now_fit, stretch_fit, bridge_role.
Use only provided candidate evidence ids for match explanations.

Return strict JSON:
{
  "recommended_roles": [
    {
      "job_id": string,
      "tier": "now_fit" | "stretch_fit" | "bridge_role",
      "match_explanation": string,
      "evidence_span_ids": [string]
    }
  ]
}
"""

    def __init__(self, candidates: list[JobCandidate]):
        self.candidates = candidates

    def build_user_prompt(self, state: SharedState) -> str:
        return json.dumps(
            {
                "resume": {
                    "normalized_base_resume": state.resume_state.normalized_base_resume,
                    "skills": state.resume_state.skills,
                },
                "career_state": state.career_state.model_dump(),
                "candidates": [_candidate_payload(candidate) for candidate in self.candidates],
            },
            ensure_ascii=False,
        )

    def apply(self, state: SharedState, parsed: dict) -> SharedState:
        roles_by_job = {
            str(role.get("job_id")): role
            for role in parsed.get("recommended_roles") or []
            if isinstance(role, dict) and role.get("job_id")
        }
        state.strategy_state.recommended_roles = [
            _recommended_role_from_candidate(candidate, roles_by_job.get(candidate.job_id))
            for candidate in self.candidates
        ]
        return state


async def run_matching_agent(
    state: SharedState,
    *,
    retrieval_plan: dict[str, Any],
    search_fn: SearchFn = hybrid_search,
) -> SharedState:
    query = build_resume_retrieval_query(state.resume_state).text.strip()
    if not query:
        raise ValueError("resume_state does not contain enough text for retrieval")

    candidates = await search_fn(
        query=query,
        hard_constraints=retrieval_plan.get("hard_constraints") or {},
        soft_prefs=retrieval_plan.get("soft_prefs") or {},
        top_k=int(retrieval_plan.get("top_k") or 5),
        include_raptor=bool(retrieval_plan.get("include_raptor", False)),
    )
    _write_retrieval_state(state, candidates)
    return await MatchingAgent(candidates).run(state)


def _write_retrieval_state(state: SharedState, candidates: list[JobCandidate]) -> None:
    evidence_ids: list[str] = []
    seen_evidence: set[str] = set()
    ranking_scores = []

    for candidate in candidates:
        ranking_scores.append(
            {
                "job_id": candidate.job_id,
                "score": candidate.score,
                "rrf_score": candidate.rrf_score,
                "bm25_score": candidate.bm25_score,
                "dense_score": candidate.dense_score,
                "raptor_score": candidate.raptor_score,
                "field_bonus": candidate.field_bonus,
                "sources": list(candidate.sources),
                "evidence_span_ids": list(candidate.evidence_span_ids),
            }
        )
        for evidence_id in candidate.evidence_span_ids:
            if evidence_id in seen_evidence:
                continue
            seen_evidence.add(evidence_id)
            evidence_ids.append(evidence_id)

    state.retrieval_state.candidate_job_ids = [
        candidate.job_id for candidate in candidates
    ]
    state.retrieval_state.ranking_scores = ranking_scores
    state.retrieval_state.evidence_span_ids = evidence_ids


def _recommended_role_from_candidate(
    candidate: JobCandidate, llm_role: dict[str, Any] | None
) -> dict[str, Any]:
    llm_role = llm_role or {}
    evidence_span_ids = [
        str(item)
        for item in (llm_role.get("evidence_span_ids") or candidate.evidence_span_ids)
    ]
    return {
        "job_id": candidate.job_id,
        "tier": _valid_tier(llm_role.get("tier")),
        "title": candidate.title,
        "company": candidate.company,
        "location": candidate.location,
        "match_score": candidate.score,
        "match_explanation": llm_role.get("match_explanation") or "",
        "evidence_span_ids": evidence_span_ids,
        "source_scores": {
            "rrf": candidate.rrf_score,
            "bm25": candidate.bm25_score,
            "dense": candidate.dense_score,
            "raptor": candidate.raptor_score,
            "field_bonus": candidate.field_bonus,
            "sources": list(candidate.sources),
        },
    }


def _valid_tier(value: Any) -> str:
    if value in {"now_fit", "stretch_fit", "bridge_role"}:
        return str(value)
    return "stretch_fit"


def _candidate_payload(candidate: JobCandidate) -> dict[str, Any]:
    return {
        "job_id": candidate.job_id,
        "title": candidate.title,
        "company": candidate.company,
        "location": candidate.location,
        "score": candidate.score,
        "evidence_span_ids": candidate.evidence_span_ids,
        "sources": candidate.sources,
    }
