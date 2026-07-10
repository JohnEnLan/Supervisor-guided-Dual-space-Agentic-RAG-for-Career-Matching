from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable

from app.agents.base import BaseAgent
from app.llm import deepseek
from app.retrieval.hybrid_search import JobCandidate, hybrid_search
from app.retrieval.query_builder import build_resume_retrieval_query
from app.state.schema import SharedState


SearchFn = Callable[..., Awaitable[list[JobCandidate]]]
ChatFn = Callable[..., Awaitable[str]]


MATCH_EXPLANATION_PROMPT = """
PHASE_C_MATCHING_AGENT
You are producing a concise evidence-grounded match explanation for exactly one
retrieved job candidate. Use only the supplied candidate evidence ids/text.

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


class MatchingAgent(BaseAgent):
    name = "matching_agent"
    system_prompt = """
PHASE_C_MATCHING_AGENT
You are the Retrieval & Matching Agent in a lightweight Agentic RAG system.
Given normalized resume context and retrieved job candidates, classify each useful
candidate into one of: now_fit, stretch_fit, bridge_role.
Use only provided candidate evidence ids and evidence text for match explanations.

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
    state = await MatchingAgent(candidates).run(state)
    if retrieval_plan.get("parallel_explanations", True):
        await enrich_top_match_explanations(
            state,
            candidates,
            top_n=int(retrieval_plan.get("explanation_top_n") or 5),
        )
    return state


async def enrich_top_match_explanations(
    state: SharedState,
    candidates: list[JobCandidate],
    *,
    top_n: int = 5,
    chat_fn: ChatFn | None = None,
) -> SharedState:
    if top_n <= 0 or not candidates:
        return state

    roles_by_job = {
        str(role.get("job_id")): role
        for role in state.strategy_state.recommended_roles
        if isinstance(role, dict) and role.get("job_id")
    }
    chat_fn = chat_fn or deepseek.chat
    top_candidates = candidates[:top_n]
    explanation_rows = await asyncio.gather(
        *[
            _explain_candidate_match_safely(
                state,
                candidate,
                roles_by_job.get(candidate.job_id, {}),
                chat_fn=chat_fn,
            )
            for candidate in top_candidates
        ]
    )

    updated = 0
    failed_job_ids = [
        job_id for job_id, _explanation, error in explanation_rows if error
    ]
    for job_id, explanation, error in explanation_rows:
        role = roles_by_job.get(job_id)
        if error or not role or not explanation:
            continue
        role["tier"] = explanation["tier"]
        role["match_explanation"] = explanation["match_explanation"]
        role["evidence_span_ids"] = explanation["evidence_span_ids"]
        role["evidence_spans"] = explanation["evidence_spans"]
        updated += 1

    state.supervisor_log.append(
        {
            "stage": "matching_explanations",
            "mode": "parallel",
            "requested": len(top_candidates),
            "updated": updated,
            "failed": len(failed_job_ids),
            "failed_job_ids": failed_job_ids,
        }
    )
    return state


async def _explain_candidate_match_safely(
    state: SharedState,
    candidate: JobCandidate,
    current_role: dict[str, Any],
    *,
    chat_fn: ChatFn,
) -> tuple[str, dict[str, Any], str | None]:
    try:
        job_id, explanation = await _explain_candidate_match(
            state,
            candidate,
            current_role,
            chat_fn=chat_fn,
        )
    except Exception as exc:
        return candidate.job_id, {}, type(exc).__name__

    if (
        not isinstance(explanation, dict)
        or not str(explanation.get("match_explanation") or "").strip()
    ):
        return job_id, {}, "invalid_response"
    return job_id, explanation, None


async def _explain_candidate_match(
    state: SharedState,
    candidate: JobCandidate,
    current_role: dict[str, Any],
    *,
    chat_fn: ChatFn,
) -> tuple[str, dict[str, Any]]:
    payload = {
        "resume": {
            "normalized_base_resume": state.resume_state.normalized_base_resume,
            "skills": state.resume_state.skills,
        },
        "career_state": state.career_state.model_dump(),
        "candidate": _candidate_payload(candidate),
        "current_role": current_role,
    }
    raw = await chat_fn(
        MATCH_EXPLANATION_PROMPT,
        json.dumps(payload, ensure_ascii=False),
        pro=False,
        json_mode=True,
    )
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return candidate.job_id, {}

    role = _role_for_candidate(parsed, candidate.job_id)
    if not role:
        return candidate.job_id, {}
    evidence_span_ids = _supported_evidence_ids(candidate, role)
    return candidate.job_id, {
        "tier": _valid_tier(role.get("tier") or current_role.get("tier")),
        "match_explanation": role.get("match_explanation")
        or current_role.get("match_explanation")
        or "",
        "evidence_span_ids": evidence_span_ids,
        "evidence_spans": _evidence_spans_for_ids(candidate, evidence_span_ids),
    }


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
                "evidence_spans": list(candidate.evidence_spans),
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
    evidence_span_ids = _supported_evidence_ids(candidate, llm_role)
    return {
        "job_id": candidate.job_id,
        "tier": _valid_tier(llm_role.get("tier")),
        "title": candidate.title,
        "company": candidate.company,
        "location": candidate.location,
        "match_score": candidate.score,
        "match_explanation": llm_role.get("match_explanation") or "",
        "evidence_span_ids": evidence_span_ids,
        "evidence_spans": _evidence_spans_for_ids(candidate, evidence_span_ids),
        "source_scores": {
            "rrf": candidate.rrf_score,
            "bm25": candidate.bm25_score,
            "dense": candidate.dense_score,
            "raptor": candidate.raptor_score,
            "field_bonus": candidate.field_bonus,
            "sources": list(candidate.sources),
        },
    }


def _supported_evidence_ids(
    candidate: JobCandidate, llm_role: dict[str, Any]
) -> list[str]:
    allowed = set(candidate.evidence_span_ids)
    requested = [
        str(item)
        for item in (llm_role.get("evidence_span_ids") or [])
        if str(item) in allowed
    ]
    return requested or list(candidate.evidence_span_ids)


def _role_for_candidate(parsed: dict[str, Any], job_id: str) -> dict[str, Any]:
    for role in parsed.get("recommended_roles") or []:
        if isinstance(role, dict) and str(role.get("job_id")) == job_id:
            return role
    return {}


def _evidence_spans_for_ids(
    candidate: JobCandidate, evidence_span_ids: list[str]
) -> list[dict[str, Any]]:
    wanted = set(evidence_span_ids)
    return [
        span
        for span in candidate.evidence_spans
        if str(span.get("evidence_span_id")) in wanted
    ]


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
        "evidence_spans": candidate.evidence_spans,
        "sources": candidate.sources,
    }
