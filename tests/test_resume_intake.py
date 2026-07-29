import json
import os
from pathlib import Path

import pytest
from docx import Document

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")
os.environ.setdefault("QWEN_API_KEY", "sk-test")


def test_docx_extraction_preserves_paragraph_and_table_order(tmp_path):
    from app.normalization import resume_intake as intake

    resume_path = tmp_path / "ordered.docx"
    document = Document()
    document.add_paragraph("Profile first")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "University of Birmingham"
    table.cell(0, 1).text = "MSc Computer Science"
    document.add_paragraph("Experience last")
    document.save(resume_path)

    text, page_count = intake.extract_resume_text(resume_path)

    assert page_count == 1
    assert text.splitlines() == [
        "Profile first",
        "University of Birmingham",
        "MSc Computer Science",
        "Experience last",
    ]


def test_normalization_prompt_contains_only_retained_span_text():
    from app.normalization import resume_intake as intake

    prompt = intake._build_user_prompt(
        "UNRETAINED RAW RESUME SECRET",
        [intake.EvidenceSpan(span_id="R001", text="Python data analysis")],
    )
    payload = json.loads(prompt)

    assert "UNRETAINED RAW RESUME SECRET" not in prompt
    assert payload == {
        "retained_resume_text": "[R001] Python data analysis",
        "evidence_spans": [
            {
                "span_id": "R001",
                "page": None,
                "text": "Python data analysis",
                "source": "resume",
            }
        ],
    }


@pytest.mark.asyncio
async def test_normalization_rejects_facts_without_retained_span_ids(monkeypatch):
    from app.normalization import resume_intake as intake

    async def fake_chat(_system, _user, **_kwargs):
        return json.dumps(
            {
                "education": [
                    {
                        "institution": "University of Birmingham",
                        "degree": "MSc",
                        "evidence_span_ids": ["R001", "MISSING"],
                    },
                    {
                        "institution": "Invented University",
                        "degree": "PhD",
                        "evidence_span_ids": ["MISSING"],
                    },
                    {
                        "institution": "Fabricated College",
                        "degree": "PhD",
                        "evidence_span_ids": ["R001"],
                    },
                ],
                "experience": [],
                "projects": [
                    {
                        "name": "Invented project",
                        "evidence_span_ids": [],
                    }
                ],
                "skills": [
                    {"skill": "Python", "evidence_span_ids": ["R001"]},
                    {"skill": "Go", "evidence_span_ids": ["MISSING"]},
                    {"skill": "Rust", "evidence_span_ids": ["R001"]},
                    "Rust",
                ],
                "resume_quality_issues": [
                    {
                        "issue": "Dense formatting",
                        "severity": "medium",
                        "evidence_span_ids": ["R001"],
                    },
                    {
                        "issue": "Invented issue",
                        "severity": "high",
                        "evidence_span_ids": ["MISSING"],
                    },
                ],
                "normalized_base_resume": "Python data analysis",
            }
        )

    monkeypatch.setattr(intake, "chat", fake_chat)
    spans = [
        intake.EvidenceSpan(
            span_id="R001",
            text="University of Birmingham MSc; Python data analysis",
        )
    ]

    result = await intake.normalize_resume_text("ignored raw text", spans)

    assert result.education == [
        {
            "institution": "University of Birmingham",
            "degree": "MSc",
            "evidence_span_ids": ["R001"],
        }
    ]
    assert result.projects == []
    assert result.skills == ["Python"]
    assert result.resume_quality_issues == [
        "unverified: medium: Dense formatting evidence=['R001']"
    ]


@pytest.mark.asyncio
async def test_intake_resume_save_to_db_does_not_close_global_pool(monkeypatch):
    from app.normalization import resume_intake as intake
    from app.state.schema import ResumeState

    calls = []

    async def fake_normalize_resume_text(raw_text, evidence_spans):
        return ResumeState(
            normalized_base_resume="normalized resume",
            original_evidence_spans=[span.model_dump() for span in evidence_spans],
        )

    async def fake_save_state(state, status):
        calls.append(("save_state", state.session_id, status))

    async def fake_close_pool():
        calls.append(("close_pool",))

    monkeypatch.setattr(intake, "extract_resume_text", lambda path: ("raw resume", 1))
    monkeypatch.setattr(
        intake,
        "build_evidence_spans",
        lambda raw_text: [intake.EvidenceSpan(span_id="R001", text=raw_text)],
    )
    monkeypatch.setattr(intake, "normalize_resume_text", fake_normalize_resume_text)
    monkeypatch.setattr(intake, "save_state", fake_save_state)
    monkeypatch.setattr(intake, "close_pool", fake_close_pool)

    result = await intake.intake_resume(
        Path("resume.pdf"),
        session_id="session-1",
        user_id="user-1",
        save_to_db=True,
    )

    assert result.state.session_id == "session-1"
    assert ("save_state", "session-1", "resume_normalized") in calls
    assert ("close_pool",) not in calls
