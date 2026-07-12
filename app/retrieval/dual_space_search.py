from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from typing import Any, Awaitable, Callable

from app.config import settings
from app.retrieval.hybrid_search import JobCandidate, hybrid_search
from app.retrieval.implicit_search import (
    match_implicit_evidence,
    retrieve_implicit_case_rows,
)


logger = logging.getLogger(__name__)

ExplicitSearch = Callable[..., Awaitable[list[JobCandidate]]]
ImplicitRowsSearch = Callable[..., Awaitable[list[dict[str, Any]]]]


async def dual_space_search(
    *,
    query: str,
    anonymized_resume_text: str,
    hard_constraints: dict,
    soft_prefs: dict,
    top_k: int,
    implicit_enabled: bool = True,
    include_raptor: bool = False,
    explicit_search: ExplicitSearch = hybrid_search,
    implicit_rows_search: ImplicitRowsSearch = retrieve_implicit_case_rows,
) -> list[JobCandidate]:
    explicit_call = explicit_search(
        query=query,
        hard_constraints=hard_constraints,
        soft_prefs=soft_prefs,
        top_k=top_k,
        include_raptor=include_raptor,
    )
    if not implicit_enabled or not anonymized_resume_text.strip():
        return await explicit_call

    explicit_candidates, implicit_rows = await asyncio.gather(
        explicit_call,
        _safe_implicit_rows(
            implicit_rows_search,
            anonymized_resume_text=anonymized_resume_text,
            top_k_cases=settings.implicit_case_top_k,
        ),
    )
    if not implicit_rows:
        return explicit_candidates

    evidence_by_job = match_implicit_evidence(
        rows=implicit_rows, candidates=explicit_candidates
    )
    if not evidence_by_job:
        return explicit_candidates

    fused: list[JobCandidate] = []
    for candidate in explicit_candidates:
        evidence = evidence_by_job.get(candidate.job_id)
        if evidence is None:
            fused.append(candidate)
            continue

        explicit_score = candidate.explicit_score or candidate.score
        beta = _bounded(settings.implicit_max_weight) * evidence.confidence
        final_score = (1.0 - beta) * _bounded(explicit_score) + beta * evidence.score
        sources = list(candidate.sources)
        if "implicit_case" not in sources:
            sources.append("implicit_case")
        fused.append(
            replace(
                candidate,
                score=round(final_score, 6),
                explicit_score=explicit_score,
                implicit_score=evidence.score,
                implicit_confidence=evidence.confidence,
                implicit_evidence=evidence.supporting_cases,
                sources=sources,
            )
        )

    return sorted(
        fused,
        key=lambda candidate: (
            -candidate.score,
            -candidate.explicit_score,
            candidate.job_id,
        ),
    )[:top_k]


async def _safe_implicit_rows(
    search: ImplicitRowsSearch,
    *,
    anonymized_resume_text: str,
    top_k_cases: int,
) -> list[dict[str, Any]]:
    try:
        return await search(
            anonymized_resume_text=anonymized_resume_text,
            top_k_cases=top_k_cases,
        )
    except Exception:
        logger.warning("Implicit retrieval unavailable; using explicit results")
        return []


def _bounded(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(max(number, 0.0), 1.0)
