"""Load a small LinkedIn JD sample into the jobs table.

Day 2 scope only:
CSV sample -> DeepSeek field extraction -> upsert into jobs.

Day 3 will add field-aware chunking, embeddings, and job_chunks writes.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings
from app.llm.deepseek import chat
from app.llm.qwen_embed import embed_texts


SYSTEM_PROMPT = """You extract structured metadata from LinkedIn job postings.
Return only valid JSON. Do not invent facts that are not supported by the JD.

Schema:
{
  "visa_sponsor": true | false | null,
  "degree_required": "none" | "high_school" | "associate" | "bachelor" |
    "master" | "phd" | "unknown",
  "min_years_exp": integer | null,
  "role_cluster": "software_engineering" | "data_ai" | "product_management" |
    "marketing_sales" | "healthcare" | "legal" | "education" | "operations" |
    "finance" | "customer_support" | "other",
  "responsibilities": string,
  "required_skills": [string],
  "nice_to_have": [string]
}

Rules:
- Keep responsibilities concise but evidence-based.
- Use null for unknown visa sponsorship or years of experience.
- Put required hard skills in required_skills; put optional tools/traits in nice_to_have.
- Normalize skill names, for example "Python", "SQL", "Project Management".
"""


@dataclass(frozen=True)
class ParsedJob:
    job_id: str
    title: str | None
    company: str | None
    location: str | None
    visa_sponsor: bool | None
    degree_required: str | None
    min_years_exp: int | None
    role_cluster: str | None
    is_open: bool
    deadline: date | None
    responsibilities: str | None
    required_skills: list[str]
    nice_to_have: list[str]
    raw_jd: str


@dataclass(frozen=True)
class JobChunk:
    chunk_id: str
    job_id: str
    field: str
    content: str
    embedding: list[float]


def _nonempty(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null", "<na>"}:
        return None
    return text


def _parse_date_from_epoch(value: Any) -> date | None:
    text = _nonempty(value)
    if text is None:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if number <= 0:
        return None
    # LinkedIn timestamps in this dataset are milliseconds since epoch.
    seconds = number / 1000 if number > 10_000_000_000 else number
    try:
        return datetime.fromtimestamp(seconds, tz=UTC).date()
    except (OSError, OverflowError, ValueError):
        return None


def _clean_string_list(value: Any, *, max_items: int = 20) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _nonempty(item)
        if text is None:
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


def _normalize_degree(value: Any) -> str:
    text = _nonempty(value)
    if text is None:
        return "unknown"
    normalized = text.casefold().replace("-", "_").replace(" ", "_")
    if normalized in {"none", "no_degree", "not_required"}:
        return "none"
    if normalized in {"high_school", "highschool", "secondary"}:
        return "high_school"
    if normalized in {"associate", "associates", "associate_degree"}:
        return "associate"
    if normalized in {"bachelor", "bachelors", "bs", "ba", "undergraduate"}:
        return "bachelor"
    if normalized in {"master", "masters", "ms", "ma", "mba"}:
        return "master"
    if normalized in {"phd", "ph.d.", "doctorate", "doctoral"}:
        return "phd"
    if normalized in {"unknown", "unspecified", "not_specified"}:
        return "unknown"
    return "unknown"


def _normalize_role_cluster(value: Any) -> str:
    text = _nonempty(value)
    valid = {
        "software_engineering",
        "data_ai",
        "product_management",
        "marketing_sales",
        "healthcare",
        "legal",
        "education",
        "operations",
        "finance",
        "customer_support",
        "other",
    }
    return text if text in valid else "other"


def _extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return json.loads(stripped)


def _build_user_prompt(row: dict[str, str]) -> str:
    fields = {
        "job_id": _nonempty(row.get("job_id")),
        "title": _nonempty(row.get("title")),
        "company_name": _nonempty(row.get("company_name")),
        "location": _nonempty(row.get("location")),
        "work_type": _nonempty(row.get("formatted_work_type")) or _nonempty(row.get("work_type")),
        "experience_level": _nonempty(row.get("formatted_experience_level")),
        "skills_desc": _nonempty(row.get("skills_desc")),
        "description": (_nonempty(row.get("description")) or "")[:7000],
    }
    return json.dumps(fields, ensure_ascii=False, indent=2)


async def _parse_with_deepseek(row: dict[str, str], index: int, total: int) -> dict[str, Any]:
    prompt = _build_user_prompt(row)
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            raw = await chat(SYSTEM_PROMPT, prompt, temperature=0.0, json_mode=True)
            parsed = _extract_json(raw)
            print(f"[{index:02d}/{total}] parsed job_id={row.get('job_id')}")
            return parsed
        except Exception as exc:  # noqa: BLE001 - preserve progress for batch loading
            last_error = exc
            await asyncio.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"DeepSeek parse failed for job_id={row.get('job_id')}: {last_error}") from last_error


def _to_parsed_job(row: dict[str, str], extracted: dict[str, Any]) -> ParsedJob:
    job_id = _nonempty(row.get("job_id"))
    if job_id is None:
        raise ValueError("row missing job_id")

    closed_time = _nonempty(row.get("closed_time"))
    raw_jd = _nonempty(row.get("description")) or ""
    responsibilities = _nonempty(extracted.get("responsibilities"))

    years = extracted.get("min_years_exp")
    min_years_exp = years if isinstance(years, int) and years >= 0 else None

    visa = extracted.get("visa_sponsor")
    visa_sponsor = visa if isinstance(visa, bool) else None

    return ParsedJob(
        job_id=job_id,
        title=_nonempty(row.get("title")),
        company=_nonempty(row.get("company_name")),
        location=_nonempty(row.get("location")),
        visa_sponsor=visa_sponsor,
        degree_required=_normalize_degree(extracted.get("degree_required")),
        min_years_exp=min_years_exp,
        role_cluster=_normalize_role_cluster(extracted.get("role_cluster")),
        is_open=closed_time is None,
        deadline=_parse_date_from_epoch(row.get("expiry")),
        responsibilities=responsibilities,
        required_skills=_clean_string_list(extracted.get("required_skills")),
        nice_to_have=_clean_string_list(extracted.get("nice_to_have")),
        raw_jd=raw_jd,
    )


async def _upsert_jobs(jobs: list[ParsedJob]) -> None:
    conn = await asyncpg.connect(settings.database_url)
    try:
        await conn.executemany(
            """
            INSERT INTO jobs (
                job_id, title, company, location, visa_sponsor,
                degree_required, min_years_exp, role_cluster, is_open,
                deadline, responsibilities, required_skills, nice_to_have, raw_jd
            )
            VALUES (
                $1, $2, $3, $4, $5,
                $6, $7, $8, $9,
                $10::date, $11, $12::text[], $13::text[], $14
            )
            ON CONFLICT (job_id) DO UPDATE SET
                title = EXCLUDED.title,
                company = EXCLUDED.company,
                location = EXCLUDED.location,
                visa_sponsor = EXCLUDED.visa_sponsor,
                degree_required = EXCLUDED.degree_required,
                min_years_exp = EXCLUDED.min_years_exp,
                role_cluster = EXCLUDED.role_cluster,
                is_open = EXCLUDED.is_open,
                deadline = EXCLUDED.deadline,
                responsibilities = EXCLUDED.responsibilities,
                required_skills = EXCLUDED.required_skills,
                nice_to_have = EXCLUDED.nice_to_have,
                raw_jd = EXCLUDED.raw_jd
            """,
            [
                (
                    job.job_id,
                    job.title,
                    job.company,
                    job.location,
                    job.visa_sponsor,
                    job.degree_required,
                    job.min_years_exp,
                    job.role_cluster,
                    job.is_open,
                    job.deadline,
                    job.responsibilities,
                    job.required_skills,
                    job.nice_to_have,
                    job.raw_jd,
                )
                for job in jobs
            ],
        )
    finally:
        await conn.close()


def _read_rows(path: Path, limit: int) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [
            row
            for row in reader
            if _nonempty(row.get("job_id"))
            and _nonempty(row.get("title"))
            and _nonempty(row.get("description"))
        ]
    return rows[:limit]


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in vector) + "]"


def _compact_text(value: Any) -> str | None:
    text = _nonempty(value)
    if text is None:
        return None
    return " ".join(text.split())


def _split_long_text(text: str, *, max_chars: int = 1800) -> list[str]:
    compact = _compact_text(text)
    if compact is None:
        return []
    if len(compact) <= max_chars:
        return [compact]

    parts: list[str] = []
    current = ""
    for paragraph in compact.replace(". ", ".\n").splitlines():
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(current) + len(paragraph) + 1 <= max_chars:
            current = f"{current} {paragraph}".strip()
            continue
        if current:
            parts.append(current)
        current = paragraph[:max_chars]
    if current:
        parts.append(current)
    return parts


def _format_list(values: list[str] | None) -> str | None:
    if not values:
        return None
    cleaned = [value for value in values if _compact_text(value)]
    return ", ".join(cleaned) if cleaned else None


def _build_chunk_specs(row: asyncpg.Record) -> list[tuple[str, str]]:
    specs: list[tuple[str, str]] = []

    title_bits = [
        f"Title: {row['title']}" if row["title"] else None,
        f"Company: {row['company']}" if row["company"] else None,
        f"Location: {row['location']}" if row["location"] else None,
        f"Role cluster: {row['role_cluster']}" if row["role_cluster"] else None,
        f"Degree: {row['degree_required']}" if row["degree_required"] else None,
        f"Minimum years experience: {row['min_years_exp']}" if row["min_years_exp"] is not None else None,
    ]
    title_content = " | ".join(bit for bit in title_bits if bit)
    if title_content:
        specs.append(("metadata", title_content))

    responsibilities = _compact_text(row["responsibilities"])
    if responsibilities:
        specs.append(("responsibilities", f"Responsibilities: {responsibilities}"))

    required_skills = _format_list(row["required_skills"])
    if required_skills:
        specs.append(("required_skills", f"Required skills: {required_skills}"))

    nice_to_have = _format_list(row["nice_to_have"])
    if nice_to_have:
        specs.append(("nice_to_have", f"Nice to have: {nice_to_have}"))

    for index, raw_part in enumerate(_split_long_text(row["raw_jd"]), start=1):
        specs.append((f"raw_jd_{index}", f"Job description excerpt: {raw_part}"))

    return specs


async def _fetch_jobs_for_chunking(limit: int) -> list[asyncpg.Record]:
    conn = await asyncpg.connect(settings.database_url)
    try:
        return await conn.fetch(
            """
            SELECT
                job_id, title, company, location, degree_required, min_years_exp,
                role_cluster, responsibilities, required_skills, nice_to_have, raw_jd
            FROM jobs
            ORDER BY job_id
            LIMIT $1
            """,
            limit,
        )
    finally:
        await conn.close()


async def _embed_specs(specs: list[tuple[str, str]], batch_size: int) -> list[list[float]]:
    embeddings: list[list[float]] = []
    for start in range(0, len(specs), batch_size):
        batch = specs[start : start + batch_size]
        vectors = await embed_texts([content for _, content in batch])
        for vector in vectors:
            if len(vector) != settings.embed_dim:
                raise ValueError(
                    f"Embedding dimension mismatch: got {len(vector)}, expected {settings.embed_dim}"
                )
        embeddings.extend(vectors)
        print(f"embedded chunks {min(start + batch_size, len(specs))}/{len(specs)}")
    return embeddings


async def build_job_chunks(limit: int, batch_size: int) -> int:
    rows = await _fetch_jobs_for_chunking(limit)
    if not rows:
        raise ValueError("No jobs found. Run Day 2 job loading first.")

    chunk_inputs: list[tuple[str, str, str, str]] = []
    for row in rows:
        for index, (field, content) in enumerate(_build_chunk_specs(row), start=1):
            chunk_id = f"{row['job_id']}:{field}:{index}"
            chunk_inputs.append((chunk_id, row["job_id"], field, content))

    if not chunk_inputs:
        raise ValueError("No chunks generated from jobs table.")

    embeddings = await _embed_specs(
        [(chunk_id, content) for chunk_id, _, _, content in chunk_inputs],
        batch_size=batch_size,
    )

    records = [
        (
            chunk_id,
            job_id,
            field,
            content,
            _vector_literal(embedding),
        )
        for (chunk_id, job_id, field, content), embedding in zip(chunk_inputs, embeddings, strict=True)
    ]

    conn = await asyncpg.connect(settings.database_url)
    try:
        async with conn.transaction():
            await conn.execute(
                "DELETE FROM job_chunks WHERE job_id = ANY($1::text[])",
                [row["job_id"] for row in rows],
            )
            await conn.executemany(
                """
                INSERT INTO job_chunks (chunk_id, job_id, field, content, embedding, tsv)
                VALUES ($1, $2, $3, $4, $5::vector, to_tsvector('english', $4))
                ON CONFLICT (chunk_id) DO UPDATE SET
                    field = EXCLUDED.field,
                    content = EXCLUDED.content,
                    embedding = EXCLUDED.embedding,
                    tsv = EXCLUDED.tsv
                """,
                records,
            )
    finally:
        await conn.close()

    return len(records)


async def load_jobs(path: Path, limit: int) -> int:
    rows = _read_rows(path, limit)
    if not rows:
        raise ValueError(f"No loadable rows found in {path}")

    total = len(rows)
    parsed_jobs: list[ParsedJob] = []
    tasks = [
        _parse_with_deepseek(row, index=index, total=total)
        for index, row in enumerate(rows, start=1)
    ]
    extracted_payloads = await asyncio.gather(*tasks)
    for row, extracted in zip(rows, extracted_payloads, strict=True):
        parsed_jobs.append(_to_parsed_job(row, extracted))

    await _upsert_jobs(parsed_jobs)
    return len(parsed_jobs)


def main() -> None:
    parser = argparse.ArgumentParser(description="Load LinkedIn JD sample into jobs table.")
    parser.add_argument(
        "--stage",
        choices=["jobs", "chunks", "all"],
        default="jobs",
        help="jobs=DeepSeek parse into jobs; chunks=Qwen embeddings into job_chunks; all=both.",
    )
    parser.add_argument(
        "--input",
        default="data/jobs/linkedin_postings_50.csv",
        type=Path,
        help="CSV file containing LinkedIn job postings.",
    )
    parser.add_argument("--limit", default=50, type=int, help="Number of rows to parse.")
    parser.add_argument("--embed-batch-size", default=10, type=int, help="Qwen embedding batch size.")
    args = parser.parse_args()

    if args.stage in {"jobs", "all"}:
        count = asyncio.run(load_jobs(args.input, args.limit))
        print(f"Inserted/updated {count} jobs into jobs table.")
    if args.stage in {"chunks", "all"}:
        count = asyncio.run(build_job_chunks(args.limit, args.embed_batch_size))
        print(f"Inserted/updated {count} chunks into job_chunks table.")


if __name__ == "__main__":
    main()
