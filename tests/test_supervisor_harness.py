import pytest

from app.state.schema import CareerState, ResumeState, RetrievalState, SharedState


def _state() -> SharedState:
    return SharedState(
        session_id="session-1",
        user_id="user-1",
        resume_state=ResumeState(
            normalized_base_resume="Python data analyst",
            original_evidence_spans=[
                {"span_id": "R001", "text": "Built a Python dashboard."}
            ],
        ),
        career_state=CareerState(
            current_goal=["data analyst"],
            hard_constraints={"locations": ["Birmingham"]},
        ),
    )


def test_checkpoint_records_privacy_safe_passed_log() -> None:
    from app.agents.supervisor_harness import record_supervisor_checkpoint

    state = _state()

    result = record_supervisor_checkpoint(
        state,
        checkpoint="intent_input",
        user_goal_text="Find data analyst jobs",
    )

    assert result == state.supervisor_log[-1]
    assert result["stage"] == "supervisor_checkpoint"
    assert result["checkpoint"] == "intent_input"
    assert result["agent"] == "intent_agent"
    assert result["phase"] == "before"
    assert result["status"] == "passed"
    assert result["issue_codes"] == []
    assert result["metrics"] == {"resume_context_present": True}
    assert "Python data analyst" not in str(result)
    assert "user-1" not in str(result)


def test_matching_input_blocks_non_positive_top_k() -> None:
    from app.agents.supervisor_harness import (
        SupervisorCheckpointError,
        record_supervisor_checkpoint,
    )

    state = _state()

    with pytest.raises(SupervisorCheckpointError) as exc_info:
        record_supervisor_checkpoint(
            state,
            checkpoint="matching_input",
            retrieval_plan={
                "hard_constraints": {"locations": ["Birmingham"]},
                "soft_prefs": {},
                "top_k": 0,
            },
        )

    assert exc_info.value.issue_codes == ["retrieval_top_k_invalid"]
    assert state.supervisor_log[-1]["status"] == "blocked"


def test_matching_input_blocks_locked_hard_constraint_rewrite() -> None:
    from app.agents.supervisor_harness import (
        SupervisorCheckpointError,
        record_supervisor_checkpoint,
    )

    state = _state()

    with pytest.raises(SupervisorCheckpointError) as exc_info:
        record_supervisor_checkpoint(
            state,
            checkpoint="matching_input",
            retrieval_plan={
                "hard_constraints": {"locations": ["London"]},
                "soft_prefs": {},
                "top_k": 5,
            },
            locked_hard_constraints={"locations": ["Birmingham"]},
        )

    assert exc_info.value.issue_codes == ["locked_hard_constraints_changed"]
    assert state.supervisor_log[-1]["status"] == "blocked"


def test_matching_and_strategy_output_report_structural_warnings() -> None:
    from app.agents.supervisor_harness import record_supervisor_checkpoint

    state = _state()
    state.retrieval_state = RetrievalState(
        candidate_job_ids=["job-1", "job-1"],
        ranking_scores=[
            {
                "job_id": "job-1",
                "evidence_span_ids": [],
                "evidence_spans": [],
            }
        ],
    )

    matching = record_supervisor_checkpoint(
        state,
        checkpoint="matching_output",
    )
    assert matching["status"] == "warning"
    assert matching["issue_codes"] == [
        "candidate_ids_duplicated",
        "candidate_evidence_missing",
    ]

    state.strategy_state.recommended_roles = [
        {"job_id": "job-2", "tier": "stretch_fit", "evidence_span_ids": []}
    ]
    strategy = record_supervisor_checkpoint(
        state,
        checkpoint="strategy_output",
    )
    assert strategy["status"] == "warning"
    assert strategy["issue_codes"] == [
        "recommendation_not_retrieved",
        "recommendation_jd_evidence_missing",
    ]


def test_publication_gate_logs_verification_risks_without_extra_llm_call() -> None:
    from app.agents.supervisor_harness import record_supervisor_checkpoint

    state = _state()
    state.retrieval_state.candidate_job_ids = ["job-1"]
    state.strategy_state.recommended_roles = [
        {
            "job_id": "job-1",
            "tier": "now_fit",
            "evidence_span_ids": ["job-1:required_skills:1"],
        }
    ]

    result = record_supervisor_checkpoint(
        state,
        checkpoint="publication_gate",
        verification={
            "hard_filter_violations": [{"job_id": "job-1"}],
            "missing_evidence": [],
            "fabrication_risks": [{"section": "experience"}],
        },
    )

    assert result["status"] == "warning"
    assert result["issue_codes"] == [
        "hard_filter_violation",
        "fabrication_risk",
        "no_publishable_recommendations",
    ]
    assert result["metrics"] == {
        "recommendation_count": 1,
        "publishable_recommendation_count": 0,
    }
