"""Stage 0 - Resume Intake & Normalization.

Input: PDF, docx, or plain text resume.
Output: SharedState.resume_state with structured resume fields, layout issues,
original evidence spans, and a normalized base resume.

Evidence spans are extracted locally from the original resume text before the
LLM call. The LLM may reference span ids, but it does not create the source
evidence itself.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
from typing import Any

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from pydantic import BaseModel, Field
from pypdf import PdfReader

from app.db.pool import close_pool
from app.db.state_store import save_state
from app.llm.deepseek import chat, extract_json_response
from app.state.schema import ResumeState, SharedState


SYSTEM_PROMPT = """You normalize resumes for an evidence-grounded career RAG system.
Return only valid JSON. Do not invent facts.

You will receive evidence spans extracted from the original resume. Use only
those spans. Every education, experience, project, skill, and resume issue item
must include evidence_span_ids. Omit any fact that cannot cite a supplied span.

Return this JSON shape:
{
  "education": [
    {
      "institution": string,
      "degree": string,
      "field": string,
      "dates": string,
      "details": [string],
      "evidence_span_ids": [string]
    }
  ],
  "experience": [
    {
      "organization": string,
      "title": string,
      "dates": string,
      "location": string,
      "responsibilities": [string],
      "achievements": [string],
      "technologies": [string],
      "evidence_span_ids": [string]
    }
  ],
  "projects": [
    {
      "name": string,
      "dates": string,
      "summary": string,
      "actions": [string],
      "technologies": [string],
      "outcomes": [string],
      "evidence_span_ids": [string]
    }
  ],
  "skills": [
    {
      "skill": string,
      "evidence_span_ids": [string]
    }
  ],
  "resume_quality_issues": [
    {
      "issue": string,
      "severity": "low" | "medium" | "high",
      "evidence_span_ids": [string]
    }
  ],
  "normalized_base_resume": string
}

Rules:
- Keep normalized_base_resume concise and query-friendly.
- Preserve real names of schools, employers, projects, tools, and measurable outcomes.
- If a fact is unclear, omit it or mark the field as an empty string.
- Never fabricate metrics, employers, degrees, dates, or skills.
"""


class ResumeIntakeResult(BaseModel):
    state: SharedState
    raw_text: str
    extracted_pages: int


class EvidenceSpan(BaseModel):
    span_id: str
    page: int | None = None
    text: str
    source: str = "resume"


class LLMResumePayload(BaseModel):
    education: list[dict[str, Any]] = Field(default_factory=list)
    experience: list[dict[str, Any]] = Field(default_factory=list)
    projects: list[dict[str, Any]] = Field(default_factory=list)
    skills: list[dict[str, Any] | str] = Field(default_factory=list)
    resume_quality_issues: list[dict[str, Any] | str] = Field(default_factory=list)
    normalized_base_resume: str = ""


def _compact_text(text: str) -> str:
    lines = [" ".join(line.strip().split()) for line in text.splitlines()]
    compact_lines: list[str] = []
    blank_seen = False
    for line in lines:
        if not line:
            if not blank_seen:
                compact_lines.append("")
            blank_seen = True
            continue
        compact_lines.append(line)
        blank_seen = False
    return "\n".join(compact_lines).strip()


def _read_pdf(path: Path) -> tuple[str, int]:
    reader = PdfReader(str(path))
    page_texts: list[str] = []
    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        text = _compact_text(text)
        if text:
            page_texts.append(f"[Page {page_number}]\n{text}")
    return "\n\n".join(page_texts).strip(), len(reader.pages)


def _read_docx(path: Path) -> tuple[str, int]:
    doc = Document(str(path))
    parts: list[str] = []
    for block in doc.iter_inner_content():
        if isinstance(block, Paragraph):
            if block.text.strip():
                parts.append(block.text)
            continue
        if isinstance(block, Table):
            for row in block.rows:
                for cell in row.cells:
                    parts.extend(
                        paragraph.text
                        for paragraph in cell.paragraphs
                        if paragraph.text.strip()
                    )
    return _compact_text("\n".join(parts)), 1


def _read_text(path: Path) -> tuple[str, int]:
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return _compact_text(path.read_text(encoding=encoding)), 1
        except UnicodeDecodeError:
            continue
    return _compact_text(path.read_text(errors="ignore")), 1


def extract_resume_text(path: Path) -> tuple[str, int]:
    suffix = path.suffix.casefold()
    if suffix == ".pdf":
        return _read_pdf(path)
    if suffix == ".docx":
        return _read_docx(path)
    if suffix in {".txt", ".md"}:
        return _read_text(path)
    raise ValueError(f"Unsupported resume file type: {path.suffix}")


def build_evidence_spans(raw_text: str, *, max_spans: int = 120) -> list[EvidenceSpan]:
    spans: list[EvidenceSpan] = []
    current_page: int | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        text = " ".join(part.strip() for part in buffer if part.strip()).strip()
        buffer = []
        if len(text) < 8:
            return
        if len(text) > 900:
            text = text[:900].rstrip()
        spans.append(
            EvidenceSpan(
                span_id=f"R{len(spans) + 1:03d}",
                page=current_page,
                text=text,
            )
        )

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if line.startswith("[Page ") and line.endswith("]"):
            flush()
            try:
                current_page = int(line.removeprefix("[Page ").removesuffix("]"))
            except ValueError:
                current_page = None
            continue
        if not line:
            flush()
            continue
        starts_new = (
            not buffer
            or line.startswith(("-", "*", "•", "●"))
            or line[:1].isdigit()
            or line.isupper()
            or len(" ".join(buffer)) > 350
        )
        if starts_new and buffer:
            flush()
        buffer.append(line)
    flush()

    return spans[:max_spans]


def _clean_string_list(values: Any, *, max_items: int = 80) -> list[str]:
    if not isinstance(values, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text:
            continue
        text = " ".join(text.split())
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text[:120])
        if len(cleaned) >= max_items:
            break
    return cleaned


def _normalize_quality_issues(values: list[dict[str, Any] | str]) -> list[str]:
    issues: list[str] = []
    for value in values:
        if isinstance(value, str):
            text = value.strip()
        else:
            severity = str(value.get("severity", "medium")).strip() or "medium"
            issue = str(value.get("issue", "")).strip()
            spans = value.get("evidence_span_ids") or []
            span_suffix = f" evidence={spans}" if spans else ""
            verification = str(value.get("verification_status") or "").strip()
            verification_prefix = (
                f"{verification}: " if verification == "unverified" else ""
            )
            text = (
                f"{verification_prefix}{severity}: {issue}{span_suffix}"
            ).strip()
        if text:
            issues.append(text)
    return issues


def _validated_span_ids(values: Any, valid_ids: set[str]) -> list[str]:
    if not isinstance(values, list):
        return []
    result: list[str] = []
    for value in values:
        span_id = str(value).strip()
        if span_id in valid_ids and span_id not in result:
            result.append(span_id)
    return result


def _validated_fact_items(
    values: Any,
    valid_ids: set[str],
    evidence_text_by_id: dict[str, str],
    *,
    reject_unsupported: bool = True,
) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        return []
    result: list[dict[str, Any]] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        evidence_span_ids = _validated_span_ids(
            value.get("evidence_span_ids"),
            valid_ids,
        )
        if not evidence_span_ids:
            continue
        supported = _fact_is_supported(
            value,
            evidence_span_ids,
            evidence_text_by_id,
        )
        if reject_unsupported and not supported:
            continue
        result.append(
            {
                **value,
                "evidence_span_ids": evidence_span_ids,
                **(
                    {"verification_status": "unverified"}
                    if not supported
                    else {}
                ),
            }
        )
    return result


def _validated_skills(
    values: Any,
    valid_ids: set[str],
    evidence_text_by_id: dict[str, str],
) -> list[str]:
    if not isinstance(values, list):
        return []
    verified: list[str] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        evidence_span_ids = _validated_span_ids(
            value.get("evidence_span_ids"),
            valid_ids,
        )
        if not evidence_span_ids:
            continue
        skill = str(value.get("skill") or value.get("name") or "").strip()
        if skill and _claim_is_supported(
            skill,
            evidence_span_ids,
            evidence_text_by_id,
        ):
            verified.append(skill)
    return _clean_string_list(verified)


def _fact_is_supported(
    value: dict[str, Any],
    evidence_span_ids: list[str],
    evidence_text_by_id: dict[str, str],
) -> bool:
    claims = _claim_strings(value)
    return bool(claims) and all(
        _claim_is_supported(
            claim,
            evidence_span_ids,
            evidence_text_by_id,
        )
        for claim in claims
    )


def _claim_strings(value: Any, *, field_name: str | None = None) -> list[str]:
    if field_name in {"evidence_span_ids", "severity", "verification_status"}:
        return []
    if isinstance(value, dict):
        return [
            claim
            for key, item in value.items()
            for claim in _claim_strings(item, field_name=key)
        ]
    if isinstance(value, list):
        return [
            claim
            for item in value
            for claim in _claim_strings(item, field_name=field_name)
        ]
    if isinstance(value, (str, int, float)):
        text = str(value).strip()
        return [text] if text else []
    return []


def _claim_is_supported(
    claim: str,
    evidence_span_ids: list[str],
    evidence_text_by_id: dict[str, str],
) -> bool:
    normalized_claim = _normalize_for_evidence_match(claim)
    source = _normalize_for_evidence_match(
        " ".join(
            evidence_text_by_id[span_id]
            for span_id in evidence_span_ids
            if span_id in evidence_text_by_id
        )
    )
    return bool(normalized_claim) and normalized_claim in source


def _normalize_for_evidence_match(value: str) -> str:
    return " ".join(re.findall(r"\w+", value.casefold()))


def _build_user_prompt(raw_text: str, evidence_spans: list[EvidenceSpan]) -> str:
    payload = {
        "retained_resume_text": "\n\n".join(
            f"[{span.span_id}] {span.text}" for span in evidence_spans
        ),
        "evidence_spans": [span.model_dump() for span in evidence_spans],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


async def normalize_resume_text(raw_text: str, evidence_spans: list[EvidenceSpan]) -> ResumeState:
    raw = await chat(
        SYSTEM_PROMPT,
        _build_user_prompt(raw_text, evidence_spans),
        temperature=0.0,
        json_mode=True,
    )
    parsed = LLMResumePayload.model_validate(extract_json_response(raw))
    valid_ids = {span.span_id for span in evidence_spans}
    evidence_text_by_id = {
        span.span_id: span.text
        for span in evidence_spans
    }
    education = _validated_fact_items(
        parsed.education,
        valid_ids,
        evidence_text_by_id,
    )
    experience = _validated_fact_items(
        parsed.experience,
        valid_ids,
        evidence_text_by_id,
    )
    projects = _validated_fact_items(
        parsed.projects,
        valid_ids,
        evidence_text_by_id,
    )
    quality_issues = _validated_fact_items(
        parsed.resume_quality_issues,
        valid_ids,
        evidence_text_by_id,
        reject_unsupported=False,
    )
    return ResumeState(
        education=education,
        experience=experience,
        projects=projects,
        skills=_validated_skills(
            parsed.skills,
            valid_ids,
            evidence_text_by_id,
        ),
        resume_quality_issues=_normalize_quality_issues(quality_issues),
        original_evidence_spans=[span.model_dump() for span in evidence_spans],
        normalized_base_resume=_compact_text(
            "\n".join(span.text for span in evidence_spans)
        ),
    )


async def intake_resume(
    path: Path,
    *,
    session_id: str,
    user_id: str,
    save_to_db: bool = False,
) -> ResumeIntakeResult:
    raw_text, page_count = extract_resume_text(path)
    if not raw_text:
        raise ValueError(f"No text could be extracted from resume: {path}")
    evidence_spans = build_evidence_spans(raw_text)
    if not evidence_spans:
        raise ValueError("No usable evidence spans could be extracted from resume text.")

    resume_state = await normalize_resume_text(raw_text, evidence_spans)
    state = SharedState(session_id=session_id, user_id=user_id, resume_state=resume_state)
    if save_to_db:
        await save_state(state, status="resume_normalized")
    return ResumeIntakeResult(state=state, raw_text=raw_text, extracted_pages=page_count)


def _write_json(path: Path, result: ResumeIntakeResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "extracted_pages": result.extracted_pages,
                "state": result.state.model_dump(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


async def _run_cli(args: argparse.Namespace) -> ResumeIntakeResult:
    try:
        return await intake_resume(
            args.resume_path,
            session_id=args.session_id,
            user_id=args.user_id,
            save_to_db=args.save_state,
        )
    finally:
        await close_pool()


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize a resume into SharedState.resume_state.")
    parser.add_argument("resume_path", type=Path)
    parser.add_argument("--session-id", default="sample-resume-session")
    parser.add_argument("--user-id", default="sample-user")
    parser.add_argument("--save-state", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    result = asyncio.run(_run_cli(args))

    output = args.output
    if output is not None:
        _write_json(output, result)

    resume_state = result.state.resume_state
    print(f"pages={result.extracted_pages}")
    print(f"education={len(resume_state.education)}")
    print(f"experience={len(resume_state.experience)}")
    print(f"projects={len(resume_state.projects)}")
    print(f"skills={len(resume_state.skills)}")
    print(f"evidence_spans={len(resume_state.original_evidence_spans)}")
    print("normalized_base_resume_preview:")
    print(resume_state.normalized_base_resume[:1000])


if __name__ == "__main__":
    main()
