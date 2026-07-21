from __future__ import annotations

import argparse
import asyncio
import json
import re
from dataclasses import dataclass, field as dataclass_field
from typing import Any

from app.config import settings
from app.db.pool import close_pool, get_pool
from app.db.state_store import load_state
from app.llm.qwen_embed import embed_one
from app.retrieval.query_builder import build_resume_retrieval_query
from app.retrieval.raptor import search_raptor_nodes
from app.retrieval.rrf import rrf_fuse


BM25_STOPWORDS = {
    "about",
    "above",
    "after",
    "again",
    "against",
    "also",
    "among",
    "and",
    "at",
    "been",
    "being",
    "below",
    "between",
    "both",
    "china",
    "could",
    "degree",
    "direction",
    "does",
    "doing",
    "during",
    "each",
    "experience",
    "education",
    "has",
    "english",
    "en",
    "from",
    "have",
    "includes",
    "in",
    "into",
    "john",
    "location",
    "minor",
    "of",
    "other",
    "present",
    "project",
    "projects",
    "course",
    "resume",
    "school",
    "skills",
    "student",
    "than",
    "that",
    "their",
    "there",
    "these",
    "they",
    "this",
    "through",
    "university",
    "with",
    "would",
    "years",
    "zhang",
}

FIELD_AWARE_BONUS = {
    "required_skills": 0.06,
    "responsibilities": 0.04,
    "nice_to_have": 0.025,
    "metadata": 0.02,
}
MAX_FIELD_BONUS = 0.08


@dataclass(frozen=True)
class ChunkHit:
    job_id: str
    chunk_id: str
    score: float
    field: str | None = None


@dataclass(frozen=True)
class JobRank:
    job_id: str
    score: float
    evidence_span_ids: list[str]
    evidence_fields: list[str]


@dataclass(frozen=True)
class JobCandidate:
    job_id: str
    score: float
    evidence_span_ids: list[str]
    evidence_spans: list[dict[str, Any]] = dataclass_field(default_factory=list)
    title: str | None = None
    company: str | None = None
    location: str | None = None
    role_cluster: str | None = None
    rrf_score: float = 0.0
    bm25_score: float = 0.0
    dense_score: float = 0.0
    raptor_score: float = 0.0
    field_bonus: float = 0.0
    sources: list[str] = dataclass_field(default_factory=list)
    explicit_score: float = 0.0
    implicit_score: float = 0.0
    implicit_confidence: float = 0.0
    implicit_evidence: list[dict[str, Any]] = dataclass_field(default_factory=list)


def _build_hard_filter_query(hard_constraints: dict[str, Any]) -> tuple[str, list[Any]]:
    clauses = ["is_open = TRUE"]
    params: list[Any] = []

    def add_param(value: Any) -> str:
        params.append(value)
        return f"${len(params)}"

    location = hard_constraints.get("location")
    locations = hard_constraints.get("locations")
    if location:
        placeholder = add_param(location)
        clauses.append(f"location = {placeholder}")
    elif locations:
        placeholder = add_param(list(locations))
        clauses.append(f"location = ANY({placeholder}::text[])")

    if hard_constraints.get("need_visa_sponsor"):
        clauses.append("visa_sponsor = TRUE")

    max_years_exp = hard_constraints.get("max_years_exp")
    if max_years_exp is not None:
        placeholder = add_param(int(max_years_exp))
        clauses.append(f"(min_years_exp IS NULL OR min_years_exp <= {placeholder})")

    role_cluster = hard_constraints.get("role_cluster")
    role_clusters = hard_constraints.get("role_clusters")
    if role_cluster:
        placeholder = add_param(role_cluster)
        clauses.append(f"role_cluster = {placeholder}")
    elif role_clusters:
        placeholder = add_param(list(role_clusters))
        clauses.append(f"role_cluster = ANY({placeholder}::text[])")

    degree_required = hard_constraints.get("degree_required")
    if degree_required:
        placeholder = add_param(degree_required)
        clauses.append(f"degree_required = {placeholder}")

    companies = [
        str(company).casefold()
        for company in hard_constraints.get("companies") or []
        if str(company).strip()
    ]
    if companies:
        placeholder = add_param(companies)
        clauses.append(f"lower(company) = ANY({placeholder}::text[])")

    sql = f"SELECT job_id FROM jobs WHERE {' AND '.join(clauses)}"
    return sql, params


async def _hard_filter_ids(pool, hard_constraints: dict[str, Any]) -> list[str]:
    sql, params = _build_hard_filter_query(hard_constraints)
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return [str(row["job_id"]) for row in rows]


async def _bm25(pool, query: str, allow_ids: list[str], k: int) -> list[ChunkHit]:
    if not allow_ids:
        return []
    bm25_query = _prepare_bm25_tsquery(query)
    if not bm25_query:
        return []

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            WITH bm25_query AS (
                SELECT to_tsquery('english', $1) AS tsq
            )
            SELECT chunk_id,
                   job_id,
                   field,
                   ts_rank_cd(tsv, bm25_query.tsq) AS score
            FROM job_chunks, bm25_query
            WHERE job_id = ANY($2::text[])
              AND tsv @@ bm25_query.tsq
            ORDER BY score DESC
            LIMIT $3
            """,
            bm25_query,
            allow_ids,
            k,
        )
    return [
        ChunkHit(
            job_id=str(row["job_id"]),
            chunk_id=str(row["chunk_id"]),
            score=float(row["score"] or 0.0),
            field=row["field"],
        )
        for row in rows
    ]


def _prepare_bm25_tsquery(query: str, *, max_terms: int = 32) -> str:
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9]{1,}", query.casefold())
    terms: list[str] = []
    seen: set[str] = set()

    for token in tokens:
        if token in seen or token in BM25_STOPWORDS:
            continue
        seen.add(token)
        terms.append(token)
        if len(terms) >= max_terms:
            break

    return " | ".join(f"{term}:*" for term in terms)


def _to_vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{float(value):.10g}" for value in values) + "]"


async def _dense(pool, query: str, allow_ids: list[str], k: int) -> list[ChunkHit]:
    if not allow_ids:
        return []

    query_emb = await embed_one(query)
    if len(query_emb) != settings.embed_dim:
        raise ValueError(
            f"Embedding dimension mismatch: got {len(query_emb)}, "
            f"expected {settings.embed_dim}"
        )

    query_vector = _to_vector_literal(query_emb)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT chunk_id,
                   job_id,
                   field,
                   1 - (embedding <=> $1::vector) AS score
            FROM job_chunks
            WHERE job_id = ANY($2::text[])
              AND embedding IS NOT NULL
            ORDER BY embedding <=> $1::vector
            LIMIT $3
            """,
            query_vector,
            allow_ids,
            k,
        )
    return [
        ChunkHit(
            job_id=str(row["job_id"]),
            chunk_id=str(row["chunk_id"]),
            score=float(row["score"] or 0.0),
            field=row["field"],
        )
        for row in rows
    ]


def _collapse_chunk_hits(
    hits: list[ChunkHit], max_evidence_per_job: int = 3
) -> list[JobRank]:
    grouped: dict[str, list[ChunkHit]] = {}
    for hit in hits:
        grouped.setdefault(hit.job_id, []).append(hit)

    ranks: list[JobRank] = []
    for job_id, job_hits in grouped.items():
        ordered_hits = sorted(job_hits, key=lambda item: item.score, reverse=True)
        evidence_ids = [hit.chunk_id for hit in ordered_hits[:max_evidence_per_job]]
        evidence_fields = [
            hit.field for hit in ordered_hits[:max_evidence_per_job] if hit.field
        ]
        ranks.append(
            JobRank(
                job_id=job_id,
                score=ordered_hits[0].score,
                evidence_span_ids=evidence_ids,
                evidence_fields=evidence_fields,
            )
        )
    return sorted(ranks, key=lambda item: item.score, reverse=True)


def _collapse_raptor_hits(
    hits: list[ChunkHit], max_evidence_per_job: int = 3
) -> list[JobRank]:
    grouped: dict[str, list[ChunkHit]] = {}
    for hit in hits:
        grouped.setdefault(hit.job_id, []).append(hit)

    ranks: list[JobRank] = []
    for job_id, job_hits in grouped.items():
        ordered_hits = sorted(job_hits, key=lambda item: item.score, reverse=True)
        unique_hits: list[ChunkHit] = []
        seen_chunks: set[str] = set()
        for hit in ordered_hits:
            if hit.chunk_id in seen_chunks:
                continue
            seen_chunks.add(hit.chunk_id)
            unique_hits.append(hit)

        evidence_hits = unique_hits[:max_evidence_per_job]
        ranks.append(
            JobRank(
                job_id=job_id,
                score=round(sum(max(0.0, hit.score) for hit in unique_hits), 6),
                evidence_span_ids=[hit.chunk_id for hit in evidence_hits],
                evidence_fields=[hit.field for hit in evidence_hits if hit.field],
            )
        )
    return sorted(ranks, key=lambda item: item.score, reverse=True)


def _normalise_scores(scores: dict[str, float]) -> dict[str, float]:
    if not scores:
        return {}

    values = list(scores.values())
    min_score = min(values)
    max_score = max(values)
    if max_score == min_score:
        return {key: 1.0 if value > 0 else 0.0 for key, value in scores.items()}

    scale = max_score - min_score
    return {key: (value - min_score) / scale for key, value in scores.items()}


def _soft_preference_bonus(
    metadata: dict[str, Any], soft_prefs: dict[str, Any]
) -> float:
    bonus = 0.0

    preferred_locations = set(soft_prefs.get("preferred_locations") or [])
    if metadata.get("location") in preferred_locations:
        bonus += 0.05

    preferred_role_clusters = set(soft_prefs.get("preferred_role_clusters") or [])
    if metadata.get("role_cluster") in preferred_role_clusters:
        bonus += 0.05

    preferred_companies = {
        str(company).casefold()
        for company in soft_prefs.get("preferred_companies") or []
    }
    if str(metadata.get("company") or "").casefold() in preferred_companies:
        bonus += 0.05

    title = (metadata.get("title") or "").lower()
    for keyword in soft_prefs.get("title_keywords") or []:
        if str(keyword).lower() in title:
            bonus += 0.03

    return min(bonus, 0.20)


def _rerank_candidates(
    fused: list[tuple[str, float]],
    bm25_by_job: dict[str, float],
    dense_by_job: dict[str, float],
    evidence_by_job: dict[str, list[str]],
    metadata_by_job: dict[str, dict[str, Any]],
    soft_prefs: dict[str, Any],
    top_k: int,
    field_bonus_by_job: dict[str, float] | None = None,
    raptor_by_job: dict[str, float] | None = None,
    evidence_payloads_by_job: dict[str, list[dict[str, Any]]] | None = None,
) -> list[JobCandidate]:
    rrf_by_job = dict(fused)
    normalised_rrf = _normalise_scores(rrf_by_job)
    normalised_bm25 = _normalise_scores(bm25_by_job)
    normalised_dense = _normalise_scores(dense_by_job)
    raptor_by_job = raptor_by_job or {}
    normalised_raptor = _normalise_scores(raptor_by_job)
    field_bonus_by_job = field_bonus_by_job or {}
    evidence_payloads_by_job = evidence_payloads_by_job or {}

    candidates: list[JobCandidate] = []
    for job_id, _rrf_score in fused:
        metadata = metadata_by_job.get(job_id, {})
        field_bonus = field_bonus_by_job.get(job_id, 0.0)
        semantic_score = max(
            normalised_dense.get(job_id, 0.0),
            normalised_raptor.get(job_id, 0.0),
        )
        score = (
            0.30 * normalised_rrf.get(job_id, 0.0)
            + 0.10 * normalised_bm25.get(job_id, 0.0)
            + 0.60 * semantic_score
            + _soft_preference_bonus(metadata, soft_prefs)
            + field_bonus
        )
        candidates.append(
            JobCandidate(
                job_id=job_id,
                score=round(score, 6),
                evidence_span_ids=evidence_by_job.get(job_id, []),
                evidence_spans=evidence_payloads_by_job.get(job_id, []),
                title=metadata.get("title"),
                company=metadata.get("company"),
                location=metadata.get("location"),
                role_cluster=metadata.get("role_cluster"),
                rrf_score=round(rrf_by_job.get(job_id, 0.0), 6),
                bm25_score=round(bm25_by_job.get(job_id, 0.0), 6),
                dense_score=round(dense_by_job.get(job_id, 0.0), 6),
                raptor_score=round(raptor_by_job.get(job_id, 0.0), 6),
                field_bonus=round(field_bonus, 6),
                sources=_sources_for_job(
                    job_id, bm25_by_job, dense_by_job, raptor_by_job
                ),
                explicit_score=round(score, 6),
            )
        )

    return sorted(candidates, key=lambda item: item.score, reverse=True)[:top_k]


def _sources_for_job(
    job_id: str,
    bm25_by_job: dict[str, float],
    dense_by_job: dict[str, float],
    raptor_by_job: dict[str, float] | None = None,
) -> list[str]:
    raptor_by_job = raptor_by_job or {}
    sources = []
    if bm25_by_job.get(job_id, 0.0) > 0:
        sources.append("bm25")
    if dense_by_job.get(job_id, 0.0) > 0:
        sources.append("dense")
    if raptor_by_job.get(job_id, 0.0) > 0:
        sources.append("raptor")
    return sources


def _rank_list(ranks: list[JobRank]) -> list[tuple[str, float]]:
    return [(rank.job_id, rank.score) for rank in ranks]


def _score_by_job(ranks: list[JobRank]) -> dict[str, float]:
    return {rank.job_id: rank.score for rank in ranks}


def _merge_evidence(
    job_ids: list[str],
    dense_ranks: list[JobRank],
    bm25_ranks: list[JobRank],
    raptor_ranks: list[JobRank] | None = None,
    max_evidence_per_job: int = 4,
) -> dict[str, list[str]]:
    evidence_by_job: dict[str, list[str]] = {job_id: [] for job_id in job_ids}
    ranks_by_source = [
        {rank.job_id: rank.evidence_span_ids for rank in dense_ranks},
        {rank.job_id: rank.evidence_span_ids for rank in bm25_ranks},
    ]
    if raptor_ranks:
        ranks_by_source.append(
            {rank.job_id: rank.evidence_span_ids for rank in raptor_ranks}
        )

    for job_id in job_ids:
        seen: set[str] = set()
        for source in ranks_by_source:
            for evidence_id in source.get(job_id, []):
                if evidence_id not in seen:
                    evidence_by_job[job_id].append(evidence_id)
                    seen.add(evidence_id)
                if len(evidence_by_job[job_id]) >= max_evidence_per_job:
                    break
            if len(evidence_by_job[job_id]) >= max_evidence_per_job:
                break
    return evidence_by_job


def _merge_evidence_fields(
    job_ids: list[str],
    dense_ranks: list[JobRank],
    bm25_ranks: list[JobRank],
    raptor_ranks: list[JobRank] | None = None,
    max_fields_per_job: int = 4,
) -> dict[str, list[str]]:
    fields_by_job: dict[str, list[str]] = {job_id: [] for job_id in job_ids}
    ranks_by_source = [
        {rank.job_id: rank.evidence_fields for rank in dense_ranks},
        {rank.job_id: rank.evidence_fields for rank in bm25_ranks},
    ]
    if raptor_ranks:
        ranks_by_source.append(
            {rank.job_id: rank.evidence_fields for rank in raptor_ranks}
        )

    for job_id in job_ids:
        seen: set[str] = set()
        for source in ranks_by_source:
            for field_name in source.get(job_id, []):
                if field_name not in seen:
                    fields_by_job[job_id].append(field_name)
                    seen.add(field_name)
                if len(fields_by_job[job_id]) >= max_fields_per_job:
                    break
            if len(fields_by_job[job_id]) >= max_fields_per_job:
                break
    return fields_by_job


def _field_bonus_from_evidence_fields(fields: list[str]) -> float:
    bonus = 0.0
    for field_name in set(fields):
        bonus += FIELD_AWARE_BONUS.get(field_name, 0.0)
    return min(round(bonus, 6), MAX_FIELD_BONUS)


async def _fetch_job_metadata(
    pool, job_ids: list[str]
) -> dict[str, dict[str, Any]]:
    if not job_ids:
        return {}

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT job_id, title, company, location, role_cluster
            FROM jobs
            WHERE job_id = ANY($1::text[])
            """,
            job_ids,
        )
    return {str(row["job_id"]): dict(row) for row in rows}


async def _fetch_evidence_payloads(
    pool, evidence_by_job: dict[str, list[str]]
) -> dict[str, list[dict[str, Any]]]:
    evidence_ids = [
        evidence_id
        for ids in evidence_by_job.values()
        for evidence_id in ids
        if evidence_id
    ]
    if not evidence_ids:
        return {job_id: [] for job_id in evidence_by_job}

    unique_ids = list(dict.fromkeys(evidence_ids))
    async with pool.acquire() as conn:
        chunk_rows = await conn.fetch(
            """
            SELECT chunk_id AS evidence_span_id, job_id, field, content
            FROM job_chunks
            WHERE chunk_id = ANY($1::text[])
            """,
            unique_ids,
        )

    payload_by_id: dict[str, dict[str, Any]] = {}
    for row in chunk_rows:
        payload_by_id[str(row["evidence_span_id"])] = {
            "evidence_span_id": str(row["evidence_span_id"]),
            "job_id": str(row["job_id"]),
            "field": row["field"],
            "content": row["content"],
            "source": "job_chunk",
        }

    return {
        job_id: [
            payload_by_id[evidence_id]
            for evidence_id in evidence_ids_for_job
            if evidence_id in payload_by_id
        ]
        for job_id, evidence_ids_for_job in evidence_by_job.items()
    }


async def hybrid_search(
    query: str,
    hard_constraints: dict[str, Any] | None = None,
    soft_prefs: dict[str, Any] | None = None,
    top_k: int = 20,
    include_raptor: bool = False,
) -> list[JobCandidate]:
    if not query.strip():
        return []

    hard_constraints = hard_constraints or {}
    soft_prefs = soft_prefs or {}
    recall_k = max(top_k * 4, top_k, 10)
    pool = await get_pool()

    allow_ids = await _hard_filter_ids(pool, hard_constraints)
    if not allow_ids:
        return []

    raptor_hits: list[ChunkHit] = []
    if include_raptor:
        bm25_hits, dense_hits, raptor_node_hits = await asyncio.gather(
            _bm25(pool, query, allow_ids, recall_k),
            _dense(pool, query, allow_ids, recall_k),
            search_raptor_nodes(
                pool,
                query=query,
                allow_ids=allow_ids,
                top_k=recall_k,
            ),
        )
        raptor_hits = [
            ChunkHit(
                job_id=hit.job_id,
                chunk_id=hit.chunk_id,
                score=hit.score,
                field=hit.field,
            )
            for hit in raptor_node_hits
            if hit.chunk_id
        ]
    else:
        bm25_hits, dense_hits = await asyncio.gather(
            _bm25(pool, query, allow_ids, recall_k),
            _dense(pool, query, allow_ids, recall_k),
        )

    bm25_ranks = _collapse_chunk_hits(bm25_hits)
    dense_ranks = _collapse_chunk_hits(dense_hits)
    raptor_ranks = _collapse_raptor_hits(raptor_hits)
    rank_lists = [_rank_list(bm25_ranks), _rank_list(dense_ranks)]
    if raptor_ranks:
        rank_lists.append(_rank_list(raptor_ranks))
    fused = rrf_fuse(rank_lists)
    if not fused:
        return []

    candidate_ids = [job_id for job_id, _score in fused[: max(top_k * 3, top_k)]]
    metadata_by_job = await _fetch_job_metadata(pool, candidate_ids)
    evidence_by_job = _merge_evidence(
        candidate_ids, dense_ranks, bm25_ranks, raptor_ranks
    )
    evidence_payloads_by_job = await _fetch_evidence_payloads(pool, evidence_by_job)
    evidence_fields_by_job = _merge_evidence_fields(
        candidate_ids, dense_ranks, bm25_ranks, raptor_ranks
    )
    field_bonus_by_job = {
        job_id: _field_bonus_from_evidence_fields(fields)
        for job_id, fields in evidence_fields_by_job.items()
    }

    return _rerank_candidates(
        fused=fused,
        bm25_by_job=_score_by_job(bm25_ranks),
        dense_by_job=_score_by_job(dense_ranks),
        evidence_by_job=evidence_by_job,
        metadata_by_job=metadata_by_job,
        soft_prefs=soft_prefs,
        top_k=top_k,
        field_bonus_by_job=field_bonus_by_job,
        raptor_by_job=_score_by_job(raptor_ranks),
        evidence_payloads_by_job=evidence_payloads_by_job,
    )


async def _query_from_session(session_id: str) -> str:
    state = await load_state(session_id)
    if state is None:
        raise ValueError(f"No session_state row found for session_id={session_id!r}")

    query = build_resume_retrieval_query(state.resume_state).text.strip()
    if not query:
        raise ValueError(
            f"session_id={session_id!r} has no normalized_base_resume"
        )
    return query


def _parse_json_arg(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("JSON argument must decode to an object")
    return parsed


def _print_candidates(candidates: list[JobCandidate]) -> None:
    print(
        "rank\tjob_id\tscore\trrf\tbm25\tdense\traptor\tfield_bonus\tsources\t"
        "title\tcompany\tlocation\tevidence"
    )
    for rank, candidate in enumerate(candidates, start=1):
        evidence = ",".join(candidate.evidence_span_ids)
        sources = ",".join(candidate.sources)
        print(
            f"{rank}\t{candidate.job_id}\t{candidate.score:.6f}\t"
            f"{candidate.rrf_score:.6f}\t{candidate.bm25_score:.6f}\t"
            f"{candidate.dense_score:.6f}\t{candidate.raptor_score:.6f}\t"
            f"{candidate.field_bonus:.6f}\t"
            f"{sources}\t"
            f"{candidate.title or ''}\t{candidate.company or ''}\t"
            f"{candidate.location or ''}\t{evidence}"
        )


async def _main_async(args: argparse.Namespace) -> None:
    try:
        query = args.query
        if args.session_id:
            query = await _query_from_session(args.session_id)
        if not query:
            raise ValueError("Provide --query or --session-id")

        candidates = await hybrid_search(
            query=query,
            hard_constraints=_parse_json_arg(args.hard_constraints),
            soft_prefs=_parse_json_arg(args.soft_prefs),
            top_k=args.top_k,
            include_raptor=args.include_raptor,
        )
        _print_candidates(candidates)
    finally:
        await close_pool()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run P0 hybrid job retrieval from a query or resume session."
    )
    parser.add_argument("--query", help="Raw query text. Ignored if --session-id is set.")
    parser.add_argument(
        "--session-id",
        help="Load resume_state.normalized_base_resume from session_state.",
    )
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument(
        "--include-raptor",
        action="store_true",
        help="Add RAPTOR-lite summary-node recall as a third retrieval source.",
    )
    parser.add_argument("--hard-constraints", help="JSON object for SQL hard filters.")
    parser.add_argument("--soft-prefs", help="JSON object for ranking preferences.")
    args = parser.parse_args()

    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
