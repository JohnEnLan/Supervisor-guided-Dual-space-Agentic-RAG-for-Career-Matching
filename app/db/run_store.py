from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from app.db.pool import get_pool
from app.domain.match_brief import MatchBrief, compute_plan_hash
from app.domain.run import MatchRun, RunStage, RunStatus, can_transition


class RunConflict(ValueError):
    """The stored run no longer satisfies the requested state transition."""


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _row_to_run(row: Any) -> MatchRun:
    data = dict(row)
    data["approved_plan"] = _json_value(data.get("approved_plan") or {})
    data["result_snapshot"] = _json_value(data.get("result_snapshot"))
    data["warning_codes"] = list(data.get("warning_codes") or [])
    return MatchRun.model_validate(data)


async def create_run(*, session_id: str, run_id: str | None = None) -> MatchRun:
    resolved_run_id = run_id or str(uuid.uuid4())
    pool = await get_pool()
    async with pool.acquire() as connection:
        row = await connection.fetchrow(
            """
            INSERT INTO match_runs (
                run_id, session_id, confirmed_resume_version, state_snapshot
            )
            SELECT $1, session_id, confirmed_resume_version, state
            FROM session_state
            WHERE session_id = $2
              AND resume_version > 0
              AND confirmed_resume_version = resume_version
            RETURNING run_id, session_id, confirmed_resume_version,
                      status, stage, plan_version,
                      approved_plan, result_snapshot, warning_codes, error_code,
                      execution_durability, created_at, updated_at,
                      started_at, finished_at
            """,
            resolved_run_id,
            session_id,
        )
    if row is None:
        raise RunConflict("resume must be confirmed before creating a run")
    return _row_to_run(row)


async def get_run(*, run_id: str) -> MatchRun | None:
    pool = await get_pool()
    async with pool.acquire() as connection:
        row = await connection.fetchrow(
            """
            SELECT run_id, session_id, confirmed_resume_version,
                   status, stage, plan_version,
                   approved_plan, result_snapshot, warning_codes, error_code,
                   execution_durability, created_at, updated_at,
                   started_at, finished_at
            FROM match_runs
            WHERE run_id = $1
            """,
            run_id,
        )
    return _row_to_run(row) if row is not None else None


async def save_match_brief(*, run_id: str, brief: MatchBrief) -> MatchRun:
    if compute_plan_hash(brief) != brief.plan_hash:
        raise RunConflict("match brief plan_hash is not canonical")
    pool = await get_pool()
    async with pool.acquire() as connection:
        row = await connection.fetchrow(
            """
            UPDATE match_runs
            SET status = 'plan_ready',
                stage = 'plan',
                plan_version = $2,
                approved_plan = $3::jsonb,
                plan_hash = $4,
                updated_at = now()
            WHERE run_id = $1 AND status = 'draft'
            RETURNING run_id, session_id, confirmed_resume_version,
                      status, stage, plan_version,
                      approved_plan, result_snapshot, warning_codes, error_code,
                      execution_durability, created_at, updated_at,
                      started_at, finished_at
            """,
            run_id,
            brief.plan_version,
            brief.model_dump_json(),
            brief.plan_hash,
        )
    if row is None:
        raise RunConflict("run must be draft before saving a match brief")
    return _row_to_run(row)


async def queue_run(
    *, run_id: str, plan_version: int, plan_hash: str
) -> MatchRun:
    pool = await get_pool()
    async with pool.acquire() as connection:
        row = await connection.fetchrow(
            """
            UPDATE match_runs
            SET status = 'queued', stage = NULL, updated_at = now()
            WHERE run_id = $1
              AND status = 'plan_ready'
              AND plan_version = $2
              AND plan_hash = $3
              AND COALESCE((approved_plan->>'needs_clarification')::boolean, false) = false
              AND jsonb_array_length(COALESCE(approved_plan->'conflicts', '[]'::jsonb)) = 0
            RETURNING run_id, session_id, confirmed_resume_version,
                      status, stage, plan_version,
                      approved_plan, result_snapshot, warning_codes, error_code,
                      execution_durability, created_at, updated_at,
                      started_at, finished_at
            """,
            run_id,
            plan_version,
            plan_hash,
        )
    if row is None:
        raise RunConflict(
            "run must be plan_ready with a matching, executable plan"
        )
    return _row_to_run(row)


async def transition_run(
    *,
    run_id: str,
    current_status: RunStatus,
    target_status: RunStatus,
    stage: RunStage | None = None,
    error_code: str | None = None,
) -> MatchRun:
    if not can_transition(current_status, target_status):
        raise RunConflict(
            f"invalid run transition: {current_status.value} -> {target_status.value}"
        )
    started_at = datetime.now(UTC) if target_status is RunStatus.RUNNING else None
    finished_at = (
        datetime.now(UTC)
        if target_status
        in {
            RunStatus.COMPLETED,
            RunStatus.COMPLETED_WITH_WARNINGS,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.STALE,
        }
        else None
    )
    pool = await get_pool()
    async with pool.acquire() as connection:
        row = await connection.fetchrow(
            """
            UPDATE match_runs
            SET status = $3,
                stage = $4,
                error_code = $5,
                started_at = COALESCE(started_at, $6),
                finished_at = COALESCE($7, finished_at),
                updated_at = now()
            WHERE run_id = $1 AND status = $2
            RETURNING run_id, session_id, confirmed_resume_version,
                      status, stage, plan_version,
                      approved_plan, result_snapshot, warning_codes, error_code,
                      execution_durability, created_at, updated_at,
                      started_at, finished_at
            """,
            run_id,
            current_status.value,
            target_status.value,
            stage.value if stage else None,
            error_code,
            started_at,
            finished_at,
        )
    if row is None:
        raise RunConflict("run status changed before transition completed")
    return _row_to_run(row)


async def save_run_result(
    *, run_id: str, result_snapshot: dict[str, Any], warning_codes: list[str]
) -> MatchRun:
    target_status = (
        RunStatus.COMPLETED_WITH_WARNINGS
        if warning_codes
        else RunStatus.COMPLETED
    )
    pool = await get_pool()
    async with pool.acquire() as connection:
        row = await connection.fetchrow(
            """
            UPDATE match_runs
            SET status = $2,
                stage = 'finalization',
                result_snapshot = $3::jsonb,
                warning_codes = $4,
                finished_at = now(),
                updated_at = now()
            WHERE run_id = $1 AND status = 'running'
            RETURNING run_id, session_id, confirmed_resume_version,
                      status, stage, plan_version,
                      approved_plan, result_snapshot, warning_codes, error_code,
                      execution_durability, created_at, updated_at,
                      started_at, finished_at
            """,
            run_id,
            target_status.value,
            json.dumps(result_snapshot, ensure_ascii=False),
            warning_codes,
        )
    if row is None:
        raise RunConflict("run must be running before saving a result")
    return _row_to_run(row)


async def update_run_stage(*, run_id: str, stage: RunStage) -> None:
    pool = await get_pool()
    async with pool.acquire() as connection:
        row = await connection.fetchrow(
            """
            UPDATE match_runs
            SET stage = $2, updated_at = now()
            WHERE run_id = $1 AND status = 'running'
            RETURNING run_id
            """,
            run_id,
            stage.value,
        )
    if row is None:
        raise RunConflict("run must be running before updating its stage")


async def save_state_snapshot(*, run_id: str, state_snapshot: dict[str, Any]) -> None:
    pool = await get_pool()
    async with pool.acquire() as connection:
        row = await connection.fetchrow(
            """
            UPDATE match_runs
            SET state_snapshot = $2::jsonb, updated_at = now()
            WHERE run_id = $1
            RETURNING run_id
            """,
            run_id,
            json.dumps(state_snapshot, ensure_ascii=False),
        )
    if row is None:
        raise KeyError(run_id)


async def load_state_snapshot(*, run_id: str) -> dict[str, Any] | None:
    pool = await get_pool()
    async with pool.acquire() as connection:
        row = await connection.fetchrow(
            "SELECT state_snapshot FROM match_runs WHERE run_id = $1",
            run_id,
        )
    if row is None or row["state_snapshot"] is None:
        return None
    return _json_value(row["state_snapshot"])
