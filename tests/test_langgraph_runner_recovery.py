from __future__ import annotations

import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any, AsyncIterator
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg import OperationalError
from psycopg_pool import AsyncConnectionPool, PoolTimeout

from app.domain.match_brief import MatchBrief, create_match_brief
from app.domain.results import ProductResult
from app.domain.run import MatchRun, RunStage, RunStatus
from app.state.schema import CareerState, ResumeState, SharedState


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT_TABLES = (
    "checkpoints",
    "checkpoint_blobs",
    "checkpoint_writes",
)


class SimulatedProcessCrash(BaseException):
    """A hard stop that must bypass the runner's business-failure mapping."""


def _run_async(coro) -> None:
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    with asyncio.Runner(loop_factory=loop_factory) as runner:
        runner.run(coro)


def _database_url() -> str:
    database_url = dotenv_values(PROJECT_ROOT / ".env").get("DATABASE_URL")
    if not database_url:
        pytest.fail(".env must define DATABASE_URL for the S4 recovery gate")
    return str(database_url)


@asynccontextmanager
async def _open_checkpointer(
    database_url: str,
) -> AsyncIterator[tuple[AsyncPostgresSaver, AsyncConnectionPool]]:
    pool = AsyncConnectionPool(
        conninfo=database_url,
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
        pytest.fail(f"PostgreSQL runner recovery unavailable: {exc}")

    try:
        checkpointer = AsyncPostgresSaver(
            pool,
            serde=JsonPlusSerializer(
                allowed_msgpack_modules=[
                    SharedState,
                    MatchBrief,
                    ProductResult,
                ],
            ),
        )
        await checkpointer.setup()
    except (OperationalError, PoolTimeout, OSError) as exc:
        await pool.close()
        pytest.fail(f"PostgreSQL checkpoint setup unavailable: {exc}")

    try:
        yield checkpointer, pool
    finally:
        await pool.close()


def _brief() -> MatchBrief:
    return create_match_brief(
        career_goal="Find evidence-grounded data analyst roles in Birmingham",
        hard_constraints={"locations": ["Birmingham"], "is_open": True},
        soft_preferences={},
        avoid_roles=["sales"],
        result_count=3,
        plan_version=1,
    )


def _state(session_id: str) -> SharedState:
    return SharedState(
        session_id=session_id,
        user_id=f"user-{session_id}",
        resume_state=ResumeState(
            skills=["Python", "SQL"],
            normalized_base_resume="Python data analyst in Birmingham.",
            original_evidence_spans=[
                {
                    "span_id": "R-001",
                    "text": "Built a Python hiring dashboard.",
                }
            ],
        ),
        career_state=CareerState(),
    )


async def _insert_queued_runs(
    pool: AsyncConnectionPool,
    *,
    session_ids: list[str],
    run_ids: list[str],
    brief: MatchBrief,
) -> None:
    async with pool.connection() as connection:
        for session_id in session_ids:
            state = _state(session_id)
            await connection.execute(
                """
                INSERT INTO session_state (
                    session_id, user_id, state, status,
                    resume_version, confirmed_resume_version
                )
                VALUES (%s, %s, %s::jsonb, 'match_brief_approved', 1, 1)
                """,
                (
                    session_id,
                    state.user_id,
                    state.model_dump_json(),
                ),
            )
        for run_id, session_id in zip(run_ids, session_ids, strict=True):
            state = _state(session_id)
            await connection.execute(
                """
                INSERT INTO match_runs (
                    run_id, session_id, confirmed_resume_version,
                    status, stage, plan_version, approved_plan,
                    plan_hash, state_snapshot
                )
                VALUES (
                    %s, %s, 1, 'queued', NULL, %s,
                    %s::jsonb, %s, %s::jsonb
                )
                """,
                (
                    run_id,
                    session_id,
                    brief.plan_version,
                    brief.model_dump_json(),
                    brief.plan_hash,
                    state.model_dump_json(),
                ),
            )


async def _delete_test_rows(
    checkpointer: AsyncPostgresSaver,
    pool: AsyncConnectionPool,
    *,
    run_ids: list[str],
    session_ids: list[str],
) -> None:
    for run_id in run_ids:
        await checkpointer.adelete_thread(run_id)
    async with pool.connection() as connection:
        await connection.execute(
            "DELETE FROM match_runs WHERE run_id = ANY(%s)",
            (run_ids,),
        )
        await connection.execute(
            "DELETE FROM session_state WHERE session_id = ANY(%s)",
            (session_ids,),
        )


async def _checkpoint_row_counts(
    pool: AsyncConnectionPool,
    run_id: str,
) -> dict[str, int]:
    counts = {}
    async with pool.connection() as connection:
        for table_name in CHECKPOINT_TABLES:
            cursor = await connection.execute(
                f"""
                SELECT count(*)
                FROM public.{table_name}
                WHERE thread_id = %s
                """,
                (run_id,),
            )
            row = await cursor.fetchone()
            assert row is not None
            counts[table_name] = int(row[0])
    return counts


def _populate_matching_state(state: SharedState) -> SharedState:
    state.retrieval_state.candidate_job_ids = ["job-1"]
    state.retrieval_state.evidence_span_ids = ["job-1:required_skills:1"]
    state.retrieval_state.ranking_scores = [
        {
            "job_id": "job-1",
            "score": 0.95,
            "evidence_span_ids": ["job-1:required_skills:1"],
            "evidence_spans": [
                {
                    "evidence_span_id": "job-1:required_skills:1",
                    "field": "required_skills",
                    "content": "Python and SQL required.",
                }
            ],
        }
    ]
    return state


def _populate_strategy_state(state: SharedState) -> SharedState:
    state.strategy_state.recommended_roles = [
        {
            "job_id": "job-1",
            "title": "Data Analyst",
            "location": "Birmingham",
            "tier": "now_fit",
            "hard_constraint_passed": True,
            "evidence_span_ids": ["job-1:required_skills:1"],
            "resume_evidence_span_ids": ["R-001"],
            "explicit_explanation": "Python and SQL align with the JD.",
        }
    ]
    return state


async def _assert_runner_recovers_and_cleans_checkpoints(monkeypatch) -> None:
    from app.agents import orchestrator, supervisor
    from app.db import pool as asyncpg_pool
    from app.db import run_store
    from app.graph import runner

    database_url = _database_url()
    interrupted_run_id = f"runner-recovery-interrupted-{uuid4()}"
    uninterrupted_run_id = f"runner-recovery-control-{uuid4()}"
    run_ids = [interrupted_run_id, uninterrupted_run_id]
    session_ids = [
        f"runner-recovery-session-{uuid4()}",
        f"runner-recovery-session-{uuid4()}",
    ]
    brief = _brief()
    execution_counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {"intent": 0, "retrieve_match": 0, "strategy": 0}
    )
    terminal_save_counts: dict[str, int] = defaultdict(int)
    graph_inputs: list[tuple[str, bool]] = []

    await asyncpg_pool.close_pool()
    monkeypatch.setattr(asyncpg_pool.settings, "database_url", database_url)
    monkeypatch.setattr(asyncpg_pool.settings, "db_pool_min", 1)
    monkeypatch.setattr(asyncpg_pool.settings, "db_pool_max", 4)

    async def intent(state: SharedState, goal: str) -> SharedState:
        execution_counts[state.session_id]["intent"] += 1
        state.career_state.current_goal = [goal]
        return state

    async def matching(
        state: SharedState,
        *,
        retrieval_plan,
        search_fn,
    ) -> SharedState:
        del retrieval_plan, search_fn
        execution_counts[state.session_id]["retrieve_match"] += 1
        return _populate_matching_state(state)

    async def strategy(state: SharedState) -> SharedState:
        execution_counts[state.session_id]["strategy"] += 1
        return _populate_strategy_state(state)

    async def chat(*_args, **_kwargs) -> str:
        return json.dumps(
            {
                "hard_filter_violations": [],
                "missing_evidence": [],
                "fabrication_risks": [],
                "too_few_results": {},
                "needs_reretrieval": False,
                "needs_repair": False,
            }
        )

    original_save_run_result = orchestrator.save_run_result

    async def counted_save_run_result(*, run_id: str, **kwargs):
        terminal_save_counts[run_id] += 1
        return await original_save_run_result(run_id=run_id, **kwargs)

    monkeypatch.setattr(orchestrator, "run_intent_agent", intent)
    monkeypatch.setattr(orchestrator, "run_matching_agent", matching)
    monkeypatch.setattr(orchestrator, "run_strategy_agent", strategy)
    monkeypatch.setattr(supervisor.deepseek, "chat", chat)
    monkeypatch.setattr(
        orchestrator,
        "save_run_result",
        counted_save_run_result,
    )

    real_build_graph = runner.build_graph
    inserted = False
    async with _open_checkpointer(database_url) as (
        first_checkpointer,
        first_pool,
    ):
        await _insert_queued_runs(
            first_pool,
            session_ids=session_ids,
            run_ids=run_ids,
            brief=brief,
        )
        inserted = True
        inner_graph = real_build_graph(checkpointer=first_checkpointer)

        class CrashAfterStrategy:
            async def ainvoke(self, graph_input, config, *, durability):
                await inner_graph.ainvoke(
                    graph_input,
                    config=config,
                    durability=durability,
                    interrupt_after=["strategy"],
                )
                interrupted = await inner_graph.aget_state(config)
                assert interrupted.next == ("verify",)
                raise SimulatedProcessCrash("process died after strategy")

        monkeypatch.setattr(
            runner,
            "build_graph",
            lambda **_kwargs: CrashAfterStrategy(),
        )

        with pytest.raises(
            SimulatedProcessCrash,
            match="after strategy",
        ):
            await runner.run_graph_match(
                run_id=interrupted_run_id,
                checkpointer=first_checkpointer,
            )

        interrupted_run = await run_store.get_run(run_id=interrupted_run_id)
        assert interrupted_run is not None
        assert interrupted_run.status is RunStatus.RUNNING
        assert interrupted_run.stage is not None
        assert interrupted_run.stage.value == "strategy"
        assert execution_counts[session_ids[0]] == {
            "intent": 1,
            "retrieve_match": 1,
            "strategy": 1,
        }
        assert terminal_save_counts[interrupted_run_id] == 0
        interrupted_checkpoint_counts = await _checkpoint_row_counts(
            first_pool,
            interrupted_run_id,
        )
        assert all(count > 0 for count in interrupted_checkpoint_counts.values())

    def build_spied_graph(*, checkpointer=None):
        inner = real_build_graph(checkpointer=checkpointer)

        class InputRecordingGraph:
            async def ainvoke(self, graph_input, config, *, durability):
                graph_inputs.append(
                    (
                        config["configurable"]["thread_id"],
                        graph_input is None,
                    )
                )
                return await inner.ainvoke(
                    graph_input,
                    config=config,
                    durability=durability,
                )

        return InputRecordingGraph()

    monkeypatch.setattr(runner, "build_graph", build_spied_graph)
    async with _open_checkpointer(database_url) as (
        resumed_checkpointer,
        resumed_pool,
    ):
        try:
            resumed_result = await runner.run_graph_match(
                run_id=interrupted_run_id,
                checkpointer=resumed_checkpointer,
            )
            assert execution_counts[session_ids[0]] == {
                "intent": 1,
                "retrieve_match": 1,
                "strategy": 1,
            }

            control_result = await runner.run_graph_match(
                run_id=uninterrupted_run_id,
                checkpointer=resumed_checkpointer,
            )
            assert execution_counts[session_ids[1]] == {
                "intent": 1,
                "retrieve_match": 1,
                "strategy": 1,
            }
            assert graph_inputs == [
                (interrupted_run_id, True),
                (uninterrupted_run_id, False),
            ]

            interrupted_terminal = await run_store.get_run(
                run_id=interrupted_run_id
            )
            control_terminal = await run_store.get_run(
                run_id=uninterrupted_run_id
            )
            assert interrupted_terminal is not None
            assert control_terminal is not None
            assert interrupted_terminal.status is RunStatus.COMPLETED
            assert control_terminal.status is RunStatus.COMPLETED
            assert (
                interrupted_terminal.result_snapshot
                == control_terminal.result_snapshot
            )
            assert (
                resumed_result.final_verification
                == control_result.final_verification
            )

            repeated_result = await runner.run_graph_match(
                run_id=interrupted_run_id,
                checkpointer=resumed_checkpointer,
            )
            assert repeated_result == resumed_result
            assert terminal_save_counts == {
                interrupted_run_id: 1,
                uninterrupted_run_id: 1,
            }
            assert execution_counts[session_ids[0]] == {
                "intent": 1,
                "retrieve_match": 1,
                "strategy": 1,
            }

            for run_id in run_ids:
                assert await _checkpoint_row_counts(resumed_pool, run_id) == {
                    table_name: 0 for table_name in CHECKPOINT_TABLES
                }
            terminal_checkpoint_threads = (
                await run_store.list_terminal_checkpoint_thread_ids()
            )
            assert not set(run_ids) & set(terminal_checkpoint_threads)
        finally:
            await asyncpg_pool.close_pool()
            if inserted:
                await _delete_test_rows(
                    resumed_checkpointer,
                    resumed_pool,
                    run_ids=run_ids,
                    session_ids=session_ids,
                )


def test_runner_resumes_after_strategy_without_reexecution_and_cleans_pg(
    monkeypatch,
) -> None:
    _run_async(_assert_runner_recovers_and_cleans_checkpoints(monkeypatch))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("outcome", "terminal_status"),
    [
        ("failure", RunStatus.FAILED),
        ("cancelled", RunStatus.CANCELLED),
    ],
)
async def test_runner_cleans_checkpoint_after_mapped_terminal_error(
    monkeypatch,
    outcome,
    terminal_status,
) -> None:
    from app.agents import orchestrator
    from app.graph import runner

    brief = _brief()
    state = _state("terminal-cleanup-session")
    now = datetime.now(UTC)
    stored_status = RunStatus.QUEUED
    deleted_threads: list[str] = []
    run = MatchRun(
        run_id="terminal-cleanup-run",
        session_id=state.session_id,
        status=RunStatus.QUEUED,
        approved_plan=brief.model_dump(mode="json"),
        plan_version=brief.plan_version,
        plan_hash=brief.plan_hash,
        created_at=now,
        updated_at=now,
    )

    async def get_run(*, run_id: str):
        assert run_id == run.run_id
        return run.model_copy(update={"status": stored_status})

    async def transition_run(
        *,
        current_status,
        target_status,
        **_kwargs,
    ):
        nonlocal stored_status
        assert stored_status is current_status
        stored_status = target_status
        return run.model_copy(update={"status": target_status})

    async def no_op(**_kwargs):
        return None

    async def load_snapshot(**_kwargs):
        return state.model_dump(mode="json")

    class FailingGraph:
        async def ainvoke(self, _state, config, *, durability):
            assert config["configurable"]["thread_id"] == run.run_id
            assert durability == "sync"
            if outcome == "cancelled":
                raise asyncio.CancelledError
            raise RuntimeError("injected failure")

    class RecordingCheckpointer:
        async def adelete_thread(self, thread_id: str):
            deleted_threads.append(thread_id)

    monkeypatch.setattr(orchestrator, "get_run", get_run)
    monkeypatch.setattr(orchestrator, "transition_run", transition_run)
    monkeypatch.setattr(orchestrator, "append_event", no_op)
    monkeypatch.setattr(orchestrator, "load_state_snapshot", load_snapshot)
    monkeypatch.setattr(runner, "build_graph", lambda **_kwargs: FailingGraph())

    expected_error = (
        asyncio.CancelledError if outcome == "cancelled" else RuntimeError
    )
    with pytest.raises(expected_error):
        await runner.run_graph_match(
            run_id=run.run_id,
            checkpointer=RecordingCheckpointer(),
        )

    assert stored_status is terminal_status
    assert deleted_threads == [run.run_id]


@pytest.mark.asyncio
async def test_runner_retains_checkpoint_when_terminal_transition_loses_cas(
    monkeypatch,
) -> None:
    from app.agents import orchestrator
    from app.db.run_store import RunConflict
    from app.graph import runner

    brief = _brief()
    state = _state("transition-conflict-session")
    now = datetime.now(UTC)
    stored_status = RunStatus.QUEUED
    deleted_threads: list[str] = []
    run = MatchRun(
        run_id="transition-conflict-run",
        session_id=state.session_id,
        status=stored_status,
        approved_plan=brief.model_dump(mode="json"),
        plan_version=brief.plan_version,
        plan_hash=brief.plan_hash,
        created_at=now,
        updated_at=now,
    )

    async def get_run(**_kwargs):
        return run.model_copy(update={"status": stored_status})

    async def transition_run(*, current_status, target_status, **_kwargs):
        nonlocal stored_status
        assert stored_status is current_status
        if target_status is RunStatus.FAILED:
            raise RunConflict("terminal CAS lost")
        stored_status = target_status
        return run.model_copy(update={"status": target_status})

    async def no_op(**_kwargs):
        return None

    async def load_snapshot(**_kwargs):
        return state.model_dump(mode="json")

    class FailingGraph:
        async def ainvoke(self, _state, config, *, durability):
            del config, durability
            raise RuntimeError("injected graph failure")

    class RecordingCheckpointer:
        async def adelete_thread(self, thread_id: str):
            deleted_threads.append(thread_id)

    monkeypatch.setattr(orchestrator, "get_run", get_run)
    monkeypatch.setattr(orchestrator, "transition_run", transition_run)
    monkeypatch.setattr(orchestrator, "append_event", no_op)
    monkeypatch.setattr(orchestrator, "load_state_snapshot", load_snapshot)
    monkeypatch.setattr(runner, "build_graph", lambda **_kwargs: FailingGraph())

    with pytest.raises(RuntimeError, match="injected graph failure"):
        await runner.run_graph_match(
            run_id=run.run_id,
            checkpointer=RecordingCheckpointer(),
        )

    assert stored_status is RunStatus.RUNNING
    assert deleted_threads == []
