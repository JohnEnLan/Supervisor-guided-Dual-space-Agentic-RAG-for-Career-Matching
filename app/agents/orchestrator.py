from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.agents.intent_agent import run_intent_agent
from app.agents.matching_agent import SearchFn, run_matching_agent
from app.agents.strategy_agent import run_strategy_agent
from app.agents.supervisor import final_verification, plan_retrieval
from app.db.state_store import load_state, save_state
from app.normalization.resume_intake import intake_resume
from app.state.schema import SharedState


@dataclass(frozen=True)
class AgenticMatchResult:
    state: SharedState
    retrieval_plan: dict[str, Any]
    final_verification: dict[str, Any]


async def run_agentic_match_from_state(
    state: SharedState,
    *,
    user_goal_text: str,
    top_k: int = 5,
    include_raptor: bool = False,
    persist_state: bool = False,
    search_fn: SearchFn | None = None,
) -> AgenticMatchResult:
    state = await run_intent_agent(state, user_goal_text)
    retrieval_plan = await plan_retrieval(
        state,
        user_goal_text=user_goal_text,
        default_top_k=top_k,
        include_raptor=include_raptor,
    )
    state = await run_matching_agent(
        state,
        retrieval_plan=retrieval_plan,
        search_fn=search_fn or _default_search_fn,
    )
    state = await run_strategy_agent(state)
    verification = await final_verification(state)
    if verification.get("reretrieval_loop_requested"):
        reretrieval_plan, reretrieval_log = _build_reretrieval_plan(
            retrieval_plan, verification
        )
        state.supervisor_log.append(
            reretrieval_log
        )
        state = await run_matching_agent(
            state,
            retrieval_plan=reretrieval_plan,
            search_fn=search_fn or _default_search_fn,
        )
        state = await run_strategy_agent(state)
        verification = await final_verification(state)
        verification = _mark_reretrieval_loop_used(state, verification)

    if persist_state:
        await save_state(state, status="agentic_done")

    return AgenticMatchResult(
        state=state,
        retrieval_plan=retrieval_plan,
        final_verification=verification,
    )


async def run_agentic_match_from_resume(
    resume_path: Path,
    *,
    session_id: str,
    user_id: str,
    user_goal_text: str,
    top_k: int = 5,
    include_raptor: bool = False,
    persist_state: bool = True,
    search_fn: SearchFn | None = None,
) -> AgenticMatchResult:
    if persist_state:
        return await run_persisted_agentic_match_from_resume(
            resume_path,
            session_id=session_id,
            user_id=user_id,
            user_goal_text=user_goal_text,
            top_k=top_k,
            include_raptor=include_raptor,
            search_fn=search_fn,
        )

    resume_result = await intake_resume(
        resume_path,
        session_id=session_id,
        user_id=user_id,
        save_to_db=False,
    )
    return await run_agentic_match_from_state(
        resume_result.state,
        user_goal_text=user_goal_text,
        top_k=top_k,
        include_raptor=include_raptor,
        persist_state=False,
        search_fn=search_fn,
    )


async def run_persisted_agentic_match_from_resume(
    resume_path: Path,
    *,
    session_id: str,
    user_id: str,
    user_goal_text: str,
    top_k: int = 5,
    include_raptor: bool = False,
    search_fn: SearchFn | None = None,
) -> AgenticMatchResult:
    resume_result = await intake_resume(
        resume_path,
        session_id=session_id,
        user_id=user_id,
        save_to_db=False,
    )
    state = resume_result.state
    await save_state(state, status="resume_normalized")

    return await run_persisted_agentic_match_from_session(
        session_id=session_id,
        user_goal_text=user_goal_text,
        top_k=top_k,
        include_raptor=include_raptor,
        search_fn=search_fn,
    )


async def run_persisted_agentic_match_from_session(
    *,
    session_id: str,
    user_goal_text: str,
    top_k: int = 5,
    include_raptor: bool = False,
    search_fn: SearchFn | None = None,
) -> AgenticMatchResult:
    state = await _load_required_state(session_id)

    state = await run_intent_agent(state, user_goal_text)
    await save_state(state, status="intent_done")

    state = await _load_required_state(session_id)
    retrieval_plan = await plan_retrieval(
        state,
        user_goal_text=user_goal_text,
        default_top_k=top_k,
        include_raptor=include_raptor,
    )
    await save_state(state, status="supervisor_planning_done")

    state = await _load_required_state(session_id)
    state = await run_matching_agent(
        state,
        retrieval_plan=retrieval_plan,
        search_fn=search_fn or _default_search_fn,
    )
    await save_state(state, status="retrieval_done")

    state = await _load_required_state(session_id)
    state = await run_strategy_agent(state)
    await save_state(state, status="strategy_done")

    state = await _load_required_state(session_id)
    verification = await final_verification(state)
    if verification.get("reretrieval_loop_requested"):
        reretrieval_plan, reretrieval_log = _build_reretrieval_plan(
            retrieval_plan, verification
        )
        state.supervisor_log.append(reretrieval_log)
        await save_state(state, status="reretrieval_planned")

        state = await _load_required_state(session_id)
        state = await run_matching_agent(
            state,
            retrieval_plan=reretrieval_plan,
            search_fn=search_fn or _default_search_fn,
        )
        await save_state(state, status="reretrieval_done")

        state = await _load_required_state(session_id)
        state = await run_strategy_agent(state)
        await save_state(state, status="strategy_rerun_done")

        state = await _load_required_state(session_id)
        verification = await final_verification(state)
        verification = _mark_reretrieval_loop_used(state, verification)

    await save_state(state, status="agentic_done")
    return AgenticMatchResult(
        state=state,
        retrieval_plan=retrieval_plan,
        final_verification=verification,
    )


async def _default_search_fn(**kwargs):
    from app.retrieval.dual_space_search import dual_space_search

    return await dual_space_search(**kwargs)


async def _load_required_state(session_id: str) -> SharedState:
    state = await load_state(session_id)
    if state is None:
        raise KeyError(f"session_id not found in state_store: {session_id}")
    return state


def _build_reretrieval_plan(
    retrieval_plan: dict[str, Any],
    verification: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    reretrieval_plan = dict(retrieval_plan)
    reason = "verification_requested"
    original_soft_prefs = _as_dict(retrieval_plan.get("soft_prefs"))
    too_few_results = _as_dict(verification.get("too_few_results"))

    if too_few_results:
        reason = "too_few_results"
        reretrieval_plan["soft_prefs"] = {}

    log_entry = {
        "stage": "reretrieval_loop",
        "trigger": "final_verification",
        "reason": reason,
        "max_loops": 1,
        "loop_used": 1,
        "reretrieval_plan": _public_retrieval_plan(reretrieval_plan),
    }
    if too_few_results:
        log_entry["too_few_results"] = too_few_results
        log_entry["relaxed_soft_prefs"] = original_soft_prefs

    return reretrieval_plan, log_entry


def _mark_reretrieval_loop_used(
    state: SharedState,
    verification: dict[str, Any],
) -> dict[str, Any]:
    verification = dict(verification)
    verification["reretrieval_loop_used"] = 1
    for entry in reversed(state.supervisor_log):
        if entry.get("stage") == "final_verification":
            entry["reretrieval_loop_used"] = 1
            break
    return verification


def _public_retrieval_plan(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "hard_constraints": _as_dict(plan.get("hard_constraints")),
        "soft_prefs": _as_dict(plan.get("soft_prefs")),
        "top_k": plan.get("top_k"),
        "include_raptor": bool(plan.get("include_raptor", False)),
    }


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
