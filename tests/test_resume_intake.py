import os
from pathlib import Path

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")
os.environ.setdefault("QWEN_API_KEY", "sk-test")


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
