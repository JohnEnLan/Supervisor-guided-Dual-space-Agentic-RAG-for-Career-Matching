"""Deterministic policy checkpoints for the lightweight Supervisor Harness."""

from __future__ import annotations

from typing import Any, Mapping

from app.state.schema import SharedState


CHECKPOINT_METADATA = {
    "intent_input": ("intent_agent", "before"),
    "intent_output": ("intent_agent", "after"),
    "matching_input": ("matching_agent", "before"),
    "matching_output": ("matching_agent", "after"),
    "strategy_input": ("strategy_agent", "before"),
    "strategy_output": ("strategy_agent", "after"),
    "publication_gate": ("supervisor", "before_publication"),
}


class SupervisorCheckpointError(ValueError):
    """Raised before an Agent call when a deterministic contract is invalid."""

    def __init__(self, checkpoint: str, issue_codes: list[str]):
        self.checkpoint = checkpoint
        self.issue_codes = issue_codes
        super().__init__(f"{checkpoint} blocked: {', '.join(issue_codes)}")


def record_supervisor_checkpoint(
    state: SharedState,
    *,
    checkpoint: str,
    user_goal_text: str = "",
    retrieval_plan: Mapping[str, Any] | None = None,
    locked_hard_constraints: Mapping[str, Any] | None = None,
    verification: Mapping[str, Any] | None = None,
    attempt: int = 1,
) -> dict[str, Any]:
    """Run one privacy-safe deterministic check and append its audit record."""
    if checkpoint not in CHECKPOINT_METADATA:
        raise ValueError(f"unknown supervisor checkpoint: {checkpoint}")

    issues: list[str] = []
    blocking: list[str] = []
    metrics: dict[str, Any] = {}

    if checkpoint == "intent_input":
        _check_intent_input(state, user_goal_text, issues, blocking, metrics)
    elif checkpoint == "intent_output":
        _check_intent_output(state, issues, metrics)
    elif checkpoint == "matching_input":
        _check_matching_input(
            retrieval_plan,
            locked_hard_constraints,
            issues,
            blocking,
            metrics,
        )
    elif checkpoint == "matching_output":
        _check_matching_output(state, issues, metrics)
    elif checkpoint == "strategy_input":
        _check_strategy_input(state, issues, metrics)
    elif checkpoint == "strategy_output":
        _check_strategy_output(state, issues, metrics)
    else:
        _check_publication_gate(state, verification, issues, metrics)

    agent, phase = CHECKPOINT_METADATA[checkpoint]
    record = {
        "stage": "supervisor_checkpoint",
        "checkpoint": checkpoint,
        "agent": agent,
        "phase": phase,
        "attempt": max(1, int(attempt)),
        "status": "blocked" if blocking else ("warning" if issues else "passed"),
        "issue_codes": _dedupe(issues),
        "metrics": metrics,
    }
    state.supervisor_log.append(record)
    if blocking:
        raise SupervisorCheckpointError(checkpoint, _dedupe(blocking))
    return record


def _check_intent_input(
    state: SharedState,
    user_goal_text: str,
    issues: list[str],
    blocking: list[str],
    metrics: dict[str, Any],
) -> None:
    if not user_goal_text.strip():
        issues.append("goal_missing")
        blocking.append("goal_missing")
    resume_context_present = _has_resume_context(state)
    metrics["resume_context_present"] = resume_context_present
    if not resume_context_present:
        issues.append("resume_context_missing")


def _check_intent_output(
    state: SharedState,
    issues: list[str],
    metrics: dict[str, Any],
) -> None:
    goal_count = len(state.career_state.current_goal)
    metrics["goal_count"] = goal_count
    if goal_count == 0 and not state.career_state.intent_directions:
        issues.append("intent_goal_missing")


def _check_matching_input(
    retrieval_plan: Mapping[str, Any] | None,
    locked_hard_constraints: Mapping[str, Any] | None,
    issues: list[str],
    blocking: list[str],
    metrics: dict[str, Any],
) -> None:
    plan = retrieval_plan if isinstance(retrieval_plan, Mapping) else {}
    hard_constraints = plan.get("hard_constraints")
    soft_prefs = plan.get("soft_prefs")
    if not isinstance(hard_constraints, Mapping):
        issues.append("hard_constraints_shape_invalid")
        blocking.append("hard_constraints_shape_invalid")
    if not isinstance(soft_prefs, Mapping):
        issues.append("soft_preferences_shape_invalid")
        blocking.append("soft_preferences_shape_invalid")

    try:
        top_k = int(plan.get("top_k"))
    except (TypeError, ValueError):
        top_k = 0
    metrics["top_k"] = top_k
    if top_k <= 0:
        issues.append("retrieval_top_k_invalid")
        blocking.append("retrieval_top_k_invalid")

    if locked_hard_constraints is not None and dict(hard_constraints or {}) != dict(
        locked_hard_constraints
    ):
        issues.append("locked_hard_constraints_changed")
        blocking.append("locked_hard_constraints_changed")


def _check_matching_output(
    state: SharedState,
    issues: list[str],
    metrics: dict[str, Any],
) -> None:
    candidate_ids = [str(item) for item in state.retrieval_state.candidate_job_ids]
    ranking_rows = [
        row for row in state.retrieval_state.ranking_scores if isinstance(row, dict)
    ]
    metrics.update(
        {
            "candidate_count": len(candidate_ids),
            "ranking_count": len(ranking_rows),
            "evidence_count": len(state.retrieval_state.evidence_span_ids),
        }
    )
    if not candidate_ids:
        issues.append("candidate_set_empty")
    if len(candidate_ids) != len(set(candidate_ids)):
        issues.append("candidate_ids_duplicated")

    ranked_ids = {str(row.get("job_id")) for row in ranking_rows if row.get("job_id")}
    if set(candidate_ids) - ranked_ids:
        issues.append("candidate_ranking_missing")
    if any(
        not row.get("evidence_span_ids") and not row.get("evidence_spans")
        for row in ranking_rows
    ):
        issues.append("candidate_evidence_missing")


def _check_strategy_input(
    state: SharedState,
    issues: list[str],
    metrics: dict[str, Any],
) -> None:
    candidate_count = len(state.retrieval_state.candidate_job_ids)
    metrics["candidate_count"] = candidate_count
    if candidate_count == 0:
        issues.append("candidate_set_empty")


def _check_strategy_output(
    state: SharedState,
    issues: list[str],
    metrics: dict[str, Any],
) -> None:
    candidate_ids = {str(item) for item in state.retrieval_state.candidate_job_ids}
    roles = [
        role for role in state.strategy_state.recommended_roles if isinstance(role, dict)
    ]
    metrics["recommendation_count"] = len(roles)
    if any(str(role.get("job_id") or "") not in candidate_ids for role in roles):
        issues.append("recommendation_not_retrieved")
    if any(not role.get("evidence_span_ids") for role in roles):
        issues.append("recommendation_jd_evidence_missing")


def _check_publication_gate(
    state: SharedState,
    verification: Mapping[str, Any] | None,
    issues: list[str],
    metrics: dict[str, Any],
) -> None:
    result = verification if isinstance(verification, Mapping) else {}
    hard_violations = _list_of_mappings(result.get("hard_filter_violations"))
    missing_evidence = _list_of_mappings(result.get("missing_evidence"))
    fabrication_risks = _list_of_mappings(result.get("fabrication_risks"))
    if hard_violations:
        issues.append("hard_filter_violation")
    if missing_evidence:
        issues.append("verification_missing_evidence")
    if fabrication_risks:
        issues.append("fabrication_risk")

    blocked_job_ids = {
        str(item.get("job_id")) for item in hard_violations if item.get("job_id")
    }
    roles = [
        role for role in state.strategy_state.recommended_roles if isinstance(role, dict)
    ]
    publishable_count = sum(
        1
        for role in roles
        if role.get("job_id")
        and str(role["job_id"]) not in blocked_job_ids
        and role.get("evidence_span_ids")
    )
    metrics.update(
        {
            "recommendation_count": len(roles),
            "publishable_recommendation_count": publishable_count,
        }
    )
    if roles and publishable_count == 0:
        issues.append("no_publishable_recommendations")


def _has_resume_context(state: SharedState) -> bool:
    resume = state.resume_state
    return bool(
        resume.normalized_base_resume.strip()
        or resume.skills
        or resume.education
        or resume.experience
        or resume.projects
        or resume.original_evidence_spans
    )


def _list_of_mappings(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
