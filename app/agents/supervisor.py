from __future__ import annotations

import json
import re
from hashlib import sha256
from typing import Any

from app.config import settings
from app.llm import deepseek
from app.memory.case_base import CareerCase, merge_case_soft_preferences
from app.memory.feedback import is_positive_outcome, normalize_application_outcome
from app.state.schema import SharedState


PLANNING_PROMPT = """
PHASE_C_SUPERVISOR_PLANNING
You are the Supervisor planning stage for a lightweight Agentic RAG system.
Check whether the user's career goal is too vague and produce a retrieval plan.
Use bounded clarification: at most one clarification question.

Return strict JSON:
{
  "needs_clarification": boolean,
  "clarification_question": string optional,
  "retrieval_plan": {
    "hard_constraints": object,
    "soft_preferences": object,
    "top_k": integer,
    "include_raptor": boolean
  }
}
"""

FINAL_PROMPT = """
PHASE_C_SUPERVISOR_FINAL
You are the final verifier for a lightweight Agentic RAG career matching system.
Check hard filter violations, missing job evidence, and resume advice fabrication.
Resume advice is valid only when it cites original resume evidence span ids.

Return strict JSON:
{
  "hard_filter_violations": [object],
  "missing_evidence": [object],
  "fabrication_risks": [object],
  "too_few_results": object optional,
  "needs_reretrieval": boolean,
  "needs_repair": boolean
}
"""


async def plan_retrieval(
    state: SharedState,
    *,
    user_goal_text: str,
    default_top_k: int,
    include_raptor: bool,
) -> dict[str, Any]:
    raw = await deepseek.chat(
        PLANNING_PROMPT,
        _planning_payload(state, user_goal_text, default_top_k, include_raptor),
        pro=True,
        json_mode=True,
    )
    parsed = _loads_or_empty(raw)
    llm_plan = _as_dict(parsed.get("retrieval_plan"))

    needs_clarification = bool(parsed.get("needs_clarification")) or _is_vague_goal(
        user_goal_text, state
    )
    clarification_loop_used = (
        1 if needs_clarification and settings.max_clarification_loops > 0 else 0
    )
    explicit_soft_prefs = (
        state.career_state.soft_preferences
        or _as_dict(llm_plan.get("soft_preferences"))
    )
    soft_prefs = merge_case_soft_preferences(
        explicit_soft_prefs,
        state.feedback_state.case_soft_preferences,
    )
    plan = {
        "needs_clarification": needs_clarification,
        "clarification_question": parsed.get("clarification_question") or "",
        "clarification_loop_used": clarification_loop_used,
        "hard_constraints": state.career_state.hard_constraints
        or _as_dict(llm_plan.get("hard_constraints")),
        "soft_prefs": soft_prefs,
        "top_k": int(llm_plan.get("top_k") or default_top_k),
        "include_raptor": bool(llm_plan.get("include_raptor", include_raptor)),
    }
    state.supervisor_log.append(
        {
            "stage": "planning",
            "needs_clarification": needs_clarification,
            "clarification_loop_used": clarification_loop_used,
            "retrieval_plan": {
                "hard_constraints": plan["hard_constraints"],
                "soft_prefs": plan["soft_prefs"],
                "top_k": plan["top_k"],
                "include_raptor": plan["include_raptor"],
            },
        }
    )
    return plan


async def final_verification(state: SharedState) -> dict[str, Any]:
    raw = await deepseek.chat(
        FINAL_PROMPT,
        _final_payload(state),
        pro=True,
        json_mode=True,
    )
    parsed = _loads_or_empty(raw)
    result = {
        "hard_filter_violations": _as_list(parsed.get("hard_filter_violations")),
        "missing_evidence": _as_list(parsed.get("missing_evidence")),
        "fabrication_risks": _as_list(parsed.get("fabrication_risks")),
        "too_few_results": _as_dict(parsed.get("too_few_results")),
        "needs_reretrieval": bool(parsed.get("needs_reretrieval")),
        "needs_repair": bool(parsed.get("needs_repair")),
    }
    _add_deterministic_verification(state, result)

    if result["needs_repair"] and settings.max_repair_loops > 0:
        repaired = _repair_unsupported_resume_advice(state)
        result["repair_loop_used"] = 1
        result["repaired_resume_advice"] = repaired
    else:
        result["repair_loop_used"] = 0

    result["reretrieval_loop_requested"] = bool(
        result["needs_reretrieval"] and settings.max_reretrieval_loops > 0
    )
    result["reretrieval_loop_used"] = 0

    state.supervisor_log.append({"stage": "final_verification", **result})
    return result


def assess_feedback_for_case(
    state: SharedState, feedback: dict[str, Any]
) -> dict[str, Any]:
    outcome = normalize_application_outcome(str(feedback.get("outcome") or ""))
    matched_role = _find_recommended_role(
        state, str(feedback.get("job_id") or "")
    )
    is_valuable = bool(is_positive_outcome(outcome) and matched_role)
    reason = "positive_feedback_with_recommended_role"
    if not is_positive_outcome(outcome):
        reason = "non_positive_outcome"
    elif not matched_role:
        reason = "job_not_in_recommendations"

    return {
        "is_valuable": is_valuable,
        "outcome": outcome,
        "reason": reason,
        "job_id": feedback.get("job_id"),
        "feedback_id": feedback.get("feedback_id"),
        "matched_role": _public_role(matched_role),
    }


def build_anonymous_case_from_feedback(
    state: SharedState,
    feedback: dict[str, Any],
    decision: dict[str, Any],
) -> CareerCase:
    if not decision.get("is_valuable"):
        raise ValueError("feedback is not valuable enough to become a career case")

    role = _as_dict(decision.get("matched_role"))
    feedback_id = feedback.get("feedback_id") or role.get("job_id") or "manual"
    case = CareerCase(
        case_id=_anonymous_feedback_case_id(
            session_id=state.session_id,
            feedback_id=feedback_id,
            job_id=role.get("job_id"),
        ),
        background_type=_anonymous_background_type(state),
        target_role=str(role.get("title") or role.get("job_id") or "Recommended Role"),
        successful_resume_features=_successful_resume_features(state, role),
        missing_skills_before=_missing_skills_before(state),
        application_outcome=str(decision["outcome"]),
        recommended_bridge_roles=_recommended_bridge_roles(state, role),
    )
    return case.validate_anonymous()


def _add_deterministic_verification(
    state: SharedState, result: dict[str, Any]
) -> None:
    hard_violations = list(result["hard_filter_violations"])
    hard = state.career_state.hard_constraints
    allowed_locations = set(hard.get("locations") or [])
    if hard.get("location"):
        allowed_locations.add(hard["location"])

    if allowed_locations:
        for role in state.strategy_state.recommended_roles:
            location = role.get("location")
            if location and location not in allowed_locations:
                hard_violations.append(
                    {
                        "job_id": role.get("job_id"),
                        "field": "location",
                        "expected": sorted(allowed_locations),
                        "actual": location,
                    }
                )

    missing_evidence = list(result["missing_evidence"])
    for role in state.strategy_state.recommended_roles:
        if not role.get("evidence_span_ids"):
            missing_evidence.append({"job_id": role.get("job_id"), "field": "role"})

    known_resume_evidence = _resume_evidence_ids(state)
    fabrication_risks = list(result["fabrication_risks"])
    for item in state.strategy_state.resume_revision_plan:
        evidence_ids = set(item.get("evidence_span_ids") or [])
        if not evidence_ids or not evidence_ids <= known_resume_evidence:
            fabrication_risks.append(
                {
                    "section": item.get("section"),
                    "suggestion": item.get("suggestion"),
                    "evidence_span_ids": sorted(evidence_ids),
                }
            )

    too_few_results = _as_dict(result.get("too_few_results"))
    planned_top_k = _latest_planned_top_k(state)
    actual_count = len(state.retrieval_state.candidate_job_ids)
    planned_soft_prefs = _latest_planned_soft_prefs(state)
    if planned_top_k > 0 and actual_count < planned_top_k and planned_soft_prefs:
        too_few_results = {
            "expected_top_k": planned_top_k,
            "actual_count": actual_count,
            "candidate_job_ids": list(state.retrieval_state.candidate_job_ids),
            "relaxation": "soft_prefs",
        }

    result["hard_filter_violations"] = hard_violations
    result["missing_evidence"] = missing_evidence
    result["fabrication_risks"] = fabrication_risks
    result["too_few_results"] = too_few_results
    result["needs_reretrieval"] = bool(result["needs_reretrieval"] or hard_violations)
    result["needs_reretrieval"] = bool(
        result["needs_reretrieval"] or too_few_results
    )
    result["needs_repair"] = bool(
        result["needs_repair"] or missing_evidence or fabrication_risks
    )


def _find_recommended_role(
    state: SharedState, job_id: str
) -> dict[str, Any] | None:
    for role in state.strategy_state.recommended_roles:
        if str(role.get("job_id")) == job_id:
            return role
    return None


def _public_role(role: dict[str, Any] | None) -> dict[str, Any]:
    if not role:
        return {}
    return {
        "job_id": role.get("job_id"),
        "title": role.get("title"),
        "tier": role.get("tier"),
        "match_explanation": role.get("match_explanation"),
    }


def _anonymous_background_type(state: SharedState) -> str:
    parts = ["feedback_case"]
    parts.extend(_safe_tokens(state.resume_state.skills[:4]))
    parts.extend(_safe_tokens(state.career_state.current_goal[:2]))
    return "_".join(parts) if len(parts) > 1 else "feedback_case_general_background"


def _successful_resume_features(
    state: SharedState, role: dict[str, Any]
) -> list[str]:
    features = []
    evidence_ids = [
        str(span.get("span_id") or span.get("id"))
        for span in state.resume_state.original_evidence_spans[:3]
        if span.get("span_id") or span.get("id")
    ]
    if evidence_ids:
        features.append("resume evidence spans supported the application")
    if role.get("match_explanation"):
        features.append(str(role["match_explanation"])[:160])
    if not features:
        features.append("profile matched the recommended role evidence")
    return features


def _missing_skills_before(state: SharedState) -> list[str]:
    skills = []
    for item in state.strategy_state.skill_gap_analysis:
        skill = item.get("skill")
        if skill:
            skills.append(str(skill))
    return skills[:5]


def _recommended_bridge_roles(
    state: SharedState, matched_role: dict[str, Any]
) -> list[str]:
    roles = []
    matched_job_id = matched_role.get("job_id")
    for role in state.strategy_state.recommended_roles:
        if role.get("job_id") == matched_job_id:
            continue
        if role.get("tier") == "bridge_role" and role.get("title"):
            roles.append(str(role["title"]))
    return roles[:3]


def _anonymous_feedback_case_id(
    *, session_id: str, feedback_id: Any, job_id: Any
) -> str:
    raw = f"{session_id}|{feedback_id}|{job_id or ''}"
    digest = sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"feedback-{digest}"


def _safe_tokens(values: list[Any]) -> list[str]:
    tokens = []
    for value in values:
        token = re.sub(r"[^A-Za-z0-9]+", "_", str(value)).strip("_")
        if token:
            tokens.append(token)
    return tokens


def _repair_unsupported_resume_advice(state: SharedState) -> int:
    known = _resume_evidence_ids(state)
    kept = []
    dropped = 0
    for item in state.strategy_state.resume_revision_plan:
        evidence_ids = set(item.get("evidence_span_ids") or [])
        if evidence_ids and evidence_ids <= known:
            kept.append(item)
        else:
            dropped += 1
    state.strategy_state.resume_revision_plan = kept
    return dropped


def _planning_payload(
    state: SharedState, user_goal_text: str, default_top_k: int, include_raptor: bool
) -> str:
    return json.dumps(
        {
            "user_goal_text": user_goal_text,
            "career_state": state.career_state.model_dump(),
            "resume_summary": state.resume_state.normalized_base_resume[:1500],
            "default_top_k": default_top_k,
            "include_raptor": include_raptor,
        },
        ensure_ascii=False,
    )


def _final_payload(state: SharedState) -> str:
    return json.dumps(
        {
            "career_state": state.career_state.model_dump(),
            "retrieval_state": state.retrieval_state.model_dump(),
            "strategy_state": state.strategy_state.model_dump(),
            "resume_evidence_span_ids": sorted(_resume_evidence_ids(state)),
        },
        ensure_ascii=False,
    )


def _is_vague_goal(user_goal_text: str, state: SharedState) -> bool:
    if state.career_state.current_goal:
        return False
    tokens = [token for token in user_goal_text.split() if len(token) > 2]
    return len(tokens) < 3


def _resume_evidence_ids(state: SharedState) -> set[str]:
    ids = set()
    for span in state.resume_state.original_evidence_spans:
        span_id = span.get("span_id") or span.get("id")
        if span_id:
            ids.add(str(span_id))
    return ids


def _latest_planned_top_k(state: SharedState) -> int:
    for entry in reversed(state.supervisor_log):
        plan = entry.get("retrieval_plan")
        if entry.get("stage") == "planning" and isinstance(plan, dict):
            try:
                return int(plan.get("top_k") or 0)
            except (TypeError, ValueError):
                return 0
    return 0


def _latest_planned_soft_prefs(state: SharedState) -> dict[str, Any]:
    for entry in reversed(state.supervisor_log):
        plan = entry.get("retrieval_plan")
        if entry.get("stage") == "planning" and isinstance(plan, dict):
            return _as_dict(plan.get("soft_prefs"))
    return {}


def _loads_or_empty(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]
