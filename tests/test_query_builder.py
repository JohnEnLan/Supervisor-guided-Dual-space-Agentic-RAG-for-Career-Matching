import os

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")
os.environ.setdefault("QWEN_API_KEY", "sk-test")

from app.retrieval.query_builder import build_resume_retrieval_query
from app.config import settings
from app.state.schema import ResumeState


def test_build_resume_retrieval_query_uses_fielded_resume_sections():
    resume_state = ResumeState(
        normalized_base_resume=(
            "Business analyst candidate with Python, SQL, market research, "
            "and strategy internship experience."
        ),
        skills=["Python", "SQL", "Python", "Market research"],
        experience=[
            {
                "title": "Corporate Strategy Intern",
                "company": "Meituan",
                "responsibilities": [
                    "Competitor analysis",
                    "Python dashboard reporting",
                ],
                "achievements": ["Presented strategy findings"],
            }
        ],
        projects=[
            {
                "name": "Short video e-commerce analysis",
                "description": "Compared platform conversion patterns with SPSS.",
            }
        ],
    )

    query = build_resume_retrieval_query(resume_state)

    assert set(query.field_texts) == {"summary", "skills", "experience", "projects"}
    assert query.field_texts["skills"] == "Python; SQL; Market research"
    assert "Summary:" in query.text
    assert "Skills: Python; SQL; Market research" in query.text
    assert "Experience: Corporate Strategy Intern" in query.text
    assert "Projects: Short video e-commerce analysis" in query.text
    assert query.text.index("Summary:") < query.text.index("Skills:")


def test_build_resume_retrieval_query_consumes_effective_resume_text(monkeypatch):
    monkeypatch.setattr(settings, "resume_clarify_enabled", True)
    baseline_state = ResumeState(normalized_base_resume="Python analyst resume")
    clarified_state = baseline_state.model_copy(deep=True)
    clarified_state.clarification_evidence_spans = [
        {
            "span_id": "C001",
            "text": "Built a FastAPI service for 500 users.",
            "source": "user_clarification",
        }
    ]

    baseline = build_resume_retrieval_query(baseline_state)
    clarified = build_resume_retrieval_query(clarified_state)

    assert baseline.text == "Summary: Python analyst resume"
    assert clarified.text != baseline.text
    assert "Built a FastAPI service for 500 users." in clarified.text


def test_build_resume_retrieval_query_is_word_for_word_unchanged_without_data(
    monkeypatch,
):
    monkeypatch.setattr(settings, "resume_clarify_enabled", True)
    state = ResumeState(
        normalized_base_resume="  Python analyst\nwith SQL  ",
        clarification_evidence_spans=[],
    )

    query = build_resume_retrieval_query(state)

    assert query.text == "Summary: Python analyst with SQL"
    assert query.field_texts["summary"] == "Python analyst with SQL"
