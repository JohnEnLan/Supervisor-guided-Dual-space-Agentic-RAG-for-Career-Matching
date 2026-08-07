from app.agents.trace import build_public_explain
import json

from app.state.schema import RetrievalState, SharedState, StrategyState


def _state() -> SharedState:
    return SharedState(
        session_id="session-1",
        user_id="private-user",
        retrieval_state=RetrievalState(
            ranking_scores=[
                {
                    "job_id": "job-1",
                    "explicit_rank": 2,
                    "implicit_rank": 1,
                    "explicit_score": 0.8,
                    "implicit_score": 0.7,
                    "implicit_confidence": 0.6,
                    "implicit_evidence": [
                        {
                            "case_id": "case-1",
                            "highest_stage": "interview",
                            "confidence": 0.75,
                            "private_resume": "must stay private",
                        }
                    ],
                }
            ]
        ),
        strategy_state=StrategyState(
            recommended_roles=[{"job_id": "job-1", "tier": "now_fit"}]
        ),
        supervisor_log=[
            {
                "stage": "reretrieval_loop",
                "reason": "too_few_results",
                "loop_used": 1,
                "max_loops": 1,
                "prompt": "must stay private",
            },
            {"stage": "final_verification", "duration_ms": 12},
        ],
    )


def test_explain_is_capability_gated() -> None:
    assert build_public_explain(_state(), evaluation_enabled=False) is None


def test_explain_contains_allow_list_trace_without_prompt_or_state() -> None:
    payload = build_public_explain(
        _state(),
        evaluation_enabled=True,
        implicit_max_weight=0.3,
        stage_durations_ms={"retrieval": 45},
    )

    assert payload is not None
    assert payload["rank_trace"][0]["case_ids"] == ["case-1"]
    assert payload["rank_trace"][0]["case_evidence"] == [
        {
            "case_id": "case-1",
            "highest_stage": "interview",
            "confidence": 0.75,
        }
    ]
    assert payload["fusion"]["implicit_max_weight"] == 0.3
    assert payload["stage_durations_ms"] == {"retrieval": 45}
    assert payload["recovery_events"][0] == {
        "stage": "reretrieval_loop",
        "reason": "too_few_results",
        "attempt": 1,
        "max_attempts": 1,
    }
    serialized = str(payload)
    assert "must stay private" not in serialized
    assert "private-user" not in serialized
    assert "normalized_base_resume" not in serialized


def test_explain_never_projects_private_clarification_or_coach_state() -> None:
    state = _state()
    state.resume_state.clarifications = [
        {
            "target_ref": "private-target-ref",
            "raw_answer": "private-clarification-answer",
        }
    ]
    state.resume_state.pending_clarification_question = {
        "target_ref": "private-pending-target",
        "asked_round": 3,
        "baseline_version": 9,
    }
    state.coach_reservations = [
        {
            "coach_attempt_id": "private-coach-attempt",
            "round": 3,
            "trigger": "stagnation",
            "status": "reserved",
        }
    ]

    payload = build_public_explain(state, evaluation_enabled=True)
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    for private_key in (
        "clarifications",
        "pending_clarification_question",
        "coach_reservations",
    ):
        assert private_key not in serialized
    for private_value in (
        "private-target-ref",
        "private-clarification-answer",
        "private-pending-target",
        "private-coach-attempt",
    ):
        assert private_value not in serialized


def test_explain_projects_repair_loop_recovery_event() -> None:
    state = _state()
    state.supervisor_log.append(
        {
            "stage": "repair_loop",
            "trigger": "final_verification",
            "reason": "unsupported_resume_advice",
            "max_loops": 1,
            "loop_used": 1,
            "repaired_resume_advice": 2,
        }
    )

    payload = build_public_explain(state, evaluation_enabled=True)

    assert {
        "stage": "repair_loop",
        "reason": "unsupported_resume_advice",
        "attempt": 1,
        "max_attempts": 1,
    } in payload["recovery_events"]


def test_explain_derives_missing_space_ranks_and_public_durations() -> None:
    state = _state()
    state.retrieval_state.ranking_scores = [
        {"job_id": "job-a", "explicit_score": 0.9, "implicit_score": 0.1},
        {"job_id": "job-b", "explicit_score": 0.8, "implicit_score": 0.7},
    ]
    state.supervisor_log.append(
        {
            "stage": "public_stage_duration",
            "stage_name": "retrieval",
            "duration_ms": 31,
        }
    )

    payload = build_public_explain(state, evaluation_enabled=True)

    assert payload["rank_trace"][0]["explicit_rank"] == 1
    assert payload["rank_trace"][0]["implicit_rank"] == 2
    assert payload["rank_trace"][1]["implicit_rank"] == 1
    assert payload["stage_durations_ms"]["retrieval"] == 31
