from __future__ import annotations

from typing import Any

from app.agents.supervisor import (
    assess_feedback_for_case,
    build_anonymous_case_from_feedback,
)
from app.memory.case_base import (
    CASE_PREFERENCE_MAX_ITEMS,
    build_case_embedding_text,
    merge_case_soft_preferences,
    search_similar_cases,
    upsert_career_case,
)
from app.db.state_store import load_state, mutate_state_atomically
from app.state.schema import SharedState


async def run_feedback_closure(
    state: SharedState,
    *,
    feedback: dict[str, Any],
    similar_case_query: str | None = None,
    similar_case_top_k: int = 3,
    embed_case: bool = True,
) -> dict[str, Any]:
    decision = assess_feedback_for_case(state, feedback)
    case_written = False
    case_payload: dict[str, Any] | None = None
    similar_cases: list[dict[str, Any]] = []

    if decision["is_valuable"]:
        case = build_anonymous_case_from_feedback(state, feedback, decision)
        await upsert_career_case(case, embed_if_missing=embed_case)
        case_written = True
        case_payload = case.model_dump(mode="json")
        query = similar_case_query or build_case_embedding_text(case)
        similar_cases = await search_similar_cases(
            query, top_k=similar_case_top_k
        )

    soft_preference_updates = build_case_soft_preferences(similar_cases)
    state.feedback_state.case_soft_preferences = merge_case_soft_preferences(
        state.feedback_state.case_soft_preferences,
        soft_preference_updates,
    )
    log_entry = build_feedback_closure_log_entry(
        feedback=feedback,
        decision=decision,
        case_written=case_written,
        case_payload=case_payload,
        soft_preference_updates=soft_preference_updates,
    )
    state.supervisor_log.append(log_entry)

    return {
        "decision": decision,
        "case_written": case_written,
        "case": case_payload,
        "similar_cases": similar_cases,
        "soft_preference_updates": soft_preference_updates,
    }


async def process_feedback_closure_for_session(
    *, session_id: str, feedback: dict[str, Any]
) -> dict[str, Any]:
    state = await load_state(session_id)
    if state is None:
        raise KeyError(session_id)

    result = await run_feedback_closure(state, feedback=feedback)
    soft_preference_updates = result["soft_preference_updates"]
    log_entry = build_feedback_closure_log_entry(
        feedback=feedback,
        decision=result["decision"],
        case_written=result["case_written"],
        case_payload=result["case"],
        soft_preference_updates=soft_preference_updates,
    )

    def merge_closure_result(latest_state: SharedState) -> None:
        latest_state.feedback_state.case_soft_preferences = merge_case_soft_preferences(
            latest_state.feedback_state.case_soft_preferences,
            soft_preference_updates,
        )
        latest_state.supervisor_log.append(log_entry)

    await mutate_state_atomically(
        session_id=session_id,
        mutator=merge_closure_result,
    )
    return result


def build_feedback_closure_log_entry(
    *,
    feedback: dict[str, Any],
    decision: dict[str, Any],
    case_written: bool,
    case_payload: dict[str, Any] | None,
    soft_preference_updates: dict[str, Any],
) -> dict[str, Any]:
    return {
        "stage": "feedback_closure",
        "feedback_id": feedback.get("feedback_id"),
        "job_id": feedback.get("job_id"),
        "decision": decision,
        "case_written": case_written,
        "case_id": case_payload.get("case_id") if case_payload else None,
        "soft_preference_updates": soft_preference_updates,
    }


def build_case_soft_preferences(
    similar_cases: list[dict[str, Any]]
) -> dict[str, list[str]]:
    target_roles: list[str] = []
    bridge_roles: list[str] = []
    for case in similar_cases:
        _append_unique(target_roles, case.get("target_role"))
        for role in case.get("recommended_bridge_roles") or []:
            _append_unique(bridge_roles, role)

    updates: dict[str, list[str]] = {}
    if target_roles:
        updates["case_target_roles"] = target_roles
    if bridge_roles:
        updates["case_bridge_roles"] = bridge_roles
    return updates


def _append_unique(values: list[str], value: Any) -> None:
    if len(values) >= CASE_PREFERENCE_MAX_ITEMS:
        return
    if not value:
        return
    text = str(value)
    if text not in values:
        values.append(text)
