import asyncio
import json
import os
import time

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")
os.environ.setdefault("QWEN_API_KEY", "sk-test")


@pytest.mark.asyncio
async def test_intent_agent_writes_hard_constraints_and_soft_preferences(monkeypatch):
    from app.agents import base
    from app.agents.intent_agent import run_intent_agent
    from app.state.schema import ResumeState, SharedState

    async def fake_chat(system, user, **kwargs):
        assert "PHASE_C_INTENT_AGENT" in system
        assert "Birmingham" in user
        return json.dumps(
            {
                "current_goal": ["data analyst internship"],
                "long_term_goal": ["product analytics"],
                "hard_constraints": {
                    "locations": ["Birmingham"],
                    "need_visa_sponsor": True,
                    "max_years_exp": 2,
                },
                "soft_preferences": {
                    "title_keywords": ["analyst"],
                    "preferred_role_clusters": ["data"],
                },
                "avoid_roles": ["door to door sales"],
            }
        )

    monkeypatch.setattr(base.deepseek, "chat", fake_chat)
    state = SharedState(
        session_id="s1",
        user_id="u1",
        resume_state=ResumeState(normalized_base_resume="Python SQL analyst resume"),
    )

    updated = await run_intent_agent(
        state,
        "I want data analyst internships in Birmingham and need visa sponsorship.",
    )

    assert updated.career_state.current_goal == ["data analyst internship"]
    assert updated.career_state.hard_constraints == {
        "locations": ["Birmingham"],
        "need_visa_sponsor": True,
        "max_years_exp": 2,
    }
    assert updated.career_state.soft_preferences["title_keywords"] == ["analyst"]
    assert updated.career_state.avoid_roles == ["door to door sales"]


@pytest.mark.asyncio
async def test_intent_agent_does_not_overinfer_long_term_goal(monkeypatch):
    from app.agents import base
    from app.agents.intent_agent import run_intent_agent
    from app.state.schema import ResumeState, SharedState

    async def fake_chat(system, user, **kwargs):
        assert "PHASE_C_INTENT_AGENT" in system
        return json.dumps(
            {
                "current_goal": ["data analyst internship"],
                "long_term_goal": ["head of product analytics"],
                "hard_constraints": {
                    "locations": ["Birmingham"],
                    "unsupported_filter": "must be dropped",
                },
                "soft_preferences": {
                    "preferred_locations": "Birmingham",
                    "title_keywords": "analyst",
                    "unsupported_preference": "must be dropped",
                },
                "avoid_roles": "door to door sales",
            }
        )

    monkeypatch.setattr(base.deepseek, "chat", fake_chat)
    state = SharedState(
        session_id="s1",
        user_id="u1",
        resume_state=ResumeState(normalized_base_resume="Python SQL analyst resume"),
    )

    updated = await run_intent_agent(
        state,
        "Find data analyst internships in Birmingham.",
    )

    assert updated.career_state.current_goal == ["data analyst internship"]
    assert updated.career_state.long_term_goal == []
    assert updated.career_state.hard_constraints == {"locations": ["Birmingham"]}
    assert updated.career_state.soft_preferences == {
        "preferred_locations": ["Birmingham"],
        "title_keywords": ["analyst"],
    }
    assert updated.career_state.avoid_roles == ["door to door sales"]


@pytest.mark.asyncio
async def test_intent_agent_keeps_explicit_long_term_goal(monkeypatch):
    from app.agents import base
    from app.agents.intent_agent import run_intent_agent
    from app.state.schema import ResumeState, SharedState

    async def fake_chat(system, user, **kwargs):
        assert "long-term" in user.casefold()
        return json.dumps(
            {
                "current_goal": ["data analyst internship"],
                "long_term_goal": ["product analytics"],
                "hard_constraints": {},
                "soft_preferences": {},
                "avoid_roles": [],
            }
        )

    monkeypatch.setattr(base.deepseek, "chat", fake_chat)
    state = SharedState(
        session_id="s1",
        user_id="u1",
        resume_state=ResumeState(normalized_base_resume="Python SQL analyst resume"),
    )

    updated = await run_intent_agent(
        state,
        "Find data analyst internships. Long-term I want product analytics.",
    )

    assert updated.career_state.long_term_goal == ["product analytics"]


@pytest.mark.asyncio
async def test_supervisor_planning_records_one_clarification_loop(monkeypatch):
    from app.agents import supervisor
    from app.state.schema import CareerState, SharedState

    async def fake_chat(system, user, **kwargs):
        assert "PHASE_C_SUPERVISOR_PLANNING" in system
        return json.dumps(
            {
                "needs_clarification": True,
                "clarification_question": "Which location do you prefer?",
                "retrieval_plan": {
                    "hard_constraints": {"locations": ["London"]},
                    "soft_preferences": {"title_keywords": ["analyst"]},
                    "top_k": 4,
                    "include_raptor": True,
                },
            }
        )

    monkeypatch.setattr(supervisor.deepseek, "chat", fake_chat)
    state = SharedState(
        session_id="s1",
        user_id="u1",
        career_state=CareerState(
            hard_constraints={"locations": ["Birmingham"]},
            soft_preferences={"title_keywords": ["data"]},
        ),
    )

    plan = await supervisor.plan_retrieval(
        state,
        user_goal_text="something good",
        default_top_k=5,
        include_raptor=False,
    )

    assert plan["needs_clarification"] is True
    assert plan["clarification_loop_used"] == 1
    assert plan["hard_constraints"] == {"locations": ["Birmingham"]}
    assert plan["soft_prefs"] == {"title_keywords": ["data"]}
    assert plan["top_k"] == 4
    assert plan["include_raptor"] is True
    assert state.supervisor_log[-1]["stage"] == "planning"


@pytest.mark.asyncio
async def test_supervisor_planning_merges_learned_case_preferences(monkeypatch):
    from app.agents import supervisor
    from app.state.schema import CareerState, FeedbackState, SharedState

    async def fake_chat(system, user, **kwargs):
        assert "PHASE_C_SUPERVISOR_PLANNING" in system
        return json.dumps(
            {
                "needs_clarification": False,
                "retrieval_plan": {
                    "hard_constraints": {},
                    "soft_preferences": {},
                    "top_k": 5,
                    "include_raptor": False,
                },
            }
        )

    monkeypatch.setattr(supervisor.deepseek, "chat", fake_chat)
    state = SharedState(
        session_id="s1",
        user_id="u1",
        career_state=CareerState(soft_preferences={"title_keywords": ["analyst"]}),
        feedback_state=FeedbackState(
            case_soft_preferences={
                "case_target_roles": ["Data Analyst"],
                "case_bridge_roles": ["Business Analyst Intern"],
            }
        ),
    )

    plan = await supervisor.plan_retrieval(
        state,
        user_goal_text="Find data analyst jobs",
        default_top_k=5,
        include_raptor=False,
    )

    assert plan["soft_prefs"] == {
        "title_keywords": ["analyst"],
        "case_target_roles": ["Data Analyst"],
        "case_bridge_roles": ["Business Analyst Intern"],
    }
    assert state.career_state.soft_preferences == {"title_keywords": ["analyst"]}


@pytest.mark.asyncio
async def test_matching_agent_writes_retrieval_state_and_recommended_roles(monkeypatch):
    from app.agents import base
    from app.agents.matching_agent import run_matching_agent
    from app.retrieval.hybrid_search import JobCandidate
    from app.state.schema import CareerState, ResumeState, SharedState

    async def fake_chat(system, user, **kwargs):
        assert "PHASE_C_MATCHING_AGENT" in system
        assert "job-1" in user
        return json.dumps(
            {
                "recommended_roles": [
                    {
                        "job_id": "job-1",
                        "tier": "now_fit",
                        "match_explanation": "Strong Python and SQL match.",
                        "evidence_span_ids": ["job-1:required_skills:1"],
                    }
                ]
            }
        )

    async def fake_search(**kwargs):
        assert kwargs["hard_constraints"] == {"locations": ["Birmingham"]}
        return [
            JobCandidate(
                job_id="job-1",
                score=0.9,
                title="Data Analyst",
                company="Example",
                location="Birmingham",
                evidence_span_ids=["job-1:required_skills:1"],
                bm25_score=0.4,
                dense_score=0.8,
                sources=["bm25", "dense"],
            )
        ]

    monkeypatch.setattr(base.deepseek, "chat", fake_chat)
    state = SharedState(
        session_id="s1",
        user_id="u1",
        resume_state=ResumeState(normalized_base_resume="Python SQL analyst resume"),
        career_state=CareerState(
            hard_constraints={"locations": ["Birmingham"]},
            soft_preferences={"title_keywords": ["analyst"]},
        ),
    )

    updated = await run_matching_agent(
        state,
        retrieval_plan={
            "hard_constraints": {"locations": ["Birmingham"]},
            "soft_prefs": {"title_keywords": ["analyst"]},
            "top_k": 3,
            "include_raptor": False,
        },
        search_fn=fake_search,
    )

    assert updated.retrieval_state.candidate_job_ids == ["job-1"]
    assert updated.retrieval_state.ranking_scores[0]["sources"] == ["bm25", "dense"]
    assert updated.strategy_state.recommended_roles[0]["tier"] == "now_fit"
    assert updated.strategy_state.recommended_roles[0]["job_id"] == "job-1"


@pytest.mark.asyncio
async def test_matching_agent_prompt_includes_job_evidence_content(monkeypatch):
    from app.agents import base
    from app.agents.matching_agent import run_matching_agent
    from app.retrieval.hybrid_search import JobCandidate
    from app.state.schema import ResumeState, SharedState

    async def fake_chat(system, user, **kwargs):
        assert "PHASE_C_MATCHING_AGENT" in system
        assert "Required skills: Python, SQL" in user
        assert "Build dashboards for stakeholders" in user
        return json.dumps({"recommended_roles": []})

    async def fake_search(**kwargs):
        return [
            JobCandidate(
                job_id="job-1",
                score=0.9,
                title="Data Analyst",
                company="Example",
                location="Birmingham",
                evidence_span_ids=[
                    "job-1:required_skills:1",
                    "job-1:responsibilities:1",
                ],
                evidence_spans=[
                    {
                        "evidence_span_id": "job-1:required_skills:1",
                        "field": "required_skills",
                        "content": "Required skills: Python, SQL",
                    },
                    {
                        "evidence_span_id": "job-1:responsibilities:1",
                        "field": "responsibilities",
                        "content": "Build dashboards for stakeholders",
                    },
                ],
            )
        ]

    monkeypatch.setattr(base.deepseek, "chat", fake_chat)
    state = SharedState(
        session_id="s1",
        user_id="u1",
        resume_state=ResumeState(normalized_base_resume="Python SQL analyst resume"),
    )

    updated = await run_matching_agent(
        state,
        retrieval_plan={"top_k": 1},
        search_fn=fake_search,
    )

    assert updated.retrieval_state.ranking_scores[0]["evidence_spans"][0][
        "content"
    ] == "Required skills: Python, SQL"


@pytest.mark.asyncio
async def test_matching_agent_outputs_three_tiers_with_supported_evidence(monkeypatch):
    from app.agents import base
    from app.agents.matching_agent import run_matching_agent
    from app.retrieval.hybrid_search import JobCandidate
    from app.state.schema import ResumeState, SharedState

    async def fake_chat(system, user, **kwargs):
        assert "PHASE_C_MATCHING_AGENT" in system
        return json.dumps(
            {
                "recommended_roles": [
                    {
                        "job_id": "job-now",
                        "tier": "now_fit",
                        "match_explanation": "Direct Python and SQL evidence.",
                        "evidence_span_ids": ["job-now:skills:1", "NOT_FROM_CANDIDATE"],
                    },
                    {
                        "job_id": "job-stretch",
                        "tier": "stretch_fit",
                        "match_explanation": "ML exposure makes it a stretch.",
                        "evidence_span_ids": ["job-stretch:responsibilities:1"],
                    },
                    {
                        "job_id": "job-bridge",
                        "tier": "bridge_role",
                        "match_explanation": "Operations analytics bridges the gap.",
                        "evidence_span_ids": [],
                    },
                ]
            }
        )

    async def fake_search(**kwargs):
        return [
            JobCandidate(
                job_id="job-now",
                score=0.95,
                title="Data Analyst",
                evidence_span_ids=["job-now:skills:1"],
                evidence_spans=[
                    {
                        "evidence_span_id": "job-now:skills:1",
                        "field": "required_skills",
                        "content": "Python and SQL required.",
                    }
                ],
            ),
            JobCandidate(
                job_id="job-stretch",
                score=0.82,
                title="ML Analyst",
                evidence_span_ids=["job-stretch:responsibilities:1"],
                evidence_spans=[
                    {
                        "evidence_span_id": "job-stretch:responsibilities:1",
                        "field": "responsibilities",
                        "content": "Build machine learning reports.",
                    }
                ],
            ),
            JobCandidate(
                job_id="job-bridge",
                score=0.7,
                title="Operations Analyst",
                evidence_span_ids=["job-bridge:metadata:1"],
                evidence_spans=[
                    {
                        "evidence_span_id": "job-bridge:metadata:1",
                        "field": "metadata",
                        "content": "Operations analyst bridge role.",
                    }
                ],
            ),
        ]

    monkeypatch.setattr(base.deepseek, "chat", fake_chat)
    state = SharedState(
        session_id="s1",
        user_id="u1",
        resume_state=ResumeState(normalized_base_resume="Python SQL analyst resume"),
    )

    updated = await run_matching_agent(
        state,
        retrieval_plan={"top_k": 3},
        search_fn=fake_search,
    )

    roles = updated.strategy_state.recommended_roles
    assert [role["tier"] for role in roles] == [
        "now_fit",
        "stretch_fit",
        "bridge_role",
    ]
    assert roles[0]["evidence_span_ids"] == ["job-now:skills:1"]
    assert roles[2]["evidence_span_ids"] == ["job-bridge:metadata:1"]
    assert roles[0]["evidence_spans"] == [
        {
            "evidence_span_id": "job-now:skills:1",
            "field": "required_skills",
            "content": "Python and SQL required.",
        }
    ]
    assert updated.retrieval_state.candidate_job_ids == [
        "job-now",
        "job-stretch",
        "job-bridge",
    ]


@pytest.mark.asyncio
async def test_top_five_match_explanations_run_in_parallel():
    from app.agents.matching_agent import enrich_top_match_explanations
    from app.retrieval.hybrid_search import JobCandidate
    from app.state.schema import ResumeState, SharedState, StrategyState

    active = 0
    max_active = 0

    async def fake_chat(system, user, **kwargs):
        nonlocal active, max_active
        assert "PHASE_C_MATCHING_AGENT" in system
        payload = json.loads(user)
        candidate = payload["candidate"]
        active += 1
        max_active = max(max_active, active)
        try:
            await asyncio.sleep(0.05)
        finally:
            active -= 1
        return json.dumps(
            {
                "recommended_roles": [
                    {
                        "job_id": candidate["job_id"],
                        "tier": "now_fit",
                        "match_explanation": f"parallel explanation for {candidate['job_id']}",
                        "evidence_span_ids": candidate["evidence_span_ids"],
                    }
                ]
            }
        )

    candidates = [
        JobCandidate(
            job_id=f"job-{index}",
            score=1.0 - index * 0.01,
            title="Data Analyst",
            evidence_span_ids=[f"job-{index}:skills:1"],
        )
        for index in range(5)
    ]
    state = SharedState(
        session_id="s1",
        user_id="u1",
        resume_state=ResumeState(normalized_base_resume="Python SQL analyst resume"),
        strategy_state=StrategyState(
            recommended_roles=[
                {
                    "job_id": candidate.job_id,
                    "tier": "stretch_fit",
                    "match_explanation": "",
                    "evidence_span_ids": list(candidate.evidence_span_ids),
                }
                for candidate in candidates
            ]
        ),
    )

    started = time.perf_counter()
    await enrich_top_match_explanations(
        state,
        candidates,
        top_n=5,
        chat_fn=fake_chat,
    )
    elapsed = time.perf_counter() - started

    assert max_active == 5
    assert elapsed < 0.15
    assert state.strategy_state.recommended_roles[0]["match_explanation"] == (
        "parallel explanation for job-0"
    )


@pytest.mark.asyncio
async def test_one_failed_explanation_preserves_successful_siblings():
    from app.agents.matching_agent import enrich_top_match_explanations
    from app.retrieval.hybrid_search import JobCandidate
    from app.state.schema import ResumeState, SharedState, StrategyState

    async def fake_chat(system, user, **kwargs):
        assert "PHASE_C_MATCHING_AGENT" in system
        candidate = json.loads(user)["candidate"]
        if candidate["job_id"] == "job-3":
            raise RuntimeError("provider temporarily unavailable")
        return json.dumps(
            {
                "recommended_roles": [
                    {
                        "job_id": candidate["job_id"],
                        "tier": "now_fit",
                        "match_explanation": f"Explanation for {candidate['job_id']}",
                        "evidence_span_ids": candidate["evidence_span_ids"],
                    }
                ]
            }
        )

    candidates = [
        JobCandidate(
            job_id=f"job-{index}",
            score=1.0 - index * 0.01,
            title="Data Analyst",
            evidence_span_ids=[f"job-{index}:skills:1"],
        )
        for index in range(1, 6)
    ]
    state = SharedState(
        session_id="s1",
        user_id="u1",
        resume_state=ResumeState(normalized_base_resume="Python SQL analyst resume"),
        strategy_state=StrategyState(
            recommended_roles=[
                {
                    "job_id": candidate.job_id,
                    "tier": "stretch_fit",
                    "match_explanation": "",
                    "evidence_span_ids": list(candidate.evidence_span_ids),
                }
                for candidate in candidates
            ]
        ),
    )

    await enrich_top_match_explanations(
        state,
        candidates,
        top_n=5,
        chat_fn=fake_chat,
    )

    roles = state.strategy_state.recommended_roles
    assert sum(bool(role["match_explanation"]) for role in roles) == 4
    assert state.supervisor_log[-1]["requested"] == 5
    assert state.supervisor_log[-1]["updated"] == 4
    assert state.supervisor_log[-1]["failed"] == 1
    assert state.supervisor_log[-1]["failed_job_ids"] == ["job-3"]
    assert state.supervisor_log[-1]["mode"] == "parallel"


@pytest.mark.asyncio
async def test_empty_new_explanation_keeps_existing_role_unchanged():
    from app.agents.matching_agent import enrich_top_match_explanations
    from app.retrieval.hybrid_search import JobCandidate
    from app.state.schema import ResumeState, SharedState, StrategyState

    candidate = JobCandidate(
        job_id="job-1",
        score=0.9,
        title="Data Analyst",
        evidence_span_ids=["job-1:skills:1"],
    )
    existing_role = {
        "job_id": "job-1",
        "tier": "bridge_role",
        "match_explanation": "Existing evidence-backed explanation.",
        "evidence_span_ids": ["job-1:skills:1"],
    }

    async def fake_chat(system, user, **kwargs):
        assert "PHASE_C_MATCHING_AGENT" in system
        return json.dumps(
            {
                "recommended_roles": [
                    {
                        "job_id": "job-1",
                        "tier": "now_fit",
                        "match_explanation": "",
                        "evidence_span_ids": ["job-1:skills:1"],
                    }
                ]
            }
        )

    state = SharedState(
        session_id="s1",
        user_id="u1",
        resume_state=ResumeState(normalized_base_resume="Python SQL analyst resume"),
        strategy_state=StrategyState(recommended_roles=[existing_role.copy()]),
    )

    await enrich_top_match_explanations(
        state,
        [candidate],
        chat_fn=fake_chat,
    )

    assert state.strategy_state.recommended_roles == [existing_role]
    assert state.supervisor_log[-1]["updated"] == 0
    assert state.supervisor_log[-1]["failed"] == 1
    assert state.supervisor_log[-1]["failed_job_ids"] == ["job-1"]


@pytest.mark.asyncio
async def test_strategy_agent_keeps_resume_advice_bound_to_evidence(monkeypatch):
    from app.agents import base
    from app.agents.strategy_agent import run_strategy_agent
    from app.state.schema import ResumeState, SharedState, StrategyState

    async def fake_chat(system, user, **kwargs):
        assert "PHASE_C_STRATEGY_AGENT" in system
        assert "R001" in user
        return json.dumps(
                {
                    "skill_gap_analysis": [
                        {
                            "skill": "SQL",
                            "priority": "high",
                            "evidence_span_ids": ["R001"],
                        }
                    ],
                "resume_revision_plan": [
                    {
                        "section": "experience",
                        "suggestion": "Quantify the Python dashboard impact.",
                        "evidence_span_ids": ["R001"],
                    },
                    {
                        "section": "experience",
                        "suggestion": "Claim invented Kubernetes production work.",
                        "evidence_span_ids": ["MISSING"],
                    },
                ],
                    "career_path": [
                        {
                            "horizon": "short",
                            "action": "Apply to analyst roles",
                            "evidence_span_ids": ["R001"],
                        }
                    ],
            }
        )

    monkeypatch.setattr(base.deepseek, "chat", fake_chat)
    state = SharedState(
        session_id="s1",
        user_id="u1",
        resume_state=ResumeState(
            normalized_base_resume="Python dashboard project",
            original_evidence_spans=[
                {"span_id": "R001", "text": "Built a Python dashboard."}
            ],
        ),
        strategy_state=StrategyState(
            recommended_roles=[
                {
                    "job_id": "job-1",
                    "tier": "now_fit",
                    "evidence_span_ids": ["job-1:required_skills:1"],
                }
            ]
        ),
    )

    updated = await run_strategy_agent(state)

    assert updated.strategy_state.skill_gap_analysis == [
        {"skill": "SQL", "priority": "high", "evidence_span_ids": ["R001"]}
    ]
    assert updated.strategy_state.resume_revision_plan == [
        {
            "section": "experience",
            "suggestion": "Quantify the Python dashboard impact.",
            "evidence_span_ids": ["R001"],
        }
    ]
    assert updated.supervisor_log[-1]["stage"] == "strategy_agent"
    assert updated.supervisor_log[-1]["dropped_unsupported_advice"] == 1


@pytest.mark.asyncio
async def test_strategy_agent_outputs_complete_evidence_grounded_strategy(monkeypatch):
    from app.agents import base
    from app.agents.strategy_agent import run_strategy_agent
    from app.state.schema import (
        ResumeState,
        RetrievalState,
        SharedState,
        StrategyState,
    )

    async def fake_chat(system, user, **kwargs):
        assert "PHASE_C_STRATEGY_AGENT" in system
        assert "R001" in user
        assert "job-1:skills:1" in user
        return json.dumps(
            {
                "skill_gap_analysis": [
                    {
                        "skill": "SQL",
                        "gap": "Role requires SQL reporting beyond current project evidence.",
                        "priority": "high",
                        "evidence_span_ids": ["job-1:skills:1", "R001"],
                    },
                    {
                        "skill": "Kubernetes",
                        "gap": "Unsupported invented gap.",
                        "priority": "high",
                        "evidence_span_ids": ["MISSING"],
                    },
                ],
                "resume_revision_plan": [
                    {
                        "section": "projects",
                        "suggestion": "Emphasize the Python dashboard work.",
                        "evidence_span_ids": ["R001"],
                    },
                    {
                        "section": "experience",
                        "suggestion": "Invent production Kubernetes ownership.",
                        "evidence_span_ids": ["job-1:skills:1"],
                    },
                ],
                "career_path": [
                    {
                        "horizon": "short",
                        "action": "Apply to now-fit analyst roles.",
                        "evidence_span_ids": ["job-1:skills:1"],
                    },
                    {
                        "horizon": "medium",
                        "action": "Build SQL reporting depth for stretch roles.",
                        "evidence_span_ids": ["job-2:responsibilities:1"],
                    },
                    {
                        "horizon": "long",
                        "action": "Move toward product analytics after evidence-backed analyst work.",
                        "evidence_span_ids": ["R001", "job-2:responsibilities:1"],
                    },
                    {
                        "horizon": "someday",
                        "action": "Unsupported path item.",
                        "evidence_span_ids": ["job-1:skills:1"],
                    },
                ],
            }
        )

    monkeypatch.setattr(base.deepseek, "chat", fake_chat)
    state = SharedState(
        session_id="s1",
        user_id="u1",
        resume_state=ResumeState(
            normalized_base_resume="Built a Python dashboard for reporting.",
            skills=["Python"],
            original_evidence_spans=[
                {"span_id": "R001", "text": "Built a Python dashboard."}
            ],
        ),
        retrieval_state=RetrievalState(
            evidence_span_ids=["job-1:skills:1", "job-2:responsibilities:1"],
            ranking_scores=[
                {
                    "job_id": "job-1",
                    "evidence_spans": [
                        {
                            "evidence_span_id": "job-1:skills:1",
                            "content": "Required skills: SQL, dashboards.",
                        }
                    ],
                },
                {
                    "job_id": "job-2",
                    "evidence_spans": [
                        {
                            "evidence_span_id": "job-2:responsibilities:1",
                            "content": "Build stakeholder reporting pipelines.",
                        }
                    ],
                },
            ],
        ),
        strategy_state=StrategyState(
            recommended_roles=[
                {
                    "job_id": "job-1",
                    "tier": "now_fit",
                    "match_explanation": "Python dashboard evidence matches.",
                    "evidence_span_ids": ["job-1:skills:1"],
                    "evidence_spans": [
                        {
                            "evidence_span_id": "job-1:skills:1",
                            "content": "Required skills: SQL, dashboards.",
                        }
                    ],
                }
            ]
        ),
    )

    updated = await run_strategy_agent(state)

    assert updated.strategy_state.skill_gap_analysis == [
        {
            "skill": "SQL",
            "gap": "Role requires SQL reporting beyond current project evidence.",
            "priority": "high",
            "evidence_span_ids": ["job-1:skills:1", "R001"],
        }
    ]
    assert updated.strategy_state.resume_revision_plan == [
        {
            "section": "projects",
            "suggestion": "Emphasize the Python dashboard work.",
            "evidence_span_ids": ["R001"],
        }
    ]
    assert [item["horizon"] for item in updated.strategy_state.career_path] == [
        "short",
        "medium",
        "long",
    ]
    assert updated.supervisor_log[-1] == {
        "stage": "strategy_agent",
        "dropped_unsupported_advice": 1,
        "dropped_unsupported_skill_gaps": 1,
        "dropped_unsupported_path_items": 1,
    }


@pytest.mark.asyncio
async def test_orchestrator_runs_three_agents_and_supervisor(monkeypatch):
    from app.agents import base, supervisor
    from app.agents.orchestrator import run_agentic_match_from_state
    from app.retrieval.hybrid_search import JobCandidate
    from app.state.schema import ResumeState, SharedState

    async def fake_chat(system, user, **kwargs):
        if "PHASE_C_INTENT_AGENT" in system:
            return json.dumps(
                {
                    "current_goal": ["data analyst"],
                    "long_term_goal": [],
                    "hard_constraints": {"locations": ["Birmingham"]},
                    "soft_preferences": {"title_keywords": ["analyst"]},
                    "avoid_roles": [],
                }
            )
        if "PHASE_C_SUPERVISOR_PLANNING" in system:
            return json.dumps(
                {
                    "needs_clarification": False,
                    "retrieval_plan": {
                        "hard_constraints": {"locations": ["Birmingham"]},
                        "soft_preferences": {"title_keywords": ["analyst"]},
                        "top_k": 1,
                        "include_raptor": False,
                    },
                }
            )
        if "PHASE_C_MATCHING_AGENT" in system:
            return json.dumps(
                {
                    "recommended_roles": [
                        {
                            "job_id": "job-1",
                            "tier": "now_fit",
                            "match_explanation": "Python evidence matches.",
                            "evidence_span_ids": ["job-1:skills:1"],
                        }
                    ]
                }
            )
        if "PHASE_C_STRATEGY_AGENT" in system:
            return json.dumps(
                {
                    "skill_gap_analysis": [
                        {
                            "skill": "SQL",
                            "priority": "medium",
                            "evidence_span_ids": ["R001", "job-1:skills:1"],
                        }
                    ],
                    "resume_revision_plan": [
                        {
                            "section": "projects",
                            "suggestion": "Emphasize the Python dashboard.",
                            "evidence_span_ids": ["R001"],
                        }
                    ],
                    "career_path": [
                        {
                            "horizon": "short",
                            "action": "Apply to analyst roles",
                            "evidence_span_ids": ["job-1:skills:1"],
                        }
                    ],
                }
            )
        if "PHASE_C_SUPERVISOR_FINAL" in system:
            return json.dumps(
                {
                    "hard_filter_violations": [],
                    "missing_evidence": [],
                    "fabrication_risks": [],
                    "needs_reretrieval": False,
                    "needs_repair": False,
                }
            )
        raise AssertionError(system)

    async def fake_search(**kwargs):
        return [
            JobCandidate(
                job_id="job-1",
                score=0.91,
                title="Data Analyst",
                company="Example",
                location="Birmingham",
                evidence_span_ids=["job-1:skills:1"],
                sources=["bm25", "dense"],
            )
        ]

    monkeypatch.setattr(base.deepseek, "chat", fake_chat)
    monkeypatch.setattr(supervisor.deepseek, "chat", fake_chat)
    state = SharedState(
        session_id="s1",
        user_id="u1",
        resume_state=ResumeState(
            normalized_base_resume="Python dashboard analyst resume",
            skills=["Python"],
            original_evidence_spans=[
                {"span_id": "R001", "text": "Built a Python dashboard."}
            ],
        ),
    )

    result = await run_agentic_match_from_state(
        state,
        user_goal_text="Find data analyst jobs in Birmingham",
        top_k=1,
        search_fn=fake_search,
    )

    assert result.state.career_state.current_goal == ["data analyst"]
    assert result.state.retrieval_state.candidate_job_ids == ["job-1"]
    assert result.state.strategy_state.recommended_roles[0]["tier"] == "now_fit"
    assert result.state.strategy_state.skill_gap_analysis[0]["skill"] == "SQL"
    assert result.final_verification["needs_repair"] is False
    assert [entry["stage"] for entry in result.state.supervisor_log] == [
        "planning",
        "matching_explanations",
        "strategy_agent",
        "final_verification",
    ]


@pytest.mark.asyncio
async def test_supervisor_relaxes_soft_preferences_when_retrieval_results_are_too_few(
    monkeypatch,
):
    from app.agents import base, supervisor
    from app.agents.orchestrator import run_agentic_match_from_state
    from app.retrieval.hybrid_search import JobCandidate
    from app.state.schema import ResumeState, SharedState

    async def fake_chat(system, user, **kwargs):
        if "PHASE_C_INTENT_AGENT" in system:
            return json.dumps(
                {
                    "current_goal": ["data analyst"],
                    "long_term_goal": [],
                    "hard_constraints": {"locations": ["Birmingham"]},
                    "soft_preferences": {
                        "title_keywords": ["fintech"],
                        "preferred_role_clusters": ["analytics"],
                    },
                    "avoid_roles": [],
                }
            )
        if "PHASE_C_SUPERVISOR_PLANNING" in system:
            return json.dumps(
                {
                    "needs_clarification": False,
                    "retrieval_plan": {
                        "hard_constraints": {"locations": ["Birmingham"]},
                        "soft_preferences": {
                            "title_keywords": ["fintech"],
                            "preferred_role_clusters": ["analytics"],
                        },
                        "top_k": 3,
                        "include_raptor": False,
                    },
                }
            )
        if "PHASE_C_MATCHING_AGENT" in system:
            roles = []
            if "job-1" in user:
                roles.append(
                    {
                        "job_id": "job-1",
                        "tier": "now_fit",
                        "match_explanation": "Python evidence matches.",
                        "evidence_span_ids": ["job-1:skills:1"],
                    }
                )
            if "job-2" in user:
                roles.append(
                    {
                        "job_id": "job-2",
                        "tier": "stretch_fit",
                        "match_explanation": "SQL evidence makes this a stretch.",
                        "evidence_span_ids": ["job-2:skills:1"],
                    }
                )
            if "job-3" in user:
                roles.append(
                    {
                        "job_id": "job-3",
                        "tier": "bridge_role",
                        "match_explanation": "Reporting evidence makes this a bridge.",
                        "evidence_span_ids": ["job-3:skills:1"],
                    }
                )
            return json.dumps({"recommended_roles": roles})
        if "PHASE_C_STRATEGY_AGENT" in system:
            return json.dumps(
                {
                    "skill_gap_analysis": [],
                    "resume_revision_plan": [
                        {
                            "section": "projects",
                            "suggestion": "Use the Python project evidence.",
                            "evidence_span_ids": ["R001"],
                        }
                    ],
                    "career_path": [],
                }
            )
        if "PHASE_C_SUPERVISOR_FINAL" in system:
            return json.dumps(
                {
                    "hard_filter_violations": [],
                    "missing_evidence": [],
                    "fabrication_risks": [],
                    "needs_reretrieval": False,
                    "needs_repair": False,
                }
            )
        raise AssertionError(system)

    search_calls = []

    def candidate(job_id: str) -> JobCandidate:
        return JobCandidate(
            job_id=job_id,
            score=0.9,
            title="Data Analyst",
            company="Example",
            location="Birmingham",
            evidence_span_ids=[f"{job_id}:skills:1"],
        )

    async def fake_search(**kwargs):
        search_calls.append(kwargs)
        if kwargs["soft_prefs"]:
            return [candidate("job-1")]
        return [candidate("job-1"), candidate("job-2"), candidate("job-3")]

    monkeypatch.setattr(base.deepseek, "chat", fake_chat)
    monkeypatch.setattr(supervisor.deepseek, "chat", fake_chat)
    state = SharedState(
        session_id="s1",
        user_id="u1",
        resume_state=ResumeState(
            normalized_base_resume="Python dashboard analyst resume",
            original_evidence_spans=[
                {"span_id": "R001", "text": "Built a Python dashboard."}
            ],
        ),
    )

    result = await run_agentic_match_from_state(
        state,
        user_goal_text="Find data analyst jobs in Birmingham",
        top_k=3,
        search_fn=fake_search,
    )

    assert len(search_calls) == 2
    assert search_calls[0]["soft_prefs"] == {
        "title_keywords": ["fintech"],
        "preferred_role_clusters": ["analytics"],
    }
    assert search_calls[1]["soft_prefs"] == {}
    assert result.state.retrieval_state.candidate_job_ids == [
        "job-1",
        "job-2",
        "job-3",
    ]
    assert result.final_verification["reretrieval_loop_used"] == 1
    reretrieval_logs = [
        entry
        for entry in result.state.supervisor_log
        if entry.get("stage") == "reretrieval_loop"
    ]
    assert reretrieval_logs[0]["reason"] == "too_few_results"
    assert reretrieval_logs[0]["relaxed_soft_prefs"] == {
        "title_keywords": ["fintech"],
        "preferred_role_clusters": ["analytics"],
    }


@pytest.mark.asyncio
async def test_orchestrator_executes_one_reretrieval_when_supervisor_requests_it(
    monkeypatch,
):
    from app.agents import base, supervisor
    from app.agents.orchestrator import run_agentic_match_from_state
    from app.retrieval.hybrid_search import JobCandidate
    from app.state.schema import ResumeState, SharedState

    final_calls = 0

    async def fake_chat(system, user, **kwargs):
        nonlocal final_calls
        if "PHASE_C_INTENT_AGENT" in system:
            return json.dumps(
                {
                    "current_goal": ["data analyst"],
                    "long_term_goal": [],
                    "hard_constraints": {"locations": ["Birmingham"]},
                    "soft_preferences": {},
                    "avoid_roles": [],
                }
            )
        if "PHASE_C_SUPERVISOR_PLANNING" in system:
            return json.dumps(
                {
                    "needs_clarification": False,
                    "retrieval_plan": {
                        "hard_constraints": {"locations": ["Birmingham"]},
                        "soft_preferences": {},
                        "top_k": 1,
                        "include_raptor": False,
                    },
                }
            )
        if "PHASE_C_MATCHING_AGENT" in system:
            return json.dumps(
                {
                    "recommended_roles": [
                        {
                            "job_id": "job-2" if "job-2" in user else "job-1",
                            "tier": "now_fit",
                            "match_explanation": "Evidence-backed match.",
                            "evidence_span_ids": ["job:skills"],
                        }
                    ]
                }
            )
        if "PHASE_C_STRATEGY_AGENT" in system:
            return json.dumps(
                {
                    "skill_gap_analysis": [],
                    "resume_revision_plan": [
                        {
                            "section": "projects",
                            "suggestion": "Use the Python project evidence.",
                            "evidence_span_ids": ["R001"],
                        }
                    ],
                    "career_path": [],
                }
            )
        if "PHASE_C_SUPERVISOR_FINAL" in system:
            final_calls += 1
            return json.dumps(
                {
                    "hard_filter_violations": []
                    if final_calls > 1
                    else [{"job_id": "job-1", "field": "location"}],
                    "missing_evidence": [],
                    "fabrication_risks": [],
                    "needs_reretrieval": final_calls == 1,
                    "needs_repair": False,
                }
            )
        raise AssertionError(system)

    search_calls = []

    async def fake_search(**kwargs):
        search_calls.append(kwargs)
        job_id = f"job-{len(search_calls)}"
        return [
            JobCandidate(
                job_id=job_id,
                score=0.9,
                title="Data Analyst",
                company="Example",
                location="Birmingham",
                evidence_span_ids=["job:skills"],
            )
        ]

    monkeypatch.setattr(base.deepseek, "chat", fake_chat)
    monkeypatch.setattr(supervisor.deepseek, "chat", fake_chat)
    state = SharedState(
        session_id="s1",
        user_id="u1",
        resume_state=ResumeState(
            normalized_base_resume="Python dashboard analyst resume",
            original_evidence_spans=[
                {"span_id": "R001", "text": "Built a Python dashboard."}
            ],
        ),
    )

    result = await run_agentic_match_from_state(
        state,
        user_goal_text="Find data analyst jobs in Birmingham",
        top_k=1,
        search_fn=fake_search,
    )

    assert len(search_calls) == 2
    assert result.state.retrieval_state.candidate_job_ids == ["job-2"]
    assert result.final_verification["reretrieval_loop_used"] == 1
    assert "reretrieval_loop" in [
        entry.get("stage") for entry in result.state.supervisor_log
    ]
    final_verification_logs = [
        entry
        for entry in result.state.supervisor_log
        if entry.get("stage") == "final_verification"
    ]
    assert final_verification_logs[-1]["reretrieval_loop_used"] == 1
