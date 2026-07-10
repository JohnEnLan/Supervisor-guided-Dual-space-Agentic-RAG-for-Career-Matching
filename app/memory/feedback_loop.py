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
    normalize_case_soft_preferences,
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
    closure_status = "skipped"
    error_code: str | None = None

    if decision["is_valuable"]:
        try:
            case = build_anonymous_case_from_feedback(state, feedback, decision)
        except Exception:
            error_code = "case_build_failed"
        else:
            case_payload = case.model_dump(mode="json")
            try:
                await upsert_career_case(case, embed_if_missing=embed_case)
            except Exception:
                error_code = "case_upsert_failed"
            else:
                case_written = True
                query = similar_case_query or build_case_embedding_text(case)
                try:
                    similar_cases = await search_similar_cases(
                        query, top_k=similar_case_top_k
                    )
                except Exception:
                    error_code = "similar_case_search_failed"

        closure_status = "error" if error_code else "processed"

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
        closure_status=closure_status,
        error_code=error_code,
    )
    state.supervisor_log.append(log_entry)

    return {
        "closure_status": closure_status,
        "error_code": error_code,
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

    existing_feedback = _feedback_entry(state, feedback.get("feedback_id"))
    if existing_feedback and _closure_is_complete(existing_feedback):
        return _completed_closure_result(existing_feedback)

    result = await run_feedback_closure(state, feedback=feedback)
    try:
        return await _persist_closure_result(
            session_id=session_id,
            feedback=feedback,
            result=result,
        )
    except Exception:
        failed_result = {
            **result,
            "closure_status": "error",
            "error_code": "closure_persistence_failed",
        }
        failed_result = _merge_durable_case_result(
            failed_result,
            existing_feedback,
        )
        try:
            return await _persist_closure_result(
                session_id=session_id,
                feedback=feedback,
                result=failed_result,
            )
        except Exception:
            pass
        return failed_result


async def _persist_closure_result(
    *, session_id: str, feedback: dict[str, Any], result: dict[str, Any]
) -> dict[str, Any]:
    soft_preference_updates = result["soft_preference_updates"]
    persisted_result: dict[str, Any] | None = None

    def merge_closure_result(latest_state: SharedState) -> dict[str, Any]:
        nonlocal persisted_result
        latest_feedback = _feedback_entry(
            latest_state, feedback.get("feedback_id")
        )
        if latest_feedback and _closure_is_complete(latest_feedback):
            persisted_result = _completed_closure_result(latest_feedback)
            return persisted_result
        persisted_result = _merge_durable_case_result(result, latest_feedback)
        normalized_preferences = normalize_case_soft_preferences(
            latest_state.feedback_state.case_soft_preferences
        )
        latest_state.feedback_state.case_soft_preferences = (
            merge_case_soft_preferences(
                normalized_preferences,
                soft_preference_updates,
            )
        )
        _update_feedback_closure_metadata(
            latest_state,
            feedback_id=feedback.get("feedback_id"),
            closure_status=persisted_result["closure_status"],
            case_written=bool(persisted_result["case_written"]),
            case_id=(persisted_result.get("case") or {}).get("case_id"),
            error_code=persisted_result.get("error_code"),
        )
        latest_state.supervisor_log.append(
            build_feedback_closure_log_entry(
                feedback=feedback,
                decision=persisted_result["decision"],
                case_written=persisted_result["case_written"],
                case_payload=persisted_result["case"],
                soft_preference_updates=soft_preference_updates,
                closure_status=persisted_result["closure_status"],
                error_code=persisted_result.get("error_code"),
            )
        )
        return persisted_result

    atomic_result = await mutate_state_atomically(
        session_id=session_id,
        mutator=merge_closure_result,
    )
    return atomic_result or persisted_result or result


def _feedback_entry(state: SharedState, feedback_id: Any) -> dict[str, Any] | None:
    for entry in state.feedback_state.user_feedback:
        if str(entry.get("feedback_id")) == str(feedback_id):
            return entry
    return None


def _closure_is_complete(feedback: dict[str, Any]) -> bool:
    return feedback.get("closure_status") in {"processed", "skipped"}


def _completed_closure_result(feedback: dict[str, Any]) -> dict[str, Any]:
    case_id = feedback.get("case_id")
    return {
        "closure_status": feedback["closure_status"],
        "error_code": feedback.get("error_code"),
        "decision": None,
        "case_written": bool(feedback.get("case_written")),
        "case": {"case_id": case_id} if case_id else None,
        "similar_cases": [],
        "soft_preference_updates": {},
    }


def _merge_durable_case_result(
    result: dict[str, Any], feedback: dict[str, Any] | None
) -> dict[str, Any]:
    merged = dict(result)
    if not feedback or not feedback.get("case_written"):
        return merged

    merged["case_written"] = True
    durable_case_id = feedback.get("case_id")
    if durable_case_id:
        case_payload = dict(merged.get("case") or {})
        case_payload["case_id"] = durable_case_id
        merged["case"] = case_payload
    return merged


def build_feedback_closure_log_entry(
    *,
    feedback: dict[str, Any],
    decision: dict[str, Any],
    case_written: bool,
    case_payload: dict[str, Any] | None,
    soft_preference_updates: dict[str, Any],
    closure_status: str = "processed",
    error_code: str | None = None,
) -> dict[str, Any]:
    entry = {
        "stage": "feedback_closure",
        "feedback_id": feedback.get("feedback_id"),
        "job_id": feedback.get("job_id"),
        "decision": decision,
        "case_written": case_written,
        "case_id": case_payload.get("case_id") if case_payload else None,
        "soft_preference_updates": soft_preference_updates,
        "closure_status": closure_status,
    }
    if error_code:
        entry["error_code"] = error_code
    return entry


def _update_feedback_closure_metadata(
    state: SharedState,
    *,
    feedback_id: Any,
    closure_status: str,
    case_written: bool,
    case_id: str | None,
    error_code: str | None,
) -> None:
    for entry in state.feedback_state.user_feedback:
        if str(entry.get("feedback_id")) != str(feedback_id):
            continue
        prior_case_written = bool(entry.get("case_written"))
        prior_case_id = entry.get("case_id")
        entry["closure_status"] = closure_status
        entry["case_written"] = prior_case_written or case_written
        entry["case_id"] = prior_case_id if prior_case_written else case_id
        if error_code:
            entry["error_code"] = error_code
        else:
            entry.pop("error_code", None)
        return


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
