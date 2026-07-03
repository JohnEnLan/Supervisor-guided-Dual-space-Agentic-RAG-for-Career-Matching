import json
import os

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
async def test_strategy_agent_keeps_resume_advice_bound_to_evidence(monkeypatch):
    from app.agents import base
    from app.agents.strategy_agent import run_strategy_agent
    from app.state.schema import ResumeState, SharedState, StrategyState

    async def fake_chat(system, user, **kwargs):
        assert "PHASE_C_STRATEGY_AGENT" in system
        assert "R001" in user
        return json.dumps(
            {
                "skill_gap_analysis": [{"skill": "SQL", "priority": "high"}],
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
                "career_path": [{"horizon": "short", "action": "Apply to analyst roles"}],
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
        {"skill": "SQL", "priority": "high"}
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
                        "top_k": 2,
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
                    "skill_gap_analysis": [{"skill": "SQL", "priority": "medium"}],
                    "resume_revision_plan": [
                        {
                            "section": "projects",
                            "suggestion": "Emphasize the Python dashboard.",
                            "evidence_span_ids": ["R001"],
                        }
                    ],
                    "career_path": [
                        {"horizon": "short", "action": "Apply to analyst roles"}
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
        top_k=2,
        search_fn=fake_search,
    )

    assert result.state.career_state.current_goal == ["data analyst"]
    assert result.state.retrieval_state.candidate_job_ids == ["job-1"]
    assert result.state.strategy_state.recommended_roles[0]["tier"] == "now_fit"
    assert result.state.strategy_state.skill_gap_analysis[0]["skill"] == "SQL"
    assert result.final_verification["needs_repair"] is False
    assert [entry["stage"] for entry in result.state.supervisor_log] == [
        "planning",
        "strategy_agent",
        "final_verification",
    ]


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
