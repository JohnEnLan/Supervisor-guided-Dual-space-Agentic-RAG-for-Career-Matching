from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from app.config import settings
from app.llm.qwen_embed import embed_one
from app.memory import case_base
from app.memory.case_base import contains_pii
from app.memory.case_schema import FinalStatus, HiringStage, ImplicitEvidence
from app.retrieval.hybrid_search import JobCandidate
from app.state.schema import ResumeState


EDUCATION_FIELDS = (
    "school",
    "institution",
    "university",
    "degree",
    "major",
    "field",
    "field_of_study",
    "qualification",
)
EXPERIENCE_FIELDS = (
    "company",
    "employer",
    "organization",
    "title",
    "role",
    "position",
)
PROJECT_FIELDS = (
    "name",
    "title",
    "technologies",
    "technology",
    "skills",
    "tools",
)


def build_implicit_query_text(resume_state: ResumeState) -> str:
    values: list[str] = []
    seen: set[str] = set()

    _append_fields(values, seen, resume_state.education, EDUCATION_FIELDS)
    _append_fields(values, seen, resume_state.experience, EXPERIENCE_FIELDS)
    _append_fields(values, seen, resume_state.projects, PROJECT_FIELDS)
    _append_values(values, seen, resume_state.skills)

    return "\n".join(values)


def aggregate_implicit_evidence(
    rows: list[dict[str, Any]], *, candidate_job_id: str
) -> ImplicitEvidence:
    weighted_sum = 0.0
    weight_sum = 0.0
    ranked_rows: list[tuple[float, dict[str, Any]]] = []

    for row in rows:
        similarity = _bounded_float(row.get("similarity"))
        source_confidence = _bounded_float(row.get("source_confidence", 1.0))
        explicit_match_score = _bounded_float(row.get("explicit_match_score"))
        stage_weight = _stage_weight(row)
        contribution = (
            similarity
            * stage_weight
            * explicit_match_score
            * source_confidence
        )
        weighted_sum += contribution
        weight_sum += similarity * source_confidence
        ranked_rows.append((contribution, row))

    score = weighted_sum / weight_sum if weight_sum else 0.0
    minimum_cases = max(int(settings.implicit_min_cases), 1)
    confidence = min(1.0, len(rows) / minimum_cases)
    supporting_cases = [
        _public_supporting_case(row)
        for _contribution, row in sorted(
            ranked_rows,
            key=lambda item: (-item[0], str(item[1].get("case_id") or "")),
        )
    ]
    return ImplicitEvidence(
        job_id=candidate_job_id,
        score=min(max(score, 0.0), 1.0),
        confidence=confidence,
        effective_case_count=len(rows),
        supporting_cases=supporting_cases,
    )


async def search_implicit_evidence(
    *,
    anonymized_resume_text: str,
    candidates: list[JobCandidate],
    top_k_cases: int = 20,
) -> dict[str, ImplicitEvidence]:
    if not anonymized_resume_text.strip() or not candidates:
        return {}

    rows = await retrieve_implicit_case_rows(
        anonymized_resume_text=anonymized_resume_text,
        top_k_cases=top_k_cases,
    )
    return match_implicit_evidence(rows=rows, candidates=candidates)


async def retrieve_implicit_case_rows(
    *, anonymized_resume_text: str, top_k_cases: int = 20
) -> list[dict[str, Any]]:
    if not anonymized_resume_text.strip() or top_k_cases <= 0:
        return []
    query_embedding = await embed_one(anonymized_resume_text)
    return await case_base.search_similar_resume_cases_by_embedding(
        query_embedding, top_k=top_k_cases
    )


def match_implicit_evidence(
    *, rows: list[dict[str, Any]], candidates: list[JobCandidate]
) -> dict[str, ImplicitEvidence]:
    candidate_by_id = {candidate.job_id: candidate for candidate in candidates}
    rows_by_candidate: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in rows:
        row_job_id = str(row.get("job_id") or "")
        if row_job_id in candidate_by_id:
            rows_by_candidate[row_job_id].append(row)
            continue

        company = _normalised_text(row.get("company"))
        role_family = _normalised_text(row.get("role_family"))
        if not company or not role_family:
            continue
        for candidate in candidates:
            if (
                _normalised_text(candidate.company) == company
                and _normalised_text(candidate.role_cluster) == role_family
            ):
                rows_by_candidate[candidate.job_id].append(row)

    return {
        job_id: aggregate_implicit_evidence(
            matched_rows, candidate_job_id=job_id
        )
        for job_id, matched_rows in rows_by_candidate.items()
        if matched_rows
    }


def _append_fields(
    output: list[str],
    seen: set[str],
    records: Iterable[dict[str, Any]],
    allowed_fields: tuple[str, ...],
) -> None:
    for record in records:
        for field in allowed_fields:
            _append_values(output, seen, _as_values(record.get(field)))


def _append_values(
    output: list[str], seen: set[str], values: Iterable[Any]
) -> None:
    for value in values:
        text = " ".join(str(value).strip().split()) if value is not None else ""
        key = text.casefold()
        if not text or key in seen or contains_pii(text):
            continue
        seen.add(key)
        output.append(text)


def _as_values(value: Any) -> list[Any]:
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _stage_weight(row: dict[str, Any]) -> float:
    try:
        stage = HiringStage(str(row.get("highest_stage") or ""))
    except ValueError:
        return 0.0
    final_status = str(row.get("final_status") or "").casefold()
    if final_status == FinalStatus.REJECTED and stage in {
        HiringStage.APPLIED,
        HiringStage.SCREEN_PASSED,
    }:
        return 0.0
    return stage.weight


def _bounded_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(max(number, 0.0), 1.0)


def _normalised_text(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _public_supporting_case(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": str(row.get("case_id") or ""),
        "similarity": _bounded_float(row.get("similarity")),
        "company": str(row.get("company") or ""),
        "role_family": str(row.get("role_family") or ""),
        "highest_stage": str(row.get("highest_stage") or ""),
        "final_status": str(row.get("final_status") or ""),
        "explicit_match_score": _bounded_float(row.get("explicit_match_score")),
        "source_confidence": _bounded_float(row.get("source_confidence", 1.0)),
    }
