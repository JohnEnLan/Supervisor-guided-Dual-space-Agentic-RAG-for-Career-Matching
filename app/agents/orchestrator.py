"""Supervisor Harness workflow orchestration and bounded recovery."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from app.agents.base import coerce_dict
from app.agents.intent_agent import run_intent_agent
from app.agents.matching_agent import SearchFn, run_matching_agent
from app.agents.strategy_agent import run_strategy_agent
from app.agents.supervisor import final_verification, plan_retrieval
from app.agents.supervisor_harness import record_supervisor_checkpoint
from app.api.result_projector import project_product_result
from app.config import settings
from app.db.event_store import append_event
from app.db.monitoring_store import save_run_metrics
from app.db.run_store import (
    get_run,
    load_state_snapshot,
    save_run_result,
    save_state_snapshot,
    transition_run,
    update_run_stage,
)
from app.db.state_store import mutate_state_atomically
from app.domain.match_brief import MatchBrief
from app.domain.monitoring import build_run_metrics
from app.domain.run import RunStage, RunStatus
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
        stage=RunStage.INTENT,
    )
    try:
        await append_event(
            run_id=run_id,
            event_type="run_started",
            stage=RunStage.INTENT.value,
            status=RunStatus.RUNNING.value,
            public_payload={"message": "Matching run started"},
        )
        initial_snapshot = await load_state_snapshot(run_id=run_id)
        if initial_snapshot is None:
            raise RuntimeError("run is missing its confirmed state snapshot")
        state = SharedState.model_validate(initial_snapshot)
        stage_started = perf_counter()
        state = await _run_intent_under_supervision(
            state,
            brief.career_goal,
            skip_agent=state.career_state.intent_consulted,
        )
        _record_stage_duration(state, "intent", stage_started)

        state, retrieval_plan = await _lock_approved_brief(
            state,
            brief,
            run_id=run_id,
        )

        await update_run_stage(run_id=run_id, stage=RunStage.RETRIEVAL)
        stage_started = perf_counter()
        state = await _run_matching_under_supervision(
            state,
            retrieval_plan=retrieval_plan,
            search_fn=_default_search_fn,
            locked_hard_constraints=brief.hard_constraints,
        )
        _record_stage_duration(state, "retrieval", stage_started)
        await save_state_snapshot(
            run_id=run_id,
            state_snapshot=state.model_dump(mode="json"),
        )

        await update_run_stage(run_id=run_id, stage=RunStage.STRATEGY)
        stage_started = perf_counter()
        state = await _run_strategy_under_supervision(state)
        _record_stage_duration(state, "strategy", stage_started)
        await save_state_snapshot(
            run_id=run_id,
            state_snapshot=state.model_dump(mode="json"),
        )
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
            state = await _run_matching_under_supervision(
                state,
                retrieval_plan=reretrieval_plan,
                search_fn=_default_search_fn,
                locked_hard_constraints=brief.hard_constraints,
                attempt=2,
            )
            state = await _run_strategy_under_supervision(state, attempt=2)
            verification = await final_verification(
                state,
                allow_repair=verification.get("repair_loop_used", 0) == 0,
            )
            verification = _mark_reretrieval_loop_used(state, verification)
        state, product_result = await _publish_verified_result(
            state,
            brief,
            verification,
            run_id=run_id,
            attempt=2 if verification.get("reretrieval_loop_used") else 1,
            verification_started_at=stage_started,
        )
        warning_codes = list(product_result.warnings)
        await save_run_result(
            run_id=run_id,
            result_snapshot=product_result.model_dump(mode="json"),
            warning_codes=warning_codes,
        )
        try:
            await save_run_metrics(
                run_id=run_id,
                metrics=build_run_metrics(state, product_result),
            )
        except Exception:
            # Monitoring is best-effort and may not downgrade a terminal run.
            pass
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
    state = await _run_intent_under_supervision(state, user_goal_text)
    retrieval_plan = await plan_retrieval(
        state,
        user_goal_text=user_goal_text,
        default_top_k=top_k,
        include_raptor=include_raptor,
    )
    state = await _run_matching_under_supervision(
        state,
        retrieval_plan=retrieval_plan,
        search_fn=search_fn or _default_search_fn,
    )
    state = await _run_strategy_under_supervision(state)
    verification = await final_verification(state)
    if verification.get("reretrieval_loop_requested"):
        reretrieval_plan, reretrieval_log = _build_reretrieval_plan(
            retrieval_plan, verification
        )
        state.supervisor_log.append(
            reretrieval_log
        )
        state = await _run_matching_under_supervision(
            state,
            retrieval_plan=reretrieval_plan,
            search_fn=search_fn or _default_search_fn,
            attempt=2,
        )
        state = await _run_strategy_under_supervision(state, attempt=2)
        verification = await final_verification(
            state,
            allow_repair=verification.get("repair_loop_used", 0) == 0,
        )
        verification = _mark_reretrieval_loop_used(state, verification)

    record_supervisor_checkpoint(
        state,
        checkpoint="publication_gate",
        verification=verification,
        attempt=2 if verification.get("reretrieval_loop_used") else 1,
    )

    if persist_state:
        state = await _persist_stage_state(
            state,
            status="agentic_done",
            owned_fields=(
                "resume_state",
                "career_state",
                "retrieval_state",
                "strategy_state",
            ),
        )

    return AgenticMatchResult(
        state=state,
        retrieval_plan=retrieval_plan,
        final_verification=verification,
    )


async def _default_search_fn(**kwargs):
    from app.retrieval.dual_space_search import dual_space_search

    return await dual_space_search(**kwargs)


async def _run_intent_under_supervision(
    state: SharedState,
    user_goal_text: str,
    *,
    skip_agent: bool = False,
    attempt: int = 1,
) -> SharedState:
    record_supervisor_checkpoint(
        state,
        checkpoint="intent_input",
        user_goal_text=user_goal_text,
        attempt=attempt,
    )
    if skip_agent:
        state.supervisor_log.append(
            {
                "stage": "intent_consultation_reused",
                "reason": "approved_visible_consultation",
            }
        )
    else:
        state = await run_intent_agent(state, user_goal_text)
    record_supervisor_checkpoint(
        state,
        checkpoint="intent_output",
        attempt=attempt,
    )
    return state


async def _run_matching_under_supervision(
    state: SharedState,
    *,
    retrieval_plan: dict[str, Any],
    search_fn: SearchFn,
    locked_hard_constraints: dict[str, Any] | None = None,
    attempt: int = 1,
) -> SharedState:
    record_supervisor_checkpoint(
        state,
        checkpoint="matching_input",
        retrieval_plan=retrieval_plan,
        locked_hard_constraints=locked_hard_constraints,
        attempt=attempt,
    )
    state = await run_matching_agent(
        state,
        retrieval_plan=retrieval_plan,
        search_fn=search_fn,
    )
    record_supervisor_checkpoint(
        state,
        checkpoint="matching_output",
        attempt=attempt,
    )
    return state


async def _run_strategy_under_supervision(
    state: SharedState,
    *,
    attempt: int = 1,
) -> SharedState:
    record_supervisor_checkpoint(
        state,
        checkpoint="strategy_input",
        attempt=attempt,
    )
    state = await run_strategy_agent(state)
    record_supervisor_checkpoint(
        state,
        checkpoint="strategy_output",
        attempt=attempt,
    )
    return state


async def _persist_stage_state(
    state: SharedState,
    *,
    status: str,
    owned_fields: tuple[str, ...],
) -> SharedState:
    def merge_stage(
        latest: SharedState,
        _resume_version: int = 0,
        _resume_upload_generation: int = 0,
    ) -> SharedState:
        for field_name in owned_fields:
            setattr(latest, field_name, deepcopy(getattr(state, field_name)))
        for entry in state.supervisor_log:
            if entry not in latest.supervisor_log:
                latest.supervisor_log.append(deepcopy(entry))
        return latest.model_copy(deep=True)

    return await mutate_state_atomically(
        session_id=state.session_id,
        mutator=merge_stage,
        status=status,
    )


def _build_reretrieval_plan(
    retrieval_plan: dict[str, Any],
    verification: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    reretrieval_plan = dict(retrieval_plan)
    reason = "verification_requested"
    original_soft_prefs = coerce_dict(retrieval_plan.get("soft_prefs"))
    too_few_results = coerce_dict(verification.get("too_few_results"))

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


async def _lock_approved_brief(
    state: SharedState,
    brief: MatchBrief,
    *,
    run_id: str,
) -> tuple[SharedState, dict[str, Any]]:
    """Apply the immutable brief and publish the planning snapshot."""
    state.career_state.current_goal = [brief.career_goal]
    state.career_state.hard_constraints = dict(brief.hard_constraints)
    state.career_state.soft_preferences = dict(brief.soft_preferences)
    state.career_state.avoid_roles = list(brief.avoid_roles)
    retrieval_plan = {
        "hard_constraints": dict(brief.hard_constraints),
        "soft_prefs": dict(brief.soft_preferences),
        "top_k": brief.result_count,
        "include_raptor": settings.raptor_enabled,
        "use_cross_encoder": settings.rerank_enabled,
    }
    state.supervisor_log.append(
        {
            "stage": "approved_match_brief",
            "plan_version": brief.plan_version,
            "plan_hash": brief.plan_hash,
            "hard_constraints_locked": True,
        }
    )
    state.supervisor_log.append(
        {
            "stage": "planning",
            "source": "approved_match_brief",
            "needs_clarification": False,
            "clarification_loop_used": 0,
            "retrieval_plan": _public_retrieval_plan(retrieval_plan),
        }
    )
    await save_state_snapshot(
        run_id=run_id,
        state_snapshot=state.model_dump(mode="json"),
    )
    return state, retrieval_plan


async def _publish_verified_result(
    state: SharedState,
    brief: MatchBrief,
    verification: dict[str, Any],
    *,
    run_id: str,
    attempt: int,
    verification_started_at: float,
):
    """Publish final public snapshots without saving the terminal run."""
    _record_stage_duration(
        state,
        "verification",
        verification_started_at,
    )
    state.career_state.hard_constraints = dict(brief.hard_constraints)
    record_supervisor_checkpoint(
        state,
        checkpoint="publication_gate",
        verification=verification,
        attempt=attempt,
    )
    await save_state_snapshot(
        run_id=run_id,
        state_snapshot=state.model_dump(mode="json"),
    )
    await update_run_stage(run_id=run_id, stage=RunStage.FINALIZATION)
    started_at = perf_counter()
    product_result = project_product_result(state)
    _record_stage_duration(state, "finalization", started_at)
    await save_state_snapshot(
        run_id=run_id,
        state_snapshot=state.model_dump(mode="json"),
    )
    return state, product_result


def _public_retrieval_plan(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "hard_constraints": coerce_dict(plan.get("hard_constraints")),
        "soft_prefs": coerce_dict(plan.get("soft_prefs")),
        "top_k": plan.get("top_k"),
        "include_raptor": bool(plan.get("include_raptor", False)),
        "use_cross_encoder": bool(plan.get("use_cross_encoder", False)),
    }


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


# ---------------------------------------------------------------------------
# 图路径（app/graph/nodes.py）消费的公共编排契约。
# 下划线原名保留供本模块 legacy 路径内部使用；两套名字指向同一实现，
# 契约由 tests/test_run_orchestration.py 的别名测试锚定。
# ---------------------------------------------------------------------------
run_intent_under_supervision = _run_intent_under_supervision
run_matching_under_supervision = _run_matching_under_supervision
run_strategy_under_supervision = _run_strategy_under_supervision
lock_approved_brief = _lock_approved_brief
publish_verified_result = _publish_verified_result
build_reretrieval_plan = _build_reretrieval_plan
mark_reretrieval_loop_used = _mark_reretrieval_loop_used
record_stage_duration = _record_stage_duration
default_search_fn = _default_search_fn
