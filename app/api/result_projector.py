from __future__ import annotations

from typing import Any

from app.domain.results import (
    CareerPathItem,
    EvidenceItem,
    ProductResult,
    RecommendationResult,
    ResumeAdvice,
    SkillGap,
)
from app.state.schema import SharedState


VALID_TIERS = {"now_fit", "stretch_fit", "bridge_role"}


def project_product_result(state: SharedState) -> ProductResult:
    """Project private SharedState into the sole public product result shape."""
    warnings: list[str] = []
    roles: list[RecommendationResult] = []
    ranked_evidence = _ranked_job_evidence(state)
    verified_hard_failures = _verified_hard_failure_job_ids(state)

    for role in state.strategy_state.recommended_roles:
        job_id = str(role.get("job_id") or "").strip()
        if not job_id:
            warnings.append("recommendation_missing_job_id")
            continue
        if (
            job_id in verified_hard_failures
            or role.get("hard_constraint_passed") is False
            or role.get("hard_constraint_violations")
        ):
            warnings.append(f"hard_constraint_failed:{job_id}")
            continue

        evidence = _job_evidence_for_role(role, ranked_evidence.get(job_id, {}))
        if not evidence:
            warnings.append(f"recommendation_missing_jd_evidence:{job_id}")
            continue

        explanation = str(
            role.get("explicit_explanation")
            or role.get("match_explanation")
            or "Evidence-backed job match."
        ).strip()
        why = [explanation]
        implicit = str(role.get("implicit_explanation") or "").strip()
        if implicit:
            why.append(implicit)
        roles.append(
            RecommendationResult(
                job_id=job_id,
                title=_optional_text(role.get("title")),
                company=_optional_text(role.get("company")),
                location=_optional_text(role.get("location")),
                tier=(
                    str(role.get("tier"))
                    if role.get("tier") in VALID_TIERS
                    else "stretch_fit"
                ),
                concise_explanation=explanation,
                why_this_match=why,
                evidence=evidence,
                resume_evidence=_resume_evidence_for_role(state, role),
                source_url=_optional_text(role.get("source_url")),
                listing_kind=(
                    "source_url" if role.get("source_url") else "dataset_only"
                ),
            )
        )

    return ProductResult(
        summary=(
            f"{len(roles)} evidence-grounded role"
            f"{'s' if len(roles) != 1 else ''} recommended."
        ),
        recommended_roles=roles,
        resume_strategy=[
            ResumeAdvice.model_validate(item)
            for item in state.strategy_state.resume_revision_plan
        ],
        skill_gaps=[
            SkillGap.model_validate(item)
            for item in state.strategy_state.skill_gap_analysis
        ],
        career_path=[
            CareerPathItem.model_validate(item)
            for item in state.strategy_state.career_path
        ],
        warnings=warnings,
    )


def _ranked_job_evidence(state: SharedState) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("job_id")): row
        for row in state.retrieval_state.ranking_scores
        if row.get("job_id")
    }


def _verified_hard_failure_job_ids(state: SharedState) -> set[str]:
    failed: set[str] = set()
    for entry in state.supervisor_log:
        violations = entry.get("hard_filter_violations") or []
        if not isinstance(violations, list):
            continue
        for violation in violations:
            if isinstance(violation, dict) and violation.get("job_id"):
                failed.add(str(violation["job_id"]))
    return failed


def _job_evidence_for_role(
    role: dict[str, Any], ranked_row: dict[str, Any]
) -> list[EvidenceItem]:
    requested_ids = {
        str(item) for item in role.get("evidence_span_ids") or [] if item
    }
    spans = list(role.get("evidence_spans") or []) + list(
        ranked_row.get("evidence_spans") or []
    )
    result: list[EvidenceItem] = []
    seen: set[str] = set()
    for span in spans:
        if not isinstance(span, dict):
            continue
        span_id = str(
            span.get("evidence_span_id") or span.get("span_id") or ""
        ).strip()
        content = str(span.get("content") or span.get("text") or "").strip()
        if not span_id or not content or span_id in seen:
            continue
        if requested_ids and span_id not in requested_ids:
            continue
        seen.add(span_id)
        result.append(
            EvidenceItem(
                evidence_span_id=span_id,
                field=_optional_text(span.get("field")),
                content=content,
            )
        )
    return result


def _resume_evidence_for_role(
    state: SharedState, role: dict[str, Any]
) -> list[EvidenceItem]:
    requested_ids = {
        str(item) for item in role.get("resume_evidence_span_ids") or [] if item
    }
    if not requested_ids:
        return []
    result = []
    for span in state.resume_state.original_evidence_spans:
        span_id = str(span.get("span_id") or span.get("id") or "").strip()
        text = str(span.get("text") or "").strip()
        if span_id in requested_ids and text:
            result.append(
                EvidenceItem(
                    evidence_span_id=span_id,
                    field="resume",
                    content=text,
                )
            )
    return result


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
