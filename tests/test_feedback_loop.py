import os

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")
os.environ.setdefault("QWEN_API_KEY", "sk-test")


@pytest.mark.asyncio
async def test_feedback_loop_writes_anonymous_case_and_returns_case_weight_hints(
    monkeypatch,
):
    from app.memory import feedback_loop
    from app.state.schema import ResumeState, SharedState, StrategyState

    upserted_cases = []

    async def fake_upsert_case(case, *, embed_if_missing):
        case.validate_anonymous()
        upserted_cases.append((case, embed_if_missing))

    async def fake_search_similar_cases(query, *, top_k):
        assert "Python dashboard" in query
        return [
            {
                "case_id": "case-existing",
                "target_role": "Data Analyst",
                "recommended_bridge_roles": ["Business Analyst Intern"],
                "score": 0.91,
            }
        ]

    monkeypatch.setattr(feedback_loop, "upsert_career_case", fake_upsert_case)
    monkeypatch.setattr(feedback_loop, "search_similar_cases", fake_search_similar_cases)

    state = SharedState(
        session_id="s1",
        user_id="u1",
        resume_state=ResumeState(
            normalized_base_resume="John Example used Python dashboard work.",
            skills=["Python", "SQL"],
            original_evidence_spans=[
                {
                    "span_id": "R001",
                    "text": "Built a Python dashboard for a university project.",
                }
            ],
        ),
        strategy_state=StrategyState(
            recommended_roles=[
                {
                    "job_id": "job-1",
                    "title": "Data Analyst",
                    "tier": "now_fit",
                    "match_explanation": "Python dashboard evidence matches.",
                    "evidence_span_ids": ["job-1:skills:1"],
                }
            ],
            skill_gap_analysis=[
                {
                    "skill": "advanced SQL",
                    "priority": "high",
                    "evidence_span_ids": ["job-1:skills:1"],
                }
            ],
        ),
    )

    result = await feedback_loop.run_feedback_closure(
        state,
        feedback={
            "feedback_id": 7,
            "job_id": "job-1",
            "outcome": "Offer",
            "reason": "strong project evidence",
        },
        similar_case_query="Python dashboard analyst background",
    )

    assert result["case_written"] is True
    assert len(upserted_cases) == 1
    case, embed_if_missing = upserted_cases[0]
    assert embed_if_missing is True
    assert case.case_id.startswith("feedback-")
    assert case.target_role == "Data Analyst"
    assert case.application_outcome == "offer"
    assert "Python" in case.background_type
    assert "john" not in case.model_dump_json().lower()
    assert "raw_resume" not in case.model_dump()
    assert result["soft_preference_updates"] == {
        "case_target_roles": ["Data Analyst"],
        "case_bridge_roles": ["Business Analyst Intern"],
    }
    assert state.feedback_state.case_soft_preferences == {
        "case_target_roles": ["Data Analyst"],
        "case_bridge_roles": ["Business Analyst Intern"],
    }
    assert state.supervisor_log[-1]["stage"] == "feedback_closure"
    assert state.supervisor_log[-1]["case_written"] is True


@pytest.mark.asyncio
async def test_feedback_loop_hashes_identifying_session_id_before_case_write(
    monkeypatch,
):
    from app.memory import feedback_loop
    from app.state.schema import ResumeState, SharedState, StrategyState

    upserted_cases = []

    async def fake_upsert_case(case, *, embed_if_missing):
        case.validate_anonymous()
        upserted_cases.append(case)

    async def fake_search_similar_cases(query, *, top_k):
        return []

    monkeypatch.setattr(feedback_loop, "upsert_career_case", fake_upsert_case)
    monkeypatch.setattr(feedback_loop, "search_similar_cases", fake_search_similar_cases)

    state = SharedState(
        session_id="john@example.com",
        user_id="u1",
        resume_state=ResumeState(
            original_evidence_spans=[{"span_id": "R001", "text": "Built dashboard."}]
        ),
        strategy_state=StrategyState(
            recommended_roles=[
                {"job_id": "job-1", "title": "Data Analyst", "tier": "now_fit"}
            ]
        ),
    )

    result = await feedback_loop.run_feedback_closure(
        state,
        feedback={"feedback_id": 9, "job_id": "job-1", "outcome": "offer"},
    )

    assert result["case_written"] is True
    assert "john@example.com" not in upserted_cases[0].case_id


@pytest.mark.asyncio
async def test_feedback_loop_skips_rejected_feedback(monkeypatch):
    from app.memory import feedback_loop
    from app.state.schema import SharedState

    async def fail_upsert_case(*args, **kwargs):
        raise AssertionError("rejected feedback should not become a case")

    monkeypatch.setattr(feedback_loop, "upsert_career_case", fail_upsert_case)

    state = SharedState(session_id="s1", user_id="u1")

    result = await feedback_loop.run_feedback_closure(
        state,
        feedback={
            "feedback_id": 8,
            "job_id": "job-1",
            "outcome": "rejected",
            "reason": "not enough experience",
        },
    )

    assert result["case_written"] is False
    assert result["decision"]["is_valuable"] is False
    assert state.supervisor_log[-1]["stage"] == "feedback_closure"
    assert state.supervisor_log[-1]["case_written"] is False
