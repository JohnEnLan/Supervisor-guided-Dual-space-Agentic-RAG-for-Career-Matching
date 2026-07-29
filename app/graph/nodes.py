from __future__ import annotations

from typing import Any, Literal

from app.agents import orchestrator
from app.domain.match_brief import MatchBrief
from app.domain.run import RunStage
from app.graph.state import GraphState, LoopCounters
from app.state.schema import SharedState


VERIFICATION_STARTED_AT = "verification_started_at"


async def intent(state: GraphState) -> dict[str, Any]:
    shared = SharedState.model_validate(state["shared"])
    brief = MatchBrief.model_validate(state["brief"])
    started_at = orchestrator.perf_counter()
    shared = await orchestrator._run_intent_under_supervision(
        shared,
        brief.career_goal,
        skip_agent=shared.career_state.intent_consulted,
    )
    orchestrator._record_stage_duration(shared, "intent", started_at)
    return {"shared": shared, "brief": brief}


async def lock_brief(state: GraphState) -> dict[str, Any]:
    shared = SharedState.model_validate(state["shared"])
    brief = MatchBrief.model_validate(state["brief"])
    shared, retrieval_plan = await orchestrator._lock_approved_brief(
        shared,
        brief,
        run_id=state["run_id"],
    )
    return {
        "shared": shared,
        "brief": brief,
        "retrieval_plan": retrieval_plan,
    }


async def retrieve_match(state: GraphState) -> dict[str, Any]:
    shared = SharedState.model_validate(state["shared"])
    brief = MatchBrief.model_validate(state["brief"])
    attempt = max(1, int(state["attempt"]))
    if attempt == 1:
        await orchestrator.update_run_stage(
            run_id=state["run_id"],
            stage=RunStage.RETRIEVAL,
        )
        started_at = orchestrator.perf_counter()

    shared = await orchestrator._run_matching_under_supervision(
        shared,
        retrieval_plan=state["retrieval_plan"],
        search_fn=orchestrator._default_search_fn,
        locked_hard_constraints=brief.hard_constraints,
        attempt=attempt,
    )
    if attempt == 1:
        orchestrator._record_stage_duration(
            shared,
            "retrieval",
            started_at,
        )
        await orchestrator.save_state_snapshot(
            run_id=state["run_id"],
            state_snapshot=shared.model_dump(mode="json"),
        )
    return {"shared": shared, "brief": brief}


async def strategy(state: GraphState) -> dict[str, Any]:
    shared = SharedState.model_validate(state["shared"])
    attempt = max(1, int(state["attempt"]))
    if attempt == 1:
        await orchestrator.update_run_stage(
            run_id=state["run_id"],
            stage=RunStage.STRATEGY,
        )
        started_at = orchestrator.perf_counter()

    shared = await orchestrator._run_strategy_under_supervision(
        shared,
        attempt=attempt,
    )
    if attempt == 1:
        orchestrator._record_stage_duration(
            shared,
            "strategy",
            started_at,
        )
        await orchestrator.save_state_snapshot(
            run_id=state["run_id"],
            state_snapshot=shared.model_dump(mode="json"),
        )
    return {"shared": shared}


async def verify(state: GraphState) -> dict[str, Any]:
    shared = SharedState.model_validate(state["shared"])
    attempt = max(1, int(state["attempt"]))
    loops = _loop_counters(state)
    stage_timing = dict(state["stage_timing"])
    if attempt == 1:
        await orchestrator.update_run_stage(
            run_id=state["run_id"],
            stage=RunStage.VERIFICATION,
        )
        stage_timing[VERIFICATION_STARTED_AT] = orchestrator.perf_counter()
        verification = await orchestrator.final_verification(shared)
    else:
        verification = await orchestrator.final_verification(
            shared,
            allow_repair=loops["repair"] == 0,
        )

    loops["repair"] = max(
        loops["repair"],
        min(1, int(verification.get("repair_loop_used", 0))),
    )
    if loops["reretrieval"]:
        verification = orchestrator._mark_reretrieval_loop_used(
            shared,
            verification,
        )
    return {
        "shared": shared,
        "verification": verification,
        "loops": loops,
        "stage_timing": stage_timing,
    }


async def prepare_reretrieval(state: GraphState) -> dict[str, Any]:
    loops = _loop_counters(state)
    if loops["reretrieval"] >= 1:
        return {"loops": loops}

    shared = SharedState.model_validate(state["shared"])
    brief = MatchBrief.model_validate(state["brief"])
    retrieval_plan, reretrieval_log = orchestrator._build_reretrieval_plan(
        state["retrieval_plan"],
        state["verification"],
    )
    retrieval_plan["hard_constraints"] = dict(brief.hard_constraints)
    shared.supervisor_log.append(reretrieval_log)
    loops["reretrieval"] = 1
    return {
        "shared": shared,
        "retrieval_plan": retrieval_plan,
        "attempt": 2,
        "loops": loops,
    }


async def publish(state: GraphState) -> dict[str, Any]:
    shared = SharedState.model_validate(state["shared"])
    brief = MatchBrief.model_validate(state["brief"])
    loops = _loop_counters(state)
    verification_started_at = state["stage_timing"].get(
        VERIFICATION_STARTED_AT
    )
    if verification_started_at is None:
        verification_started_at = orchestrator.perf_counter()
    shared, product_result = await orchestrator._publish_verified_result(
        shared,
        brief,
        state["verification"],
        run_id=state["run_id"],
        attempt=2 if loops["reretrieval"] else 1,
        verification_started_at=verification_started_at,
    )
    return {
        "shared": shared,
        "brief": brief,
        "product_result": product_result,
    }


def route_after_verify(
    state: GraphState,
) -> Literal["prepare_reretrieval", "publish"]:
    loops = _loop_counters(state)
    requested = bool(
        state["verification"].get("reretrieval_loop_requested")
    )
    if requested and loops["reretrieval"] == 0:
        return "prepare_reretrieval"
    return "publish"


def _loop_counters(state: GraphState) -> LoopCounters:
    loops = state["loops"]
    return {
        "reretrieval": min(1, max(0, int(loops["reretrieval"]))),
        "repair": min(1, max(0, int(loops["repair"]))),
    }
