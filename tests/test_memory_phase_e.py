import os

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")
os.environ.setdefault("QWEN_API_KEY", "sk-test")


class FakeAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return FakeAcquire(self.conn)


def test_private_resume_payload_keeps_raw_resume_in_private_memory_only():
    from app.memory.private_memory import build_private_resume_payload
    from app.state.schema import ResumeState

    payload = build_private_resume_payload(
        resume_state=ResumeState(
            normalized_base_resume="Normalized analyst resume",
            original_evidence_spans=[{"span_id": "R001", "text": "Raw evidence"}],
        ),
        raw_resume_text="John Example john@example.com raw resume text",
        user_goal_text="Find analyst roles",
    )

    assert payload["raw_resume_text"] == "John Example john@example.com raw resume text"
    assert payload["memory_scope"] == "private"
    assert "case_base" not in payload


@pytest.mark.asyncio
async def test_save_private_resume_memory_upserts_by_user_and_version(monkeypatch):
    from app.memory import private_memory
    from app.state.schema import ResumeState

    calls = []

    class FakeConn:
        async def execute(self, sql, *args):
            calls.append((sql, args))

    async def fake_get_pool():
        return FakePool(FakeConn())

    monkeypatch.setattr(private_memory, "get_pool", fake_get_pool)

    await private_memory.save_private_resume_memory(
        user_id="u1",
        resume_version_id="v1",
        resume_state=ResumeState(normalized_base_resume="base"),
        raw_resume_text="private raw text",
    )

    sql, args = calls[0]
    assert "private_memory" in sql
    assert args[0] == "u1"
    assert args[1] == "v1"
    assert "private raw text" in args[2]


@pytest.mark.asyncio
async def test_feedback_records_outcomes_and_positive_policy(monkeypatch):
    from app.memory import feedback

    class FakeConn:
        async def fetchrow(self, sql, *args):
            self.args = args
            return {"feedback_id": 7}

    conn = FakeConn()

    async def fake_get_pool():
        return FakePool(conn)

    monkeypatch.setattr(feedback, "get_pool", fake_get_pool)

    assert feedback.is_positive_outcome("interview_1") is True
    assert feedback.is_positive_outcome("rejected") is False

    feedback_id = await feedback.record_application_feedback(
        user_id="u1",
        job_id="job-1",
        outcome="interview_1",
        reason="good screen",
        user_rating=4,
    )

    assert feedback_id == 7
    assert conn.args == ("u1", "job-1", "interview_1", "good screen", 4)


def test_case_base_rejects_pii_and_builds_anonymous_embedding_text():
    from app.memory.case_base import CareerCase, build_case_embedding_text

    case = CareerCase(
        case_id="case-001",
        background_type="business_undergraduate_with_python",
        target_role="Data Analyst",
        successful_resume_features=["SQL project", "dashboard evidence"],
        missing_skills_before=["advanced SQL"],
        application_outcome="interview_1",
        recommended_bridge_roles=["Business Analyst Intern"],
    )

    text = build_case_embedding_text(case)

    assert "business_undergraduate_with_python" in text
    assert "Data Analyst" in text
    assert "john@" not in text.lower()

    with pytest.raises(ValueError):
        CareerCase(
            case_id="bad",
            background_type="john@example.com",
            target_role="Data Analyst",
            successful_resume_features=[],
            missing_skills_before=[],
            application_outcome="offer",
            recommended_bridge_roles=[],
        ).validate_anonymous()


@pytest.mark.asyncio
async def test_search_similar_cases_uses_query_embedding(monkeypatch):
    from app.memory import case_base

    class FakeConn:
        async def fetch(self, sql, *args):
            self.args = args
            return [
                {
                    "case_id": "case-001",
                    "background_type": "business_undergraduate",
                    "target_role": "Data Analyst",
                    "successful_resume_features": ["SQL project"],
                    "missing_skills_before": ["advanced SQL"],
                    "application_outcome": "interview_1",
                    "recommended_bridge_roles": ["Business Analyst Intern"],
                    "score": 0.9,
                }
            ]

    conn = FakeConn()

    async def fake_get_pool():
        return FakePool(conn)

    async def fake_embed_one(text):
        assert "analyst" in text
        return [0.1] * 1024

    monkeypatch.setattr(case_base, "get_pool", fake_get_pool)
    monkeypatch.setattr(case_base, "embed_one", fake_embed_one)

    rows = await case_base.search_similar_cases("analyst with SQL", top_k=3)

    assert rows[0]["case_id"] == "case-001"
    assert rows[0]["score"] == 0.9
    assert conn.args[1] == 3


def test_seed_cases_are_10_to_20_and_anonymous():
    from app.memory.case_base import contains_pii
    from scripts.seed_cases import DEFAULT_CASES

    assert 10 <= len(DEFAULT_CASES) <= 20
    for case in DEFAULT_CASES:
        case.validate_anonymous()
        assert contains_pii(case.background_type) is False
        assert "raw_resume" not in case.model_dump()
