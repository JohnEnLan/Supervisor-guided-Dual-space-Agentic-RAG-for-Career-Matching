from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError


def _brief(**overrides):
    from app.domain.match_brief import create_match_brief

    values = {
        "career_goal": "Find evidence-grounded data analyst roles",
        "hard_constraints": {"locations": ["Birmingham"]},
        "soft_preferences": {"preferred_role_clusters": ["data"]},
        "avoid_roles": ["sales"],
        "result_count": 5,
        "plan_version": 1,
    }
    values.update(overrides)
    return create_match_brief(**values)


def test_match_brief_hash_is_stable_for_equivalent_mapping_order() -> None:
    first = _brief(
        hard_constraints={
            "locations": ["Birmingham"],
            "need_visa_sponsor": True,
        }
    )
    second = _brief(
        hard_constraints={
            "need_visa_sponsor": True,
            "locations": ["Birmingham"],
        }
    )

    assert first.plan_hash == second.plan_hash
    assert len(first.plan_hash) == 64


def test_match_brief_hash_changes_when_execution_input_changes() -> None:
    original = _brief()
    changed_location = _brief(
        hard_constraints={"locations": ["London"]}
    )
    changed_version = _brief(plan_version=2)

    assert original.plan_hash != changed_location.plan_hash
    assert original.plan_hash != changed_version.plan_hash


def test_match_brief_is_immutable_after_confirmation() -> None:
    brief = _brief()

    with pytest.raises(ValidationError):
        brief.result_count = 10


def test_run_state_machine_allows_only_forward_lifecycle() -> None:
    from app.domain.run import RunStatus, can_transition

    assert can_transition(RunStatus.DRAFT, RunStatus.PLAN_READY)
    assert can_transition(RunStatus.PLAN_READY, RunStatus.QUEUED)
    assert can_transition(RunStatus.QUEUED, RunStatus.RUNNING)
    assert can_transition(RunStatus.RUNNING, RunStatus.COMPLETED)
    assert can_transition(RunStatus.RUNNING, RunStatus.COMPLETED_WITH_WARNINGS)
    assert not can_transition(RunStatus.COMPLETED, RunStatus.RUNNING)
    assert not can_transition(RunStatus.PLAN_READY, RunStatus.COMPLETED)


def test_match_run_uses_distinct_session_and_run_identifiers() -> None:
    from app.domain.run import MatchRun, RunStatus

    now = datetime.now(UTC)
    run = MatchRun(
        run_id="run-1",
        session_id="session-1",
        status=RunStatus.PLAN_READY,
        plan_version=1,
        approved_plan=_brief().model_dump(mode="json"),
        created_at=now,
        updated_at=now,
    )

    assert run.run_id == "run-1"
    assert run.session_id == "session-1"


def test_product_result_rejects_internal_state_fields() -> None:
    from app.domain.results import ProductResult

    with pytest.raises(ValidationError):
        ProductResult(
            summary="One result",
            recommended_roles=[],
            user_id="private-user",
        )
