from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from operator import add
from pathlib import Path
import sys
from typing import Annotated, Any, AsyncIterator, TypedDict
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from psycopg import OperationalError
from psycopg_pool import AsyncConnectionPool, PoolTimeout

from app.state.schema import (
    CareerState,
    FeedbackState,
    ResumeState,
    RetrievalState,
    SharedState,
    StrategyState,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT_TABLES = (
    "checkpoints",
    "checkpoint_blobs",
    "checkpoint_writes",
)


class CheckpointSpikeState(TypedDict):
    shared_state: dict[str, Any]
    node_trace: Annotated[list[str], add]


class InjectedNodeInterruption(RuntimeError):
    pass


def _run_async(coro) -> None:
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    with asyncio.Runner(loop_factory=loop_factory) as runner:
        runner.run(coro)


def _database_url() -> str:
    database_url = dotenv_values(PROJECT_ROOT / ".env").get("DATABASE_URL")
    if not database_url:
        pytest.skip(".env does not define DATABASE_URL")
    return str(database_url)


async def _probe_postgres(database_url: str) -> None:
    pool = AsyncConnectionPool(
        conninfo=database_url,
        min_size=1,
        max_size=1,
        kwargs={"autocommit": True, "prepare_threshold": 0},
        open=False,
    )
    try:
        await pool.open()
        await pool.wait(timeout=5)
    except (OperationalError, PoolTimeout, OSError) as exc:
        await pool.close()
        pytest.skip(f"PostgreSQL checkpoint tests unavailable: {exc}")
    await pool.close()


@pytest.fixture(scope="module", autouse=True)
def postgres_available() -> None:
    """Skip this PG-only module once when no test database is reachable."""
    _run_async(_probe_postgres(_database_url()))


@asynccontextmanager
async def _open_checkpointer() -> AsyncIterator[
    tuple[AsyncPostgresSaver, AsyncConnectionPool]
]:
    pool = AsyncConnectionPool(
        conninfo=_database_url(),
        min_size=1,
        max_size=4,
        kwargs={"autocommit": True, "prepare_threshold": 0},
        open=False,
    )
    try:
        await pool.open()
        await pool.wait(timeout=5)
    except (OperationalError, PoolTimeout, OSError) as exc:
        await pool.close()
        pytest.skip(f"PostgreSQL checkpoint spike unavailable: {exc}")

    try:
        checkpointer = AsyncPostgresSaver(pool)
        await checkpointer.setup()
    except (OperationalError, PoolTimeout, OSError) as exc:
        await pool.close()
        pytest.skip(f"PostgreSQL checkpoint setup unavailable: {exc}")

    try:
        yield checkpointer, pool
    finally:
        await pool.close()


async def _delete_checkpoint_threads(
    checkpointer: AsyncPostgresSaver,
    pool: AsyncConnectionPool,
    thread_ids: list[str],
) -> None:
    for thread_id in thread_ids:
        await checkpointer.adelete_thread(thread_id)

    async with pool.connection() as connection:
        for table_name in CHECKPOINT_TABLES:
            for thread_id in thread_ids:
                cursor = await connection.execute(
                    f"""
                    SELECT count(*)
                    FROM public.{table_name}
                    WHERE thread_id = %s
                    """,
                    (thread_id,),
                )
                row = await cursor.fetchone()
                assert row is not None
                assert row[0] == 0


def _sample_shared_state(*, suffix: str) -> SharedState:
    return SharedState(
        session_id=f"会话-{suffix}",
        user_id=f"用户-{suffix}",
        resume_state=ResumeState(
            education=[
                {
                    "school": "伯明翰大学",
                    "degree": "计算机科学硕士",
                    "year": "2026",
                }
            ],
            experience=[
                {
                    "company": "示例科技",
                    "role": "数据分析实习生",
                    "summary": "使用 Python 构建招聘数据看板。",
                }
            ],
            projects=[
                {
                    "name": "双空间职业匹配",
                    "description": "实现可追溯的混合检索。",
                }
            ],
            skills=["Python", "PostgreSQL", "异步编程"],
            resume_quality_issues=["量化成果仍可补充"],
            original_evidence_spans=[
                {
                    "span_id": f"R-{suffix}",
                    "text": "使用 Python 构建招聘数据看板。",
                }
            ],
            normalized_base_resume="数据分析候选人，熟悉 Python 与 PostgreSQL。",
        ),
        career_state=CareerState(
            current_goal=["数据分析师"],
            long_term_goal=["机器学习工程师"],
            hard_constraints={"locations": ["伯明翰"], "is_open": True},
            soft_preferences={"work_mode": "混合办公"},
            avoid_roles=["电话销售"],
            intent_mode="targeted",
            intent_consulted=True,
            intent_assistant_message="目标已确认。",
            intent_directions=[{"title": "数据分析", "priority": 1}],
            intent_needs_clarification=False,
            intent_clarification_used=1,
        ),
        retrieval_state=RetrievalState(
            candidate_job_ids=[f"job-{suffix}"],
            filter_log=["地点硬过滤通过"],
            ranking_scores=[
                {
                    "job_id": f"job-{suffix}",
                    "score": 0.91,
                    "evidence_span_ids": [f"JD-{suffix}"],
                }
            ],
            evidence_span_ids=[f"JD-{suffix}"],
        ),
        strategy_state=StrategyState(
            recommended_roles=[
                {
                    "job_id": f"job-{suffix}",
                    "tier": "now_fit",
                    "evidence_span_ids": [f"JD-{suffix}"],
                }
            ],
            resume_revision_plan=[
                {
                    "section": "项目经历",
                    "suggestion": "保留真实量化结果。",
                    "evidence_span_ids": [f"R-{suffix}"],
                }
            ],
            career_path=[{"step": 1, "role": "数据分析师"}],
            skill_gap_analysis=[{"skill": "统计建模", "priority": "high"}],
        ),
        feedback_state=FeedbackState(
            application_history=[{"job_id": f"job-{suffix}", "status": "saved"}],
            interview_outcomes=[{"job_id": f"job-{suffix}", "outcome": "待定"}],
            user_feedback=[{"message": "推荐结果相关"}],
            case_soft_preferences={"preferred_industry": "科技"},
        ),
        supervisor_log=[
            {
                "stage": "planning",
                "message": "中文 SharedState checkpoint spike",
            }
        ],
    )


def _build_two_node_graph(
    checkpointer: AsyncPostgresSaver,
    *,
    execution_counts: dict[str, int] | None = None,
    interrupt_first_node_b_attempt: bool = False,
):
    counts = execution_counts if execution_counts is not None else {"A": 0, "B": 0}

    async def node_a(_state: CheckpointSpikeState) -> dict[str, list[str]]:
        counts["A"] += 1
        return {"node_trace": ["A"]}

    async def node_b(_state: CheckpointSpikeState) -> dict[str, list[str]]:
        counts["B"] += 1
        if interrupt_first_node_b_attempt and counts["B"] == 1:
            raise InjectedNodeInterruption("interrupted after node A checkpoint")
        return {"node_trace": ["B"]}

    builder = StateGraph(CheckpointSpikeState)
    builder.add_node("node_a", node_a)
    builder.add_node("node_b", node_b)
    builder.add_edge(START, "node_a")
    builder.add_edge("node_a", "node_b")
    builder.add_edge("node_b", END)
    return builder.compile(checkpointer=checkpointer)


def _config(thread_id: str) -> dict[str, Any]:
    return {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": 12,
    }


async def _assert_full_shared_state_round_trip() -> None:
    thread_id = f"checkpoint-spike-roundtrip-{uuid4()}"
    expected = _sample_shared_state(suffix="往返")

    async with _open_checkpointer() as (checkpointer, pool):
        try:
            graph = _build_two_node_graph(checkpointer)
            result = await graph.ainvoke(
                {
                    "shared_state": expected.model_dump(mode="json"),
                    "node_trace": [],
                },
                config=_config(thread_id),
                durability="sync",
            )
            persisted = await graph.aget_state(_config(thread_id))

            assert result["node_trace"] == ["A", "B"]
            assert persisted.values["node_trace"] == ["A", "B"]
            assert (
                SharedState.model_validate(persisted.values["shared_state"])
                == expected
            )
        finally:
            await _delete_checkpoint_threads(
                checkpointer,
                pool,
                [thread_id],
            )


async def _assert_concurrent_thread_isolation() -> None:
    thread_ids = [
        f"checkpoint-spike-concurrent-left-{uuid4()}",
        f"checkpoint-spike-concurrent-right-{uuid4()}",
    ]
    expected_states = [
        _sample_shared_state(suffix="并发甲"),
        _sample_shared_state(suffix="并发乙"),
    ]

    async with _open_checkpointer() as (checkpointer, pool):
        try:
            graph = _build_two_node_graph(checkpointer)
            results = await asyncio.gather(
                *(
                    graph.ainvoke(
                        {
                            "shared_state": expected.model_dump(mode="json"),
                            "node_trace": [],
                        },
                        config=_config(thread_id),
                        durability="sync",
                    )
                    for thread_id, expected in zip(
                        thread_ids,
                        expected_states,
                        strict=True,
                    )
                )
            )
            persisted = await asyncio.gather(
                *(graph.aget_state(_config(thread_id)) for thread_id in thread_ids)
            )

            assert [
                SharedState.model_validate(result["shared_state"])
                for result in results
            ] == expected_states
            assert [
                SharedState.model_validate(snapshot.values["shared_state"])
                for snapshot in persisted
            ] == expected_states
            assert expected_states[0].session_id != expected_states[1].session_id
        finally:
            await _delete_checkpoint_threads(
                checkpointer,
                pool,
                thread_ids,
            )


async def _assert_node_b_resume_without_node_a_reexecution() -> None:
    thread_id = f"checkpoint-spike-resume-{uuid4()}"
    expected = _sample_shared_state(suffix="断点续跑")
    execution_counts = {"A": 0, "B": 0}

    async with _open_checkpointer() as (first_checkpointer, _first_pool):
        first_graph = _build_two_node_graph(
            first_checkpointer,
            execution_counts=execution_counts,
            interrupt_first_node_b_attempt=True,
        )
        with pytest.raises(
            InjectedNodeInterruption,
            match="after node A checkpoint",
        ):
            await first_graph.ainvoke(
                {
                    "shared_state": expected.model_dump(mode="json"),
                    "node_trace": [],
                },
                config=_config(thread_id),
                durability="sync",
            )

        interrupted = await first_graph.aget_state(_config(thread_id))
        assert interrupted.values["node_trace"] == ["A"]
        assert interrupted.next == ("node_b",)
        assert execution_counts == {"A": 1, "B": 1}

    async with _open_checkpointer() as (resumed_checkpointer, resumed_pool):
        try:
            resumed_graph = _build_two_node_graph(
                resumed_checkpointer,
                execution_counts=execution_counts,
                interrupt_first_node_b_attempt=True,
            )
            result = await resumed_graph.ainvoke(
                None,
                config=_config(thread_id),
                durability="sync",
            )

            assert result["node_trace"] == ["A", "B"]
            assert SharedState.model_validate(result["shared_state"]) == expected
            assert execution_counts == {"A": 1, "B": 2}
        finally:
            await _delete_checkpoint_threads(
                resumed_checkpointer,
                resumed_pool,
                [thread_id],
            )


def test_full_shared_state_round_trips_through_postgres_checkpoint() -> None:
    _run_async(_assert_full_shared_state_round_trip())


def test_concurrent_thread_ids_keep_shared_states_isolated() -> None:
    _run_async(_assert_concurrent_thread_isolation())


def test_new_graph_resumes_at_node_b_without_reexecuting_node_a() -> None:
    _run_async(_assert_node_b_resume_without_node_a_reexecution())
