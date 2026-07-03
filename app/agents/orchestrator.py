from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.agents.intent_agent import run_intent_agent
from app.agents.matching_agent import SearchFn, run_matching_agent
from app.agents.strategy_agent import run_strategy_agent
from app.agents.supervisor import final_verification, plan_retrieval
from app.db.state_store import save_state
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
        state.supervisor_log.append(
            {
                "stage": "reretrieval_loop",
                "trigger": "final_verification",
                "max_loops": 1,
            }
        )
        state = await run_matching_agent(
            state,
            retrieval_plan=retrieval_plan,
            search_fn=search_fn or _default_search_fn,
        )
        state = await run_strategy_agent(state)
        verification = await final_verification(state)
        verification["reretrieval_loop_used"] = 1

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
    resume_result = await intake_resume(
        resume_path,
        session_id=session_id,
        user_id=user_id,
        save_to_db=persist_state,
    )
    return await run_agentic_match_from_state(
        resume_result.state,
        user_goal_text=user_goal_text,
        top_k=top_k,
        include_raptor=include_raptor,
        persist_state=persist_state,
        search_fn=search_fn,
    )


async def _default_search_fn(**kwargs):
    from app.retrieval.hybrid_search import hybrid_search

    return await hybrid_search(**kwargs)
