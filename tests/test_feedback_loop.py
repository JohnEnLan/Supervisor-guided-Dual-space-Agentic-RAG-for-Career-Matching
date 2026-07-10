import os

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")
os.environ.setdefault("QWEN_API_KEY", "sk-test")


def test_merge_case_soft_preferences_preserves_and_appends_hints():
    from app.memory.case_base import merge_case_soft_preferences

    base_preferences = {
        "preferred_location": "remote",
        "case_target_roles": ["Data Analyst", "Product Analyst"],
    }

    merged = merge_case_soft_preferences(
        base_preferences,
        {
            "case_target_roles": ["Product Analyst", "Business Analyst"],
        },
    )

    assert merged == {
        "preferred_location": "remote",
        "case_target_roles": [
            "Data Analyst",
            "Product Analyst",
            "Business Analyst",
        ],
    }
    assert base_preferences == {
        "preferred_location": "remote",
        "case_target_roles": ["Data Analyst", "Product Analyst"],
    }


def test_case_soft_preferences_restrict_keys_deduplicate_and_cap_values():
    from app.memory.case_base import CASE_PREFERENCE_MAX_ITEMS
    from app.memory.case_base import merge_case_soft_preferences

    merged = merge_case_soft_preferences(
        {"title_keywords": ["analyst"]},
        {
            "case_target_roles": [
                "Data Analyst",
                "Data Analyst",
                *[f"Role {index}" for index in range(20)],
            ],
            "case_bridge_roles": ["Business Analyst", "Business Analyst"],
            "preferred_location": ["private-user-value"],
            "unexpected": ["must-not-persist"],
        },
    )

    assert merged["title_keywords"] == ["analyst"]
    assert merged["case_bridge_roles"] == ["Business Analyst"]
    assert len(merged["case_target_roles"]) == CASE_PREFERENCE_MAX_ITEMS
    assert merged["case_target_roles"][0] == "Data Analyst"
    assert "preferred_location" not in merged
    assert "unexpected" not in merged


def test_similar_case_preferences_are_bounded_before_persistence():
    from app.memory.case_base import CASE_PREFERENCE_MAX_ITEMS
    from app.memory.feedback_loop import build_case_soft_preferences

    cases = [
        {
            "target_role": f"Target {index}",
            "recommended_bridge_roles": [f"Bridge {index}", "Shared Bridge"],
        }
        for index in range(CASE_PREFERENCE_MAX_ITEMS + 5)
    ]

    updates = build_case_soft_preferences(cases)

    assert len(updates["case_target_roles"]) == CASE_PREFERENCE_MAX_ITEMS
    assert len(updates["case_bridge_roles"]) == CASE_PREFERENCE_MAX_ITEMS
    assert updates["case_bridge_roles"].count("Shared Bridge") == 1


def test_anonymous_feedback_case_uses_only_controlled_non_private_content():
    from app.agents.supervisor import assess_feedback_for_case
    from app.agents.supervisor import build_anonymous_case_from_feedback
    from app.state.schema import CareerState, ResumeState, SharedState, StrategyState

    private_fragments = [
        "John Example",
        "john@example.com",
        "Acme Corporation",
        "University of Birmingham",
        "quoted private resume sentence",
    ]
    state = SharedState(
        session_id="john@example.com",
        user_id="John Example",
        resume_state=ResumeState(
            skills=["Python", "SQL", *private_fragments],
            normalized_base_resume=" ".join(private_fragments),
            original_evidence_spans=[
                {"span_id": "R001", "text": "quoted private resume sentence"}
            ],
        ),
        career_state=CareerState(current_goal=private_fragments),
        strategy_state=StrategyState(
            recommended_roles=[
                {
                    "job_id": "job-1",
                    "title": "Data Analyst",
                    "tier": "now_fit",
                    "match_explanation": " ".join(private_fragments),
                },
                {
                    "job_id": "job-2",
                    "title": "Business Analyst Intern",
                    "tier": "bridge_role",
                },
            ],
            skill_gap_analysis=[
                {"skill": "John Example at Acme Corporation"},
                {"skill": "Tableau"},
            ],
        ),
    )
    feedback = {
        "feedback_id": 101,
        "job_id": "job-1",
        "outcome": "offer",
    }
    decision = assess_feedback_for_case(state, feedback)

    case = build_anonymous_case_from_feedback(state, feedback, decision)
    retry_case = build_anonymous_case_from_feedback(
        state,
        {**feedback, "feedback_id": 999},
        {**decision, "feedback_id": 999},
    )

    payload = case.model_dump_json()
    assert case.case_id == retry_case.case_id
    assert case.background_type == "feedback_case_Python_SQL"
    assert case.target_role == "Data Analyst"
    assert case.successful_resume_features == ["evidence_backed_resume"]
    assert case.missing_skills_before == ["Tableau"]
    assert case.recommended_bridge_roles == ["Business Analyst Intern"]
    for fragment in private_fragments:
        assert fragment.casefold() not in payload.casefold()


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


@pytest.mark.asyncio
async def test_feedback_loop_reports_case_written_when_similar_search_fails(
    monkeypatch,
):
    import json

    from app.memory import feedback_loop
    from app.state.schema import SharedState, StrategyState

    async def fake_upsert_case(case, *, embed_if_missing):
        assert embed_if_missing is True

    async def fake_search_similar_cases(query, *, top_k):
        raise RuntimeError("private provider message must not persist")

    monkeypatch.setattr(feedback_loop, "upsert_career_case", fake_upsert_case)
    monkeypatch.setattr(feedback_loop, "search_similar_cases", fake_search_similar_cases)
    state = SharedState(
        session_id="s1",
        user_id="u1",
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

    assert result["closure_status"] == "error"
    assert result["error_code"] == "similar_case_search_failed"
    assert result["case_written"] is True
    assert result["case"]["case_id"].startswith("feedback-")
    assert state.supervisor_log[-1]["case_written"] is True
    assert state.supervisor_log[-1]["error_code"] == "similar_case_search_failed"
    assert "private provider message" not in json.dumps(state.model_dump())


@pytest.mark.asyncio
async def test_process_feedback_closure_for_session_uses_atomic_state_mutation(
    monkeypatch,
):
    from app.memory import feedback_loop
    from app.state.schema import SharedState

    state = SharedState(session_id="s1", user_id="u1")
    state.feedback_state.user_feedback = [
        {"feedback_id": 42, "job_id": "job-1", "outcome": "offer"}
    ]
    mutated = []

    async def fake_load_state(session_id):
        assert session_id == "s1"
        return state

    async def fake_run_feedback_closure(loaded_state, *, feedback):
        assert loaded_state is state
        assert feedback == {"feedback_id": 42, "job_id": "job-1"}
        return {
            "closure_status": "processed",
            "decision": {"is_valuable": True},
            "case_written": True,
            "case": {"case_id": "case-1"},
            "soft_preference_updates": {"case_target_roles": ["Data Analyst"]},
        }

    async def fake_mutate_state_atomically(*, session_id, mutator):
        assert session_id == "s1"
        mutator(state)
        mutated.append(state)

    monkeypatch.setattr(feedback_loop, "load_state", fake_load_state)
    monkeypatch.setattr(feedback_loop, "run_feedback_closure", fake_run_feedback_closure)
    monkeypatch.setattr(
        feedback_loop, "mutate_state_atomically", fake_mutate_state_atomically
    )

    result = await feedback_loop.process_feedback_closure_for_session(
        session_id="s1",
        feedback={"feedback_id": 42, "job_id": "job-1"},
    )

    assert result == {
        "closure_status": "processed",
        "decision": {"is_valuable": True},
        "case_written": True,
        "case": {"case_id": "case-1"},
        "soft_preference_updates": {"case_target_roles": ["Data Analyst"]},
    }
    assert mutated == [state]
    assert state.feedback_state.user_feedback[0] == {
        "feedback_id": 42,
        "job_id": "job-1",
        "outcome": "offer",
        "closure_status": "processed",
        "case_written": True,
        "case_id": "case-1",
    }


@pytest.mark.asyncio
async def test_process_feedback_closure_merges_into_latest_state_atomically(
    monkeypatch,
):
    from app.memory import feedback_loop
    from app.state.schema import SharedState

    stale_state = SharedState(session_id="s1", user_id="u1")
    latest_state = SharedState(session_id="s1", user_id="u1")
    latest_state.career_state.current_goal = ["newer unrelated goal"]
    latest_state.feedback_state.user_feedback = [
        {"feedback_id": 42, "job_id": "job-1", "outcome": "offer"}
    ]
    latest_row = {"state": latest_state, "status": "agentic_done"}

    async def fake_load_state(session_id):
        assert session_id == "s1"
        return stale_state

    async def fake_run_feedback_closure(loaded_state, *, feedback):
        assert loaded_state is stale_state
        return {
            "closure_status": "processed",
            "decision": {"is_valuable": True},
            "case_written": True,
            "case": {"case_id": "case-1"},
            "soft_preference_updates": {"case_target_roles": ["Data Analyst"]},
        }

    async def fake_mutate_state_atomically(*, session_id, mutator):
        assert session_id == "s1"
        assert latest_row["status"] == "agentic_done"
        mutator(latest_row["state"])
        assert latest_row["status"] == "agentic_done"

    monkeypatch.setattr(feedback_loop, "load_state", fake_load_state, raising=False)
    monkeypatch.setattr(feedback_loop, "run_feedback_closure", fake_run_feedback_closure)
    monkeypatch.setattr(
        feedback_loop,
        "mutate_state_atomically",
        fake_mutate_state_atomically,
        raising=False,
    )

    result = await feedback_loop.process_feedback_closure_for_session(
        session_id="s1",
        feedback={"feedback_id": 42, "job_id": "job-1"},
    )

    assert result["case_written"] is True
    assert latest_row["state"].career_state.current_goal == ["newer unrelated goal"]
    assert latest_row["state"].feedback_state.case_soft_preferences == {
        "case_target_roles": ["Data Analyst"]
    }
    assert latest_row["state"].supervisor_log[-1] == {
        "stage": "feedback_closure",
        "feedback_id": 42,
        "job_id": "job-1",
        "decision": {"is_valuable": True},
        "case_written": True,
        "case_id": "case-1",
        "soft_preference_updates": {"case_target_roles": ["Data Analyst"]},
        "closure_status": "processed",
    }
    assert latest_row["state"].feedback_state.user_feedback[0]["case_id"] == "case-1"
    assert latest_row["status"] == "agentic_done"


@pytest.mark.asyncio
async def test_process_feedback_closure_preserves_case_truth_when_persistence_fails(
    monkeypatch,
):
    import json

    from app.memory import feedback_loop
    from app.state.schema import SharedState

    state = SharedState(session_id="s1", user_id="u1")
    state.feedback_state.user_feedback = [
        {"feedback_id": 42, "job_id": "job-1", "outcome": "offer"}
    ]
    mutation_attempts = 0

    async def fake_load_state(session_id):
        return state

    async def fake_run_feedback_closure(loaded_state, *, feedback):
        return {
            "closure_status": "processed",
            "decision": {"is_valuable": True},
            "case_written": True,
            "case": {"case_id": "case-42"},
            "similar_cases": [],
            "soft_preference_updates": {
                "case_target_roles": ["Data Analyst"]
            },
        }

    async def fake_mutate_state_atomically(*, session_id, mutator):
        nonlocal mutation_attempts
        mutation_attempts += 1
        if mutation_attempts == 1:
            raise RuntimeError("private database failure")
        mutator(state)

    monkeypatch.setattr(feedback_loop, "load_state", fake_load_state)
    monkeypatch.setattr(feedback_loop, "run_feedback_closure", fake_run_feedback_closure)
    monkeypatch.setattr(
        feedback_loop,
        "mutate_state_atomically",
        fake_mutate_state_atomically,
    )

    result = await feedback_loop.process_feedback_closure_for_session(
        session_id="s1",
        feedback={"feedback_id": 42, "job_id": "job-1", "outcome": "offer"},
    )

    assert mutation_attempts == 2
    assert result["closure_status"] == "error"
    assert result["error_code"] == "closure_persistence_failed"
    assert result["case_written"] is True
    assert result["case"] == {"case_id": "case-42"}
    assert state.feedback_state.user_feedback[0]["closure_status"] == "error"
    assert state.feedback_state.user_feedback[0]["case_written"] is True
    assert state.feedback_state.user_feedback[0]["case_id"] == "case-42"
    assert state.feedback_state.user_feedback[0]["error_code"] == (
        "closure_persistence_failed"
    )
    assert "private database failure" not in json.dumps(state.model_dump())


@pytest.mark.asyncio
async def test_atomic_closure_normalizes_existing_case_preferences(monkeypatch):
    from app.memory import feedback_loop
    from app.memory.case_base import CASE_PREFERENCE_MAX_ITEMS
    from app.state.schema import SharedState

    state = SharedState(session_id="s1", user_id="u1")
    state.feedback_state.user_feedback = [
        {"feedback_id": 42, "job_id": "job-1", "outcome": "offer"}
    ]
    state.feedback_state.case_soft_preferences = {
        "legacy_private_key": ["must disappear"],
        "case_target_roles": [
            " Data Analyst ",
            "Data Analyst",
            *[f"Role {index}" for index in range(20)],
        ],
    }

    async def fake_load_state(session_id):
        return state.model_copy(deep=True)

    async def fake_run_feedback_closure(loaded_state, *, feedback):
        return {
            "closure_status": "processed",
            "decision": {"is_valuable": True},
            "case_written": True,
            "case": {"case_id": "case-42"},
            "similar_cases": [],
            "soft_preference_updates": {
                "case_bridge_roles": ["Business Analyst"]
            },
        }

    async def fake_mutate_state_atomically(*, session_id, mutator):
        mutator(state)

    monkeypatch.setattr(feedback_loop, "load_state", fake_load_state)
    monkeypatch.setattr(feedback_loop, "run_feedback_closure", fake_run_feedback_closure)
    monkeypatch.setattr(
        feedback_loop,
        "mutate_state_atomically",
        fake_mutate_state_atomically,
    )

    await feedback_loop.process_feedback_closure_for_session(
        session_id="s1",
        feedback={"feedback_id": 42, "job_id": "job-1", "outcome": "offer"},
    )

    preferences = state.feedback_state.case_soft_preferences
    assert set(preferences) == {"case_target_roles", "case_bridge_roles"}
    assert preferences["case_target_roles"][0] == "Data Analyst"
    assert len(preferences["case_target_roles"]) == CASE_PREFERENCE_MAX_ITEMS
    assert preferences["case_bridge_roles"] == ["Business Analyst"]


@pytest.mark.asyncio
async def test_process_feedback_closure_does_not_rerun_completed_entry(monkeypatch):
    from app.memory import feedback_loop
    from app.state.schema import SharedState

    state = SharedState(session_id="s1", user_id="u1")
    state.feedback_state.user_feedback = [
        {
            "feedback_id": 42,
            "job_id": "job-1",
            "outcome": "offer",
            "closure_status": "processed",
            "case_written": True,
            "case_id": "case-42",
        }
    ]

    async def fake_load_state(session_id):
        return state

    async def fail_run_feedback_closure(*args, **kwargs):
        raise AssertionError("completed closure must not run again")

    async def fail_mutate_state_atomically(**kwargs):
        raise AssertionError("completed closure metadata must not be rewritten")

    monkeypatch.setattr(feedback_loop, "load_state", fake_load_state)
    monkeypatch.setattr(
        feedback_loop,
        "run_feedback_closure",
        fail_run_feedback_closure,
    )
    monkeypatch.setattr(
        feedback_loop,
        "mutate_state_atomically",
        fail_mutate_state_atomically,
    )

    result = await feedback_loop.process_feedback_closure_for_session(
        session_id="s1",
        feedback={"feedback_id": 42, "job_id": "job-1", "outcome": "offer"},
    )

    assert result["closure_status"] == "processed"
    assert result["case_written"] is True
    assert result["case"] == {"case_id": "case-42"}


@pytest.mark.asyncio
async def test_retry_preserves_prior_durable_case_when_local_upsert_fails(monkeypatch):
    from app.memory import feedback_loop
    from app.state.schema import SharedState

    loaded_state = SharedState(session_id="s1", user_id="u1")
    loaded_state.feedback_state.user_feedback = [
        {
            "feedback_id": 51,
            "job_id": "job-1",
            "outcome": "offer",
            "closure_status": "error",
            "case_written": True,
            "case_id": "case-durable-51",
            "error_code": "similar_case_search_failed",
        }
    ]
    latest_state = loaded_state.model_copy(deep=True)

    async def fake_load_state(session_id):
        return loaded_state

    async def fake_run_feedback_closure(state, *, feedback):
        return {
            "closure_status": "error",
            "error_code": "case_upsert_failed",
            "decision": {"is_valuable": True},
            "case_written": False,
            "case": {"case_id": "case-local-51"},
            "similar_cases": [],
            "soft_preference_updates": {},
        }

    async def fake_mutate_state_atomically(*, session_id, mutator):
        return mutator(latest_state)

    monkeypatch.setattr(feedback_loop, "load_state", fake_load_state)
    monkeypatch.setattr(feedback_loop, "run_feedback_closure", fake_run_feedback_closure)
    monkeypatch.setattr(
        feedback_loop,
        "mutate_state_atomically",
        fake_mutate_state_atomically,
    )

    result = await feedback_loop.process_feedback_closure_for_session(
        session_id="s1",
        feedback={"feedback_id": 51, "job_id": "job-1", "outcome": "offer"},
    )

    persisted = latest_state.feedback_state.user_feedback[0]
    log_entry = latest_state.supervisor_log[-1]
    assert result["closure_status"] == "error"
    assert result["error_code"] == "case_upsert_failed"
    assert result["case_written"] is True
    assert result["case"]["case_id"] == "case-durable-51"
    assert persisted["case_written"] is True
    assert persisted["case_id"] == "case-durable-51"
    assert log_entry["case_written"] is True
    assert log_entry["case_id"] == "case-durable-51"


@pytest.mark.asyncio
async def test_atomic_terminal_observation_returns_canonical_persisted_result(
    monkeypatch,
):
    from app.memory import feedback_loop
    from app.state.schema import SharedState

    stale_state = SharedState(session_id="s1", user_id="u1")
    stale_state.feedback_state.user_feedback = [
        {
            "feedback_id": 52,
            "job_id": "job-1",
            "outcome": "offer",
            "closure_status": "error",
            "case_written": False,
            "case_id": None,
        }
    ]
    latest_state = stale_state.model_copy(deep=True)
    latest_state.feedback_state.user_feedback[0].update(
        {
            "closure_status": "processed",
            "case_written": True,
            "case_id": "case-canonical-52",
        }
    )

    async def fake_load_state(session_id):
        return stale_state

    async def fake_run_feedback_closure(state, *, feedback):
        return {
            "closure_status": "error",
            "error_code": "case_upsert_failed",
            "decision": {"is_valuable": True},
            "case_written": False,
            "case": None,
            "similar_cases": [],
            "soft_preference_updates": {},
        }

    async def fake_mutate_state_atomically(*, session_id, mutator):
        return mutator(latest_state)

    monkeypatch.setattr(feedback_loop, "load_state", fake_load_state)
    monkeypatch.setattr(feedback_loop, "run_feedback_closure", fake_run_feedback_closure)
    monkeypatch.setattr(
        feedback_loop,
        "mutate_state_atomically",
        fake_mutate_state_atomically,
    )

    result = await feedback_loop.process_feedback_closure_for_session(
        session_id="s1",
        feedback={"feedback_id": 52, "job_id": "job-1", "outcome": "offer"},
    )

    assert result["closure_status"] == "processed"
    assert result["case_written"] is True
    assert result["case"] == {"case_id": "case-canonical-52"}
    assert latest_state.supervisor_log == []


@pytest.mark.asyncio
async def test_ambiguous_persistence_retry_returns_concurrent_terminal_result(
    monkeypatch,
):
    import json

    from app.memory import feedback_loop
    from app.state.schema import SharedState

    state = SharedState(session_id="s1", user_id="u1")
    state.feedback_state.user_feedback = [
        {"feedback_id": 53, "job_id": "job-1", "outcome": "offer"}
    ]
    mutation_attempts = 0

    async def fake_load_state(session_id):
        return state.model_copy(deep=True)

    async def fake_run_feedback_closure(loaded_state, *, feedback):
        return {
            "closure_status": "error",
            "error_code": "case_upsert_failed",
            "decision": {"is_valuable": True},
            "case_written": False,
            "case": None,
            "similar_cases": [],
            "soft_preference_updates": {},
        }

    async def fake_mutate_state_atomically(*, session_id, mutator):
        nonlocal mutation_attempts
        mutation_attempts += 1
        if mutation_attempts == 1:
            # The first transaction outcome is unknown; another request commits
            # terminal state before this caller's bounded persistence retry.
            state.feedback_state.user_feedback[0].update(
                {
                    "closure_status": "processed",
                    "case_written": True,
                    "case_id": "case-concurrent-53",
                }
            )
            raise RuntimeError("private ambiguous commit failure")
        return mutator(state)

    monkeypatch.setattr(feedback_loop, "load_state", fake_load_state)
    monkeypatch.setattr(feedback_loop, "run_feedback_closure", fake_run_feedback_closure)
    monkeypatch.setattr(
        feedback_loop,
        "mutate_state_atomically",
        fake_mutate_state_atomically,
    )

    result = await feedback_loop.process_feedback_closure_for_session(
        session_id="s1",
        feedback={"feedback_id": 53, "job_id": "job-1", "outcome": "offer"},
    )

    assert mutation_attempts == 2
    assert result["closure_status"] == "processed"
    assert result["case_written"] is True
    assert result["case"] == {"case_id": "case-concurrent-53"}
    assert "private ambiguous commit failure" not in json.dumps(result)
