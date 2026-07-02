from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.pool import close_pool
from app.db.state_store import save_state as save_shared_state
from app.normalization.resume_intake import ResumeIntakeResult, intake_resume
from app.retrieval.hybrid_search import JobCandidate, hybrid_search
from app.retrieval.query_builder import build_resume_retrieval_query


@dataclass(frozen=True)
class Week1PipelineResult:
    resume_result: ResumeIntakeResult
    candidates: list[JobCandidate]


def _parse_json_object(raw: str | None, *, label: str) -> dict[str, Any]:
    if not raw:
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} must be a JSON object")
    return parsed


def _write_retrieval_state(result: ResumeIntakeResult, candidates: list[JobCandidate]) -> None:
    evidence_ids: list[str] = []
    seen_evidence: set[str] = set()
    ranking_scores: list[dict[str, Any]] = []

    for candidate in candidates:
        ranking_scores.append(
            {
                "job_id": candidate.job_id,
                "score": candidate.score,
                "rrf_score": candidate.rrf_score,
                "bm25_score": candidate.bm25_score,
                "dense_score": candidate.dense_score,
                "raptor_score": candidate.raptor_score,
                "field_bonus": candidate.field_bonus,
                "sources": list(candidate.sources),
                "evidence_span_ids": list(candidate.evidence_span_ids),
            }
        )
        for evidence_id in candidate.evidence_span_ids:
            if evidence_id in seen_evidence:
                continue
            seen_evidence.add(evidence_id)
            evidence_ids.append(evidence_id)

    retrieval_state = result.state.retrieval_state
    retrieval_state.candidate_job_ids = [candidate.job_id for candidate in candidates]
    retrieval_state.ranking_scores = ranking_scores
    retrieval_state.evidence_span_ids = evidence_ids


async def run_pipeline(
    *,
    resume_path: Path,
    session_id: str,
    user_id: str,
    top_k: int,
    hard_constraints: dict[str, Any] | None = None,
    soft_prefs: dict[str, Any] | None = None,
    save_state: bool = True,
) -> Week1PipelineResult:
    try:
        resume_result = await intake_resume(
            resume_path,
            session_id=session_id,
            user_id=user_id,
            save_to_db=save_state,
        )
        query = build_resume_retrieval_query(resume_result.state.resume_state).text.strip()
        if not query:
            raise ValueError("Resume normalization returned an empty normalized_base_resume")

        candidates = await hybrid_search(
            query=query,
            hard_constraints=hard_constraints or {},
            soft_prefs=soft_prefs or {},
            top_k=top_k,
        )
        _write_retrieval_state(resume_result, candidates)
        if save_state:
            await save_shared_state(resume_result.state, status="retrieval_done")
        return Week1PipelineResult(
            resume_result=resume_result,
            candidates=candidates,
        )
    finally:
        await close_pool()


def format_result(result: Week1PipelineResult) -> str:
    resume_state = result.resume_result.state.resume_state
    lines = [
        "Resume normalization",
        f"session_id: {result.resume_result.state.session_id}",
        f"pages: {result.resume_result.extracted_pages}",
        f"education: {len(resume_state.education)}",
        f"experience: {len(resume_state.experience)}",
        f"projects: {len(resume_state.projects)}",
        f"skills: {len(resume_state.skills)}",
        f"evidence_spans: {len(resume_state.original_evidence_spans)}",
        "",
        "Normalized base resume preview",
        resume_state.normalized_base_resume[:700],
        "",
        "Top-K matches",
        (
            "rank\tjob_id\tscore\trrf\tbm25\tdense\traptor\tfield_bonus\tsources\t"
            "title\tcompany\tlocation\tevidence"
        ),
    ]

    for rank, candidate in enumerate(result.candidates, start=1):
        evidence = ",".join(candidate.evidence_span_ids)
        sources = ",".join(candidate.sources)
        lines.append(
            f"{rank}\t{candidate.job_id}\t{candidate.score:.6f}\t"
            f"{candidate.rrf_score:.6f}\t{candidate.bm25_score:.6f}\t"
            f"{candidate.dense_score:.6f}\t{candidate.raptor_score:.6f}\t"
            f"{candidate.field_bonus:.6f}\t"
            f"{sources}\t"
            f"{candidate.title or ''}\t{candidate.company or ''}\t"
            f"{candidate.location or ''}\t{evidence}"
        )

    if not result.candidates:
        lines.append("(no matches)")

    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Week1 end-to-end CLI: resume file -> DeepSeek normalization -> "
            "hybrid retrieval -> Top-K job matches."
        )
    )
    parser.add_argument("resume_path", type=Path)
    parser.add_argument("--session-id", default="week1-demo-session")
    parser.add_argument("--user-id", default="week1-demo-user")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--hard-constraints",
        help='JSON object for SQL filters, e.g. {"location":"London"}',
    )
    parser.add_argument(
        "--soft-prefs",
        help='JSON object for ranking preferences, e.g. {"title_keywords":["data"]}',
    )
    parser.add_argument(
        "--no-save-state",
        action="store_true",
        help="Do not persist the normalized resume state to PostgreSQL.",
    )
    return parser


async def _main_async(args: argparse.Namespace) -> None:
    result = await run_pipeline(
        resume_path=args.resume_path,
        session_id=args.session_id,
        user_id=args.user_id,
        top_k=args.top_k,
        hard_constraints=_parse_json_object(
            args.hard_constraints, label="--hard-constraints"
        ),
        soft_prefs=_parse_json_object(args.soft_prefs, label="--soft-prefs"),
        save_state=not args.no_save_state,
    )
    print(format_result(result))


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
