from __future__ import annotations

import json

import pytest


@pytest.mark.asyncio
async def test_supervisor_plan_resolves_cross_switch_once_and_audits_it(
    monkeypatch,
) -> None:
    from app.agents import supervisor
    from app.state.schema import SharedState

    async def fake_chat(*_args, **_kwargs):
        return json.dumps(
            {
                "needs_clarification": False,
                "retrieval_plan": {
                    "hard_constraints": {},
                    "soft_preferences": {},
                    "top_k": 5,
                    "use_cross_encoder": False,
                },
            }
        )

    monkeypatch.setattr(supervisor.deepseek, "chat", fake_chat)
    monkeypatch.setattr(supervisor.settings, "rerank_enabled", True)
    state = SharedState(session_id="s-cross-plan", user_id="u-cross-plan")

    plan = await supervisor.plan_retrieval(
        state,
        user_goal_text="Find data analyst roles",
        default_top_k=5,
        include_raptor=False,
    )
    monkeypatch.setattr(supervisor.settings, "rerank_enabled", False)

    assert plan["use_cross_encoder"] is True
    assert state.supervisor_log[-1]["retrieval_plan"]["use_cross_encoder"] is True


def test_public_plan_whitelist_and_reretrieval_copy_preserve_cross_switch() -> None:
    from app.agents import orchestrator

    original = {
        "hard_constraints": {"locations": ["London"]},
        "soft_prefs": {"title_keywords": ["analyst"]},
        "top_k": 5,
        "include_raptor": False,
        "use_cross_encoder": True,
        "private_internal": "must not leak",
    }

    public = orchestrator._public_retrieval_plan(original)
    reretrieval, audit = orchestrator._build_reretrieval_plan(
        original,
        {"too_few_results": {"actual_count": 1}},
    )

    assert public == {
        "hard_constraints": {"locations": ["London"]},
        "soft_prefs": {"title_keywords": ["analyst"]},
        "top_k": 5,
        "include_raptor": False,
        "use_cross_encoder": True,
    }
    assert reretrieval["use_cross_encoder"] is True
    assert audit["reretrieval_plan"]["use_cross_encoder"] is True
    assert "private_internal" not in audit["reretrieval_plan"]


@pytest.mark.asyncio
async def test_approved_brief_locks_cross_switch_into_saved_plan(monkeypatch) -> None:
    from app.agents import orchestrator
    from app.domain.match_brief import create_match_brief
    from app.state.schema import SharedState

    saved = []

    async def save_snapshot(*, run_id, state_snapshot):
        saved.append((run_id, state_snapshot))

    brief = create_match_brief(
        career_goal="Find graduate data analyst roles",
        hard_constraints={"locations": ["London"]},
        soft_preferences={"title_keywords": ["analyst"]},
        avoid_roles=[],
        result_count=5,
        plan_version=1,
    )
    monkeypatch.setattr(orchestrator.settings, "rerank_enabled", True, raising=False)
    monkeypatch.setattr(orchestrator, "save_state_snapshot", save_snapshot)
    state = SharedState(session_id="s-lock", user_id="u-lock")

    state, plan = await orchestrator._lock_approved_brief(
        state,
        brief,
        run_id="run-lock",
    )
    monkeypatch.setattr(orchestrator.settings, "rerank_enabled", False)

    assert plan["use_cross_encoder"] is True
    assert state.supervisor_log[-1]["retrieval_plan"]["use_cross_encoder"] is True
    assert saved[0][0] == "run-lock"


@pytest.mark.asyncio
async def test_matching_reads_cross_switch_only_from_plan(monkeypatch) -> None:
    from app.agents import base, matching_agent
    from app.state.schema import ResumeState, SharedState

    received = []

    async def fake_chat(*_args, **_kwargs):
        return json.dumps({"recommended_roles": []})

    async def fake_search(**kwargs):
        received.append(kwargs)
        return []

    monkeypatch.setattr(base.deepseek, "chat", fake_chat)
    monkeypatch.setattr(matching_agent.settings, "rerank_enabled", True)
    state = SharedState(
        session_id="s-match-plan",
        user_id="u-match-plan",
        resume_state=ResumeState(normalized_base_resume="Python SQL analyst"),
    )

    await matching_agent.run_matching_agent(
        state,
        retrieval_plan={"top_k": 5, "use_cross_encoder": False},
        search_fn=fake_search,
    )
    await matching_agent.run_matching_agent(
        state,
        retrieval_plan={"top_k": 5},
        search_fn=fake_search,
    )

    assert [call["use_cross_encoder"] for call in received] == [False, False]


@pytest.mark.asyncio
async def test_dual_space_forwards_cross_switch_to_explicit_search() -> None:
    from app.retrieval.dual_space_search import dual_space_search

    received = {}

    async def explicit_search(**kwargs):
        received.update(kwargs)
        return []

    await dual_space_search(
        query="data analyst",
        anonymized_resume_text="SQL internship",
        hard_constraints={},
        soft_prefs={},
        top_k=5,
        implicit_enabled=False,
        include_raptor=False,
        use_cross_encoder=True,
        explicit_search=explicit_search,
    )

    assert received["use_cross_encoder"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("checkpoint_plan", "expected"),
    [
        ({"top_k": 5, "include_raptor": False}, False),
        ({"top_k": 5, "include_raptor": False, "use_cross_encoder": True}, True),
    ],
)
async def test_retrieve_node_migrates_old_checkpoint_and_returns_persistable_plan(
    monkeypatch,
    checkpoint_plan,
    expected,
) -> None:
    from app.agents import orchestrator
    from app.domain.match_brief import create_match_brief
    from app.graph import nodes
    from app.state.schema import SharedState

    captured = {}

    async def matching(shared, *, retrieval_plan, **_kwargs):
        captured.update(retrieval_plan)
        return shared

    monkeypatch.setattr(orchestrator, "run_matching_under_supervision", matching)
    brief = create_match_brief(
        career_goal="Find graduate data analyst roles",
        hard_constraints={},
        soft_preferences={},
        avoid_roles=[],
        result_count=5,
        plan_version=1,
    )
    graph_state = {
        "shared": SharedState(session_id="s-old", user_id="u-old"),
        "brief": brief,
        "retrieval_plan": checkpoint_plan,
        "verification": {},
        "product_result": None,
        "attempt": 2,
        "loops": {"reretrieval": 0, "repair": 0},
        "run_id": "run-old",
        "stage_timing": {},
    }

    update = await nodes.retrieve_match(graph_state)

    assert captured["use_cross_encoder"] is expected
    assert update["retrieval_plan"]["use_cross_encoder"] is expected


def test_ranking_scores_store_private_cross_fields_without_public_dto_change() -> None:
    from app.agents.matching_agent import _write_retrieval_state
    from app.retrieval.hybrid_search import JobCandidate
    from app.state.schema import SharedState

    candidate = JobCandidate(
        job_id="job-cross",
        score=0.9,
        explicit_score=0.9,
        cross_score=0.77,
        cross_rank=2,
        evidence_span_ids=[],
    )
    state = SharedState(session_id="s-cross-fields", user_id="u-cross-fields")

    _write_retrieval_state(state, [candidate])

    stored = state.retrieval_state.ranking_scores[0]
    assert stored["cross_score"] == 0.77
    assert stored["cross_rank"] == 2
