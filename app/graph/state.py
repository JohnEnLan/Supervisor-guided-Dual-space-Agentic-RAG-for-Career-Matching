from __future__ import annotations

from typing import Any, TypedDict

from app.domain.match_brief import MatchBrief
from app.domain.results import ProductResult
from app.state.schema import SharedState


class LoopCounters(TypedDict):
    reretrieval: int
    repair: int


class GraphState(TypedDict):
    shared: SharedState
    brief: MatchBrief
    retrieval_plan: dict[str, Any]
    verification: dict[str, Any]
    product_result: ProductResult | None
    attempt: int
    loops: LoopCounters
    run_id: str
    stage_timing: dict[str, float]
