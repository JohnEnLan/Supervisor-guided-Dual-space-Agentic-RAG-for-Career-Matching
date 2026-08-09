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
import io
import json
import re
from pathlib import Path
from typing import Any, Literal

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from pydantic import BaseModel, Field
from pypdf import PdfReader

from app.config import settings
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
  "contact": {
    "name": string,
    "phone": string,
    "email": string,
    "evidence_span_ids": [string]
  },
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
      "field_path": string (the closest path such as "experience[0]"),
      "evidence_span_ids": [string]
    }
  ],
  "normalized_base_resume": string
}

Rules:
- Copy each non-empty contact field verbatim from one cited evidence span.
- Use one shared evidence_span_ids list for the contact object.
- Keep normalized_base_resume concise and query-friendly.
- Preserve real names of schools, employers, projects, tools, and measurable outcomes.
- Copy institutions, organizations, project names, job titles, dates, and locations
  verbatim from the evidence spans — never reformat dates or rephrase names.
- Internships, part-time jobs, and research/teaching assistant roles are experience.
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
    source: Literal["resume", "user_clarification"] = "resume"


class LLMResumePayload(BaseModel):
    contact: dict[str, Any] = Field(default_factory=dict)
    education: list[dict[str, Any]] = Field(default_factory=list)
    experience: list[dict[str, Any]] = Field(default_factory=list)
    projects: list[dict[str, Any]] = Field(default_factory=list)
    skills: list[dict[str, Any] | str] = Field(default_factory=list)
    resume_quality_issues: list[dict[str, Any] | str] = Field(default_factory=list)
    normalized_base_resume: str = ""


_QUALITY_SEVERITIES = frozenset({"low", "medium", "high"})
_MIN_CLARIFICATION_DESCRIPTION_CHARS = 12


class ResumeIntakeUserError(ValueError):
    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message


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


def _extract_pdf_pages(
    path: "Path | io.BytesIO",
) -> tuple[list[tuple[int, str]], int]:
    reader = PdfReader(path if isinstance(path, io.BytesIO) else str(path))
    pages = [
        (page_number, page.extract_text() or "")
        for page_number, page in enumerate(reader.pages, start=1)
    ]
    return pages, len(reader.pages)


def extract_resume_pages_from_bytes(
    content: bytes,
    suffix: str,
) -> tuple[list[tuple[int, str]], int]:
    if suffix.casefold() != ".pdf":
        raise ValueError(f"Unsupported resume file type: {suffix}")
    return _extract_pdf_pages(io.BytesIO(content))


def join_pdf_pages(pages: list[tuple[int, str]]) -> str:
    page_texts: list[str] = []
    for page_number, raw_text in pages:
        text = _compact_text(raw_text)
        if text:
            page_texts.append(f"[Page {page_number}]\n{text}")
    return "\n\n".join(page_texts).strip()


def _read_pdf(path: "Path | io.BytesIO") -> tuple[str, int]:
    pages, total_pages = _extract_pdf_pages(path)
    return join_pdf_pages(pages), total_pages


def _read_docx(path: "Path | io.BytesIO") -> tuple[str, int]:
    doc = Document(path if isinstance(path, io.BytesIO) else str(path))
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


def extract_resume_text_from_bytes(content: bytes, suffix: str) -> tuple[str, int]:
    """B2 上传确认流：上传即在内存中本地提取（零 LLM），不落磁盘。"""
    normalized_suffix = suffix.casefold()
    if normalized_suffix == ".pdf":
        return _read_pdf(io.BytesIO(content))
    if normalized_suffix == ".docx":
        return _read_docx(io.BytesIO(content))
    if normalized_suffix in {".txt", ".md"}:
        for encoding in ("utf-8-sig", "utf-8", "gbk"):
            try:
                return _compact_text(content.decode(encoding)), 1
            except UnicodeDecodeError:
                continue
        return _compact_text(content.decode(errors="ignore")), 1
    raise ValueError(f"Unsupported resume file type: {suffix}")


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


def build_clarification_targets(
    *,
    quality_issues: list[dict[str, Any]],
    experience: list[dict[str, Any]],
    projects: list[dict[str, Any]],
    max_targets: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Normalize quality signals and choose deterministic Feature-A targets."""
    normalized_issues = [
        _normalize_quality_issue(value, index=index)
        for index, value in enumerate(quality_issues)
        if isinstance(value, dict)
    ]
    candidates: list[dict[str, Any]] = []

    for issue in sorted(
        normalized_issues,
        key=lambda item: 0 if item["severity"] == "high" else 1,
    ):
        if issue["severity"] not in {"high", "medium"}:
            continue
        candidates.append(_clarification_target_from_issue(issue))

    for index, item in enumerate(experience):
        if not isinstance(item, dict):
            continue
        missing_fields = [
            label
            for field_name, label in (
                ("responsibilities", "职责"),
                ("achievements", "成果"),
            )
            if _description_is_too_short(item.get(field_name))
        ]
        if missing_fields:
            field_path = f"experience[{index}]"
            candidates.append(
                _new_clarification_target(
                    field_path=field_path,
                    severity="medium",
                    issue=f"该段经历缺少充分的{'/'.join(missing_fields)}描述",
                    evidence_span_ids=item.get("evidence_span_ids"),
                )
            )

    for index, item in enumerate(projects):
        if not isinstance(item, dict):
            continue
        linked_skills = _clean_string_list(
            [
                *(
                    item.get("technologies")
                    if isinstance(item.get("technologies"), list)
                    else []
                ),
                *(
                    item.get("skills")
                    if isinstance(item.get("skills"), list)
                    else []
                ),
            ]
        )
        if not linked_skills:
            field_path = f"projects[{index}]"
            candidates.append(
                _new_clarification_target(
                    field_path=field_path,
                    severity="medium",
                    issue="该项目没有关联所使用的技能或技术",
                    evidence_span_ids=item.get("evidence_span_ids"),
                )
            )

    selected: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for candidate in candidates:
        field_path = candidate["field_path"]
        if field_path in seen_paths:
            continue
        seen_paths.add(field_path)
        selected.append(candidate)
        if len(selected) >= max(0, int(max_targets)):
            break
    return normalized_issues, selected


def _normalize_quality_issue(
    value: dict[str, Any], *, index: int
) -> dict[str, Any]:
    normalized = dict(value)
    severity = str(value.get("severity") or "medium").strip().casefold()
    normalized["severity"] = (
        severity if severity in _QUALITY_SEVERITIES else "medium"
    )
    normalized["issue"] = str(value.get("issue") or "").strip()
    field_path = str(value.get("field_path") or "").strip()
    normalized["field_path"] = field_path or f"resume_quality_issues[{index}]"
    normalized["evidence_span_ids"] = _clean_string_list(
        value.get("evidence_span_ids"),
        max_items=20,
    )
    return normalized


def _clarification_target_from_issue(issue: dict[str, Any]) -> dict[str, Any]:
    return _new_clarification_target(
        field_path=issue["field_path"],
        severity=issue["severity"],
        issue=issue["issue"],
        evidence_span_ids=issue.get("evidence_span_ids"),
    )


def _new_clarification_target(
    *,
    field_path: str,
    severity: str,
    issue: str,
    evidence_span_ids: Any,
) -> dict[str, Any]:
    return {
        "target_ref": field_path,
        "field_path": field_path,
        "status": "open",
        "severity": severity,
        "issue": issue,
        "evidence_span_ids": _clean_string_list(
            evidence_span_ids,
            max_items=20,
        ),
    }


def _description_is_too_short(value: Any) -> bool:
    text = "".join(_clean_string_list(value))
    return len(re.sub(r"\s+", "", text)) < _MIN_CLARIFICATION_DESCRIPTION_CHARS


def _validated_span_ids(values: Any, valid_ids: set[str]) -> list[str]:
    if not isinstance(values, list):
        return []
    result: list[str] = []
    for value in values:
        span_id = str(value).strip()
        if span_id in valid_ids and span_id not in result:
            result.append(span_id)
    return result


_CONTACT_FIELDS = ("name", "phone", "email")


def _exact_substring_is_supported(
    value: str,
    evidence_span_ids: list[str],
    evidence_text_by_id: dict[str, str],
) -> bool:
    return bool(value) and any(
        value in evidence_text_by_id[span_id]
        for span_id in evidence_span_ids
        if span_id in evidence_text_by_id
    )


def _validated_contact(
    value: Any,
    valid_ids: set[str],
    evidence_text_by_id: dict[str, str],
) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        return {}

    evidence_span_ids = _validated_span_ids(
        value.get("evidence_span_ids"),
        valid_ids,
    )
    contact = {
        field_name: field_value
        if isinstance(field_value := value.get(field_name), str)
        and _exact_substring_is_supported(
            field_value,
            evidence_span_ids,
            evidence_text_by_id,
        )
        else ""
        for field_name in _CONTACT_FIELDS
    }
    supported_span_ids = [
        span_id
        for span_id in evidence_span_ids
        if any(
            _exact_substring_is_supported(
                contact[field_name],
                [span_id],
                evidence_text_by_id,
            )
            for field_name in _CONTACT_FIELDS
        )
    ]
    if not any(contact.values()):
        supported_span_ids = []
    return {
        **contact,
        "evidence_span_ids": supported_span_ids,
    }


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
        if (
            reject_unsupported
            and not supported
            and not _identity_is_supported(
                value,
                evidence_span_ids,
                evidence_text_by_id,
            )
        ):
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


_IDENTITY_FIELDS = ("institution", "organization", "name", "title")


def _identity_is_supported(
    value: dict[str, Any],
    evidence_span_ids: list[str],
    evidence_text_by_id: dict[str, str],
) -> bool:
    """条目的身份锚点（校名/公司/项目名/职位）至少一个能逐字对上证据。

    锚点在证据里 → 条目是真实经历的规范化改写（保留并标记 unverified，
    避免日期重排、措辞润色导致整条真实经历被丢弃）；
    锚点全对不上 → 条目无法追溯到任何证据，按编造处理（丢弃）。
    """
    claims = [
        text
        for field_name in _IDENTITY_FIELDS
        if (text := str(value.get(field_name) or "").strip())
    ]
    return any(
        _claim_is_supported(
            claim,
            evidence_span_ids,
            evidence_text_by_id,
        )
        for claim in claims
    )


def _claim_strings(value: Any, *, field_name: str | None = None) -> list[str]:
    if field_name in {
        "evidence_span_ids",
        "severity",
        "verification_status",
        "field_path",
        "target_ref",
    }:
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


def _normalization_system_prompt() -> str:
    if settings.resume_clarify_enabled:
        return SYSTEM_PROMPT
    return "\n".join(
        line for line in SYSTEM_PROMPT.splitlines() if '"field_path":' not in line
    )


async def normalize_resume_text(raw_text: str, evidence_spans: list[EvidenceSpan]) -> ResumeState:
    raw = await chat(
        _normalization_system_prompt(),
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
    contact = _validated_contact(
        parsed.contact,
        valid_ids,
        evidence_text_by_id,
    )
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
    quality_issues_struct: list[dict[str, Any]] = []
    clarification_targets: list[dict[str, Any]] = []
    if settings.resume_clarify_enabled:
        # Feature A is a runtime-gated augmentation. With the switch off,
        # normalization keeps the pre-5B side effects and all A fields empty.
        quality_issues_struct, clarification_targets = build_clarification_targets(
            quality_issues=quality_issues,
            experience=experience,
            projects=projects,
            max_targets=settings.resume_clarify_max,
        )
    return ResumeState(
        contact=contact,
        education=education,
        experience=experience,
        projects=projects,
        skills=_validated_skills(
            parsed.skills,
            valid_ids,
            evidence_text_by_id,
        ),
        resume_quality_issues=_normalize_quality_issues(quality_issues),
        quality_issues_struct=quality_issues_struct,
        original_evidence_spans=[span.model_dump() for span in evidence_spans],
        normalized_base_resume=_compact_text(
            "\n".join(span.text for span in evidence_spans)
        ),
        clarification_targets=clarification_targets,
    )


async def intake_resume(
    path: Path,
    *,
    session_id: str,
    user_id: str,
    save_to_db: bool = False,
) -> ResumeIntakeResult:
    # Offloading a blocking parser with asyncio.to_thread is the idiomatic
    # asyncio boundary; it does not replace the project's asyncio concurrency model.
    raw_text, page_count = await asyncio.to_thread(extract_resume_text, path)
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
