from app.api.result_projector import project_product_result
from app.state.schema import RetrievalState, SharedState, StrategyState


def _state() -> SharedState:
    return SharedState(
        session_id="session-1",
        user_id="private-user",
        retrieval_state=RetrievalState(
            candidate_job_ids=["job-good", "job-no-evidence", "job-hard-fail"],
            ranking_scores=[
                {
                    "job_id": "job-good",
                    "score": 0.91,
                    "evidence_spans": [
                        {
                            "evidence_span_id": "job-good:skills:1",
                            "field": "skills",
                            "content": "Python and SQL",
                        }
                    ],
                }
            ],
        ),
        strategy_state=StrategyState(
            recommended_roles=[
                {
                    "job_id": "job-good",
                    "tier": "now_fit",
                    "title": "Data Analyst",
                    "company": "Example Ltd",
                    "location": "Birmingham",
                    "match_explanation": "The JD requires Python and SQL.",
                    "explicit_explanation": "The JD requires Python and SQL.",
                    "evidence_span_ids": ["job-good:skills:1"],
                    "evidence_spans": [
                        {
                            "evidence_span_id": "job-good:skills:1",
                            "field": "skills",
                            "content": "Python and SQL",
                        }
                    ],
                    "hard_constraint_passed": True,
                },
                {
                    "job_id": "job-no-evidence",
                    "tier": "stretch_fit",
                    "match_explanation": "Unsupported claim",
                    "evidence_span_ids": [],
                },
                {
                    "job_id": "job-hard-fail",
                    "tier": "bridge_role",
                    "match_explanation": "Wrong location",
                    "evidence_span_ids": ["job-hard-fail:skills:1"],
                    "evidence_spans": [
                        {
                            "evidence_span_id": "job-hard-fail:skills:1",
                            "content": "Python",
                        }
                    ],
                    "hard_constraint_passed": False,
                },
            ],
            resume_revision_plan=[
                {
                    "section": "Projects",
                    "suggestion": "Lead with the SQL project.",
                    "evidence_span_ids": ["R001"],
                }
            ],
            skill_gap_analysis=[
                {
                    "skill": "Tableau",
                    "gap": "Not shown in the resume.",
                    "priority": "medium",
                    "evidence_span_ids": ["job-good:skills:1"],
                }
            ],
            career_path=[
                {
                    "horizon": "short",
                    "action": "Apply to evidence-backed analyst roles.",
                    "evidence_span_ids": ["job-good:skills:1"],
                }
            ],
        ),
    )


def test_projector_returns_one_canonical_product_shape_and_filters_unsafe_roles() -> None:
    result = project_product_result(_state())

    assert [role.job_id for role in result.recommended_roles] == ["job-good"]
    assert result.recommended_roles[0].evidence[0].content == "Python and SQL"
    assert result.resume_strategy[0].section == "Projects"
    assert result.skill_gaps[0].skill == "Tableau"
    assert result.career_path[0].horizon == "short"
    assert "recommendation_missing_jd_evidence:job-no-evidence" in result.warnings
    assert "hard_constraint_failed:job-hard-fail" in result.warnings


def test_projector_never_exposes_shared_state_or_private_user_id() -> None:
    payload = project_product_result(_state()).model_dump(mode="json")
    serialized = str(payload)

    assert "private-user" not in serialized
    assert "supervisor_log" not in payload
    assert "retrieval_state" not in payload


def test_projector_honors_supervisor_hard_filter_violations() -> None:
    state = _state()
    state.strategy_state.recommended_roles[0].pop("hard_constraint_passed")
    state.supervisor_log.append(
        {
            "stage": "final_verification",
            "hard_filter_violations": [
                {"job_id": "job-good", "field": "location"}
            ],
        }
    )

    result = project_product_result(state)

    assert "job-good" not in [role.job_id for role in result.recommended_roles]
    assert "hard_constraint_failed:job-good" in result.warnings


def test_projector_warns_when_no_recommendation_is_publishable() -> None:
    state = SharedState(session_id="session-empty", user_id="private-user")

    result = project_product_result(state)

    assert result.recommended_roles == []
    assert result.warnings == ["no_publishable_recommendations"]
