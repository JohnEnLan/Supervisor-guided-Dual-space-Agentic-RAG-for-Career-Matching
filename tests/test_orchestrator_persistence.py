import os
from pathlib import Path

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")
os.environ.setdefault("QWEN_API_KEY", "sk-test")


@pytest.mark.asyncio
async def test_persisted_resume_flow_saves_and_loads_state_between_stages(monkeypatch):
    from app.agents import orchestrator
    from app.normalization.resume_intake import ResumeIntakeResult
    from app.state.schema import ResumeState, SharedState

    calls = []
    stored: dict[str, SharedState] = {}

    async def fake_save_state(state, status):
        calls.append(("save", status))
        stored[state.session_id] = state.model_copy(deep=True)

    async def fake_load_state(session_id):
        calls.append(("load", session_id))
        return stored[session_id].model_copy(deep=True)

    async def fake_intake_resume(path, *, session_id, user_id, save_to_db):
        calls.append(("intake", path, save_to_db))
        return ResumeIntakeResult(
            state=SharedState(
                session_id=session_id,
                user_id=user_id,
                resume_state=ResumeState(
                    normalized_base_resume="Python dashboard analyst resume",
                    original_evidence_spans=[
                        {"span_id": "R001", "text": "Built a Python dashboard."}
                    ],
                ),
            ),
            raw_text="raw resume",
            extracted_pages=1,
        )

    async def fake_run_intent_agent(state, user_goal_text):
        calls.append(("intent", user_goal_text))
        state.career_state.current_goal = ["data analyst"]
        return state

    async def fake_plan_retrieval(
        state, *, user_goal_text, default_top_k, include_raptor
    ):
        calls.append(("planning", default_top_k, include_raptor))
        plan = {
            "hard_constraints": {"locations": ["Birmingham"]},
            "soft_prefs": {"title_keywords": ["analyst"]},
            "top_k": default_top_k,
            "include_raptor": include_raptor,
        }
        state.supervisor_log.append({"stage": "planning", "retrieval_plan": plan})
        return plan

    async def fake_run_matching_agent(state, *, retrieval_plan, search_fn):
        calls.append(("matching", retrieval_plan["top_k"]))
        state.retrieval_state.candidate_job_ids = ["job-1"]
        state.strategy_state.recommended_roles = [
            {
                "job_id": "job-1",
                "tier": "now_fit",
                "evidence_span_ids": ["job-1:skills:1"],
            }
        ]
        return state

    async def fake_run_strategy_agent(state):
        calls.append(("strategy", list(state.retrieval_state.candidate_job_ids)))
        state.strategy_state.resume_revision_plan = [
            {
                "section": "projects",
                "suggestion": "Emphasize the Python dashboard.",
                "evidence_span_ids": ["R001"],
            }
        ]
        return state

    async def fake_final_verification(state):
        calls.append(("final_verification", list(state.strategy_state.recommended_roles)))
        result = {
            "needs_repair": False,
            "needs_reretrieval": False,
            "reretrieval_loop_requested": False,
            "reretrieval_loop_used": 0,
        }
        state.supervisor_log.append({"stage": "final_verification", **result})
        return result

    monkeypatch.setattr(orchestrator, "save_state", fake_save_state)
    monkeypatch.setattr(orchestrator, "load_state", fake_load_state)
    monkeypatch.setattr(orchestrator, "intake_resume", fake_intake_resume)
    monkeypatch.setattr(orchestrator, "run_intent_agent", fake_run_intent_agent)
    monkeypatch.setattr(orchestrator, "plan_retrieval", fake_plan_retrieval)
    monkeypatch.setattr(orchestrator, "run_matching_agent", fake_run_matching_agent)
    monkeypatch.setattr(orchestrator, "run_strategy_agent", fake_run_strategy_agent)
    monkeypatch.setattr(orchestrator, "final_verification", fake_final_verification)

    result = await orchestrator.run_persisted_agentic_match_from_resume(
        Path("resume.txt"),
        session_id="s1",
        user_id="u1",
        user_goal_text="Find data analyst jobs in Birmingham",
        top_k=3,
        include_raptor=True,
    )

    assert result.state.strategy_state.recommended_roles[0]["job_id"] == "job-1"
    assert result.final_verification["reretrieval_loop_used"] == 0
    assert calls == [
        ("intake", Path("resume.txt"), False),
        ("save", "resume_normalized"),
        ("load", "s1"),
        ("intent", "Find data analyst jobs in Birmingham"),
        ("save", "intent_done"),
        ("load", "s1"),
        ("planning", 3, True),
        ("save", "supervisor_planning_done"),
        ("load", "s1"),
        ("matching", 3),
        ("save", "retrieval_done"),
        ("load", "s1"),
        ("strategy", ["job-1"]),
        ("save", "strategy_done"),
        ("load", "s1"),
        ("final_verification", [{"job_id": "job-1", "tier": "now_fit", "evidence_span_ids": ["job-1:skills:1"]}]),
        ("save", "agentic_done"),
    ]
    assert stored["s1"].strategy_state.resume_revision_plan == [
        {
            "section": "projects",
            "suggestion": "Emphasize the Python dashboard.",
            "evidence_span_ids": ["R001"],
        }
    ]
