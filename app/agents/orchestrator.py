from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from app.agents.intent_agent import run_intent_agent
from app.agents.matching_agent import SearchFn, run_matching_agent
from app.agents.strategy_agent import run_strategy_agent
from app.agents.supervisor import final_verification, plan_retrieval
from app.api.result_projector import project_product_result
from app.db.event_store import append_event
from app.db.run_store import (
    get_run,
    load_state_snapshot,
    save_run_result,
    save_state_snapshot,
    transition_run,
    update_run_stage,
)
from app.db.state_store import load_state, save_state
from app.domain.match_brief import MatchBrief
from app.domain.run import RunStage, RunStatus
from app.normalization.resume_intake import intake_resume
from app.state.schema import SharedState


@dataclass(frozen=True)
class AgenticMatchResult:
    state: SharedState
    retrieval_plan: dict[str, Any]
    final_verification: dict[str, Any]


async def run_persisted_agentic_match_run(*, run_id: str) -> AgenticMatchResult:
    """Execute one approved immutable Match Brief and persist public snapshots."""
    run = await get_run(run_id=run_id)
    if run is None:
        raise KeyError(f"run_id not found: {run_id}")
    brief = MatchBrief.model_validate(run.approved_plan)
    await transition_run(
        run_id=run_id,
        current_status=RunStatus.QUEUED,
        target_status=RunStatus.RUNNING,
        stage=RunStage.RETRIEVAL,
    )
    try:
        await append_event(
            run_id=run_id,
            event_type="run_started",
            stage=RunStage.RETRIEVAL.value,
            status=RunStatus.RUNNING.value,
            public_payload={"message": "Matching run started"},
        )
        initial_snapshot = await load_state_snapshot(run_id=run_id)
        if initial_snapshot is None:
            raise RuntimeError("run is missing its confirmed state snapshot")
        state = SharedState.model_validate(initial_snapshot)
        stage_started = perf_counter()
        state = await run_intent_agent(state, brief.career_goal)
        _record_stage_duration(state, "intent", stage_started)

        # The confirmed brief is the execution authority. Later agents may not
        # rewrite these constraints.
        state.career_state.current_goal = [brief.career_goal]
        state.career_state.hard_constraints = dict(brief.hard_constraints)
        state.career_state.soft_preferences = dict(brief.soft_preferences)
        state.career_state.avoid_roles = list(brief.avoid_roles)
        retrieval_plan = {
            "hard_constraints": dict(brief.hard_constraints),
            "soft_prefs": dict(brief.soft_preferences),
            "top_k": brief.result_count,
            "include_raptor": False,
        }
        state.supervisor_log.append(
            {
                "stage": "approved_match_brief",
                "plan_version": brief.plan_version,
                "plan_hash": brief.plan_hash,
                "hard_constraints_locked": True,
            }
        )
        await save_state(state, status="run_intent_done")

        stage_started = perf_counter()
        state = await run_matching_agent(
            state,
            retrieval_plan=retrieval_plan,
            search_fn=_default_search_fn,
        )
        _record_stage_duration(state, "retrieval", stage_started)
        await save_state(state, status="run_retrieval_done")

        await update_run_stage(run_id=run_id, stage=RunStage.STRATEGY)
        stage_started = perf_counter()
        state = await run_strategy_agent(state)
        _record_stage_duration(state, "strategy", stage_started)
        await save_state(state, status="run_strategy_done")
        await update_run_stage(run_id=run_id, stage=RunStage.VERIFICATION)
        stage_started = perf_counter()
        verification = await final_verification(state)
        if verification.get("reretrieval_loop_requested"):
            reretrieval_plan, reretrieval_log = _build_reretrieval_plan(
                retrieval_plan, verification
            )
            # Even recovery may only relax soft preferences.
            reretrieval_plan["hard_constraints"] = dict(
                brief.hard_constraints
            )
            state.supervisor_log.append(reretrieval_log)
            state = await run_matching_agent(
                state,
                retrieval_plan=reretrieval_plan,
                search_fn=_default_search_fn,
            )
            state = await run_strategy_agent(state)
            verification = await final_verification(state)
            verification = _mark_reretrieval_loop_used(state, verification)
        _record_stage_duration(state, "verification", stage_started)

        # Reassert the immutable contract before snapshots are published.
        state.career_state.hard_constraints = dict(brief.hard_constraints)
        await save_state(state, status="agentic_done")
        await update_run_stage(run_id=run_id, stage=RunStage.FINALIZATION)
        await save_state_snapshot(
            run_id=run_id,
            state_snapshot=state.model_dump(mode="json"),
        )
        product_result = project_product_result(state)
        warning_codes = list(product_result.warnings)
        await save_run_result(
            run_id=run_id,
            result_snapshot=product_result.model_dump(mode="json"),
            warning_codes=warning_codes,
        )
        try:
            await append_event(
                run_id=run_id,
                event_type="run_completed",
                stage=RunStage.FINALIZATION.value,
                status=(
                    RunStatus.COMPLETED_WITH_WARNINGS.value
                    if warning_codes
                    else RunStatus.COMPLETED.value
                ),
                public_payload={
                    "message": "Matching run completed",
                    "count": len(product_result.recommended_roles),
                },
            )
        except Exception:
            # The result snapshot is already terminal; observability must not
            # downgrade a successful run.
            pass
        return AgenticMatchResult(
            state=state,
            retrieval_plan=retrieval_plan,
            final_verification=verification,
        )
    except asyncio.CancelledError:
        try:
            await transition_run(
                run_id=run_id,
                current_status=RunStatus.RUNNING,
                target_status=RunStatus.CANCELLED,
                error_code="run_cancelled",
            )
        except Exception:
            pass
        raise
    except Exception:
        try:
            await transition_run(
                run_id=run_id,
                current_status=RunStatus.RUNNING,
                target_status=RunStatus.FAILED,
                error_code="run_execution_failed",
            )
        except Exception:
            pass
        try:
            await append_event(
                run_id=run_id,
                event_type="run_failed",
                status=RunStatus.FAILED.value,
                public_payload={
                    "message": "Matching run failed",
                    "reason_code": "run_execution_failed",
                },
            )
        except Exception:
            pass
        raise


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


def _record_stage_duration(
    state: SharedState, stage_name: str, started_at: float
) -> None:
    state.supervisor_log.append(
        {
            "stage": "public_stage_duration",
            "stage_name": stage_name,
            "duration_ms": max(0, round((perf_counter() - started_at) * 1000)),
        }
    )
