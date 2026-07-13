from datetime import UTC, datetime

import pytest

from app.domain.run import MatchRun, RunStage, RunStatus


def _run(
    *,
    status: RunStatus,
    stage: RunStage | None = None,
) -> MatchRun:
    now = datetime.now(UTC)
    return MatchRun(
        run_id="run-1",
        session_id="session-1",
        status=status,
        stage=stage,
        plan_version=1,
        approved_plan={},
        created_at=now,
        updated_at=now,
    )


@pytest.mark.parametrize(
    ("status", "stage", "completed"),
    [
        (RunStatus.QUEUED, None, ["resume"]),
        (RunStatus.RUNNING, RunStage.INTENT, ["resume"]),
        (RunStatus.RUNNING, RunStage.RETRIEVAL, ["resume", "intent"]),
        (
            RunStatus.RUNNING,
            RunStage.VERIFICATION,
            ["resume", "intent", "retrieval", "strategy"],
        ),
        (
            RunStatus.COMPLETED,
            RunStage.FINALIZATION,
            [
                "resume",
                "intent",
                "retrieval",
                "strategy",
                "verification",
                "finalization",
                "result",
            ],
        ),
    ],
)
def test_public_progress_is_deterministic(status, stage, completed) -> None:
    from app.api.v1 import runs

    public_progress = getattr(runs, "public_progress", None)
    assert public_progress is not None
    assert public_progress(status=status, stage=stage) == completed


def test_match_run_exposes_approved_plan_hash() -> None:
    run = _run(status=RunStatus.PLAN_READY)

    assert run.plan_hash is None


def test_status_response_contains_recoverable_plan_and_polling_contract() -> None:
    from app.api.v1.runs import _status_response

    running = _run(status=RunStatus.RUNNING, stage=RunStage.STRATEGY)
    running.plan_hash = "a" * 64
    payload = _status_response(running)

    assert payload.retry_after_ms == 1500
    assert payload.completed_stages == ["resume", "intent", "retrieval"]
    assert payload.total_stages == 7
    assert payload.plan_version == 1
    assert payload.plan_hash == "a" * 64

    terminal = _status_response(
        _run(status=RunStatus.COMPLETED, stage=RunStage.FINALIZATION)
    )
    assert terminal.retry_after_ms is None

