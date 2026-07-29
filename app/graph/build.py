from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from app.graph.nodes import (
    intent,
    lock_brief,
    prepare_reretrieval,
    publish,
    retrieve_match,
    route_after_verify,
    strategy,
    verify,
)
from app.graph.state import GraphState


def build_graph(checkpointer: Any = None):
    builder = StateGraph(GraphState)
    builder.add_node("intent", intent)
    builder.add_node("lock_brief", lock_brief)
    builder.add_node("retrieve_match", retrieve_match)
    builder.add_node("strategy", strategy)
    builder.add_node("verify", verify)
    builder.add_node("prepare_reretrieval", prepare_reretrieval)
    builder.add_node("publish", publish)

    builder.add_edge(START, "intent")
    builder.add_edge("intent", "lock_brief")
    builder.add_edge("lock_brief", "retrieve_match")
    builder.add_edge("retrieve_match", "strategy")
    builder.add_edge("strategy", "verify")
    builder.add_conditional_edges(
        "verify",
        route_after_verify,
        {
            "prepare_reretrieval": "prepare_reretrieval",
            "publish": "publish",
        },
    )
    builder.add_edge("prepare_reretrieval", "retrieve_match")
    builder.add_edge("publish", END)
    return builder.compile(checkpointer=checkpointer)
