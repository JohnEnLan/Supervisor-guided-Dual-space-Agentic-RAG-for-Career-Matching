from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from app.config import settings
from app.llm.qwen_embed import embed_one, embed_texts


RAPTOR_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS raptor_nodes (
    node_id        TEXT PRIMARY KEY,
    node_type      TEXT NOT NULL CHECK (node_type IN ('job_summary', 'role_summary')),
    parent_id      TEXT,
    role_cluster   TEXT,
    job_id         TEXT REFERENCES jobs(job_id),
    title          TEXT,
    content        TEXT NOT NULL,
    source_job_ids TEXT[] NOT NULL DEFAULT '{}',
    embedding      vector(1024),
    tsv            tsvector,
    updated_at     TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_raptor_nodes_hnsw
    ON raptor_nodes USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_raptor_nodes_tsv
    ON raptor_nodes USING gin (tsv);

CREATE INDEX IF NOT EXISTS idx_raptor_nodes_type_cluster
    ON raptor_nodes (node_type, role_cluster);
"""

CHUNK_FIELD_PRIORITY = {
    "metadata": 0,
    "required_skills": 1,
    "responsibilities": 2,
    "nice_to_have": 3,
}


@dataclass(frozen=True)
class RaptorNode:
    node_id: str
    node_type: str
    content: str
    source_job_ids: list[str]
    parent_id: str | None = None
    role_cluster: str | None = None
    job_id: str | None = None
    title: str | None = None


@dataclass(frozen=True)
class RaptorHit:
    job_id: str
    node_id: str
    score: float
    node_type: str


@dataclass(frozen=True)
class RaptorBuildStats:
    job_nodes: int
    role_nodes: int
    total_nodes: int


async def ensure_raptor_schema(pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(RAPTOR_SCHEMA_SQL)


def build_job_summary_node(
    *, job: Mapping[str, Any], chunks: Sequence[Mapping[str, Any]], max_chars: int = 1800
) -> RaptorNode:
    job_id = str(_value(job, "job_id"))
    role_cluster = _slug_role_cluster(_value(job, "role_cluster"))
    title = _clean(_value(job, "title") or "")
    lines = _job_metadata_lines(job)

    for chunk in sorted(chunks, key=_chunk_sort_key):
        content = _clean(_value(chunk, "content") or "")
        if content:
            lines.append(content)

    content = _clip_lines(_dedupe(lines), max_chars=max_chars)
    return RaptorNode(
        node_id=f"job:{job_id}",
        node_type="job_summary",
        parent_id=f"role:{role_cluster}",
        role_cluster=role_cluster,
        job_id=job_id,
        title=title or None,
        content=content,
        source_job_ids=[job_id],
    )


def build_role_summary_node(
    role_cluster: str, job_nodes: Sequence[RaptorNode], max_chars: int = 2400
) -> RaptorNode:
    role = _slug_role_cluster(role_cluster)
    source_job_ids = [node.job_id for node in job_nodes if node.job_id]
    titles = _dedupe([node.title or "" for node in job_nodes if node.title])

    lines = [
        f"Role cluster: {role}",
        f"Representative jobs: {'; '.join(titles[:12])}",
    ]
    for node in job_nodes[:12]:
        if node.title:
            lines.append(f"{node.title}: {_first_sentence(node.content)}")

    return RaptorNode(
        node_id=f"role:{role}",
        node_type="role_summary",
        role_cluster=role,
        title=f"Role cluster: {role}",
        content=_clip_lines(_dedupe(lines), max_chars=max_chars),
        source_job_ids=source_job_ids,
    )


def expand_raptor_hits(
    *,
    rows: Sequence[Mapping[str, Any]],
    allow_ids: Sequence[str],
    max_jobs_per_role: int = 20,
) -> list[RaptorHit]:
    allowed = {str(job_id) for job_id in allow_ids}
    best_by_job: dict[str, RaptorHit] = {}

    for row in rows:
        node_id = str(_value(row, "node_id"))
        node_type = str(_value(row, "node_type"))
        score = round(float(_value(row, "score") or 0.0), 6)
        job_id = _value(row, "job_id")

        if job_id:
            _keep_best_hit(
                best_by_job,
                RaptorHit(
                    job_id=str(job_id),
                    node_id=node_id,
                    score=score,
                    node_type=node_type,
                ),
                allowed,
            )
            continue

        source_job_ids = [str(item) for item in (_value(row, "source_job_ids") or [])]
        expanded = [job for job in source_job_ids if job in allowed][:max_jobs_per_role]
        for expanded_job_id in expanded:
            _keep_best_hit(
                best_by_job,
                RaptorHit(
                    job_id=expanded_job_id,
                    node_id=node_id,
                    score=score,
                    node_type=node_type,
                ),
                allowed,
            )

    return sorted(best_by_job.values(), key=lambda hit: hit.score, reverse=True)


async def build_raptor_index(
    pool,
    *,
    limit: int | None = None,
    batch_size: int = 10,
    include_role_summaries: bool = True,
) -> RaptorBuildStats:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    await ensure_raptor_schema(pool)
    jobs_with_chunks = await _fetch_jobs_with_chunks(pool, limit=limit)
    job_nodes = [
        build_job_summary_node(job=item["job"], chunks=item["chunks"])
        for item in jobs_with_chunks.values()
    ]

    role_nodes: list[RaptorNode] = []
    if include_role_summaries:
        by_role: dict[str, list[RaptorNode]] = defaultdict(list)
        for node in job_nodes:
            by_role[node.role_cluster or "unknown"].append(node)
        role_nodes = [
            build_role_summary_node(role, nodes)
            for role, nodes in sorted(by_role.items())
            if nodes
        ]

    nodes = job_nodes + role_nodes
    embeddings = await _embed_nodes(nodes, batch_size=batch_size)
    await _upsert_nodes(pool, nodes, embeddings)
    return RaptorBuildStats(
        job_nodes=len(job_nodes),
        role_nodes=len(role_nodes),
        total_nodes=len(nodes),
    )


async def search_raptor_nodes(
    pool,
    *,
    query: str,
    allow_ids: Sequence[str],
    top_k: int,
    node_k: int | None = None,
    max_jobs_per_role: int = 20,
) -> list[RaptorHit]:
    if not allow_ids or not query.strip():
        return []

    await ensure_raptor_schema(pool)
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
            SELECT node_id,
                   node_type,
                   job_id,
                   source_job_ids,
                   1 - (embedding <=> $1::vector) AS score
            FROM raptor_nodes
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> $1::vector
            LIMIT $2
            """,
            query_vector,
            node_k or max(top_k * 4, top_k, 10),
        )

    hits = expand_raptor_hits(
        rows=rows,
        allow_ids=allow_ids,
        max_jobs_per_role=max_jobs_per_role,
    )
    return hits[:top_k]


async def _fetch_jobs_with_chunks(pool, *, limit: int | None) -> dict[str, dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            WITH selected_jobs AS (
                SELECT job_id, title, company, location, role_cluster
                FROM jobs
                WHERE is_open = TRUE
                ORDER BY job_id
                LIMIT $1
            )
            SELECT
                j.job_id,
                j.title,
                j.company,
                j.location,
                j.role_cluster,
                c.chunk_id,
                c.field,
                c.content
            FROM selected_jobs j
            LEFT JOIN job_chunks c ON c.job_id = j.job_id
            ORDER BY j.job_id, c.field, c.chunk_id
            """,
            limit,
        )

    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        job_id = str(row["job_id"])
        grouped.setdefault(
            job_id,
            {
                "job": {
                    "job_id": job_id,
                    "title": row["title"],
                    "company": row["company"],
                    "location": row["location"],
                    "role_cluster": row["role_cluster"],
                },
                "chunks": [],
            },
        )
        if row["chunk_id"]:
            grouped[job_id]["chunks"].append(
                {
                    "chunk_id": row["chunk_id"],
                    "field": row["field"],
                    "content": row["content"],
                }
            )
    return grouped


async def _embed_nodes(
    nodes: Sequence[RaptorNode], *, batch_size: int
) -> list[list[float]]:
    embeddings: list[list[float]] = []
    for start in range(0, len(nodes), batch_size):
        batch = nodes[start : start + batch_size]
        vectors = await embed_texts([node.content for node in batch])
        for vector in vectors:
            if len(vector) != settings.embed_dim:
                raise ValueError(
                    f"Embedding dimension mismatch: got {len(vector)}, "
                    f"expected {settings.embed_dim}"
                )
        embeddings.extend(vectors)
    return embeddings


async def _upsert_nodes(
    pool, nodes: Sequence[RaptorNode], embeddings: Sequence[Sequence[float]]
) -> None:
    records = [
        (
            node.node_id,
            node.node_type,
            node.parent_id,
            node.role_cluster,
            node.job_id,
            node.title,
            node.content,
            node.source_job_ids,
            _to_vector_literal(list(embedding)),
        )
        for node, embedding in zip(nodes, embeddings, strict=True)
    ]
    if not records:
        return

    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO raptor_nodes (
                node_id, node_type, parent_id, role_cluster, job_id, title,
                content, source_job_ids, embedding, tsv, updated_at
            )
            VALUES (
                $1, $2, $3, $4, $5, $6,
                $7, $8::text[], $9::vector, to_tsvector('english', $7), now()
            )
            ON CONFLICT (node_id) DO UPDATE SET
                node_type = EXCLUDED.node_type,
                parent_id = EXCLUDED.parent_id,
                role_cluster = EXCLUDED.role_cluster,
                job_id = EXCLUDED.job_id,
                title = EXCLUDED.title,
                content = EXCLUDED.content,
                source_job_ids = EXCLUDED.source_job_ids,
                embedding = EXCLUDED.embedding,
                tsv = EXCLUDED.tsv,
                updated_at = now()
            """,
            records,
        )


def _job_metadata_lines(job: Mapping[str, Any]) -> list[str]:
    lines = []
    if _value(job, "title"):
        lines.append(f"Title: {_clean(_value(job, 'title'))}")
    if _value(job, "company"):
        lines.append(f"Company: {_clean(_value(job, 'company'))}")
    if _value(job, "location"):
        lines.append(f"Location: {_clean(_value(job, 'location'))}")
    if _value(job, "role_cluster"):
        lines.append(f"Role cluster: {_slug_role_cluster(_value(job, 'role_cluster'))}")
    return lines


def _chunk_sort_key(chunk: Mapping[str, Any]) -> tuple[int, str]:
    field = str(_value(chunk, "field") or "")
    chunk_id = str(_value(chunk, "chunk_id") or "")
    return (CHUNK_FIELD_PRIORITY.get(field, 99), chunk_id)


def _keep_best_hit(
    best_by_job: dict[str, RaptorHit], hit: RaptorHit, allowed: set[str]
) -> None:
    if hit.job_id not in allowed:
        return
    current = best_by_job.get(hit.job_id)
    if current is None or hit.score > current.score:
        best_by_job[hit.job_id] = hit


def _slug_role_cluster(raw: Any) -> str:
    value = _clean(str(raw or "unknown")).casefold()
    slug = re.sub(r"[^a-z0-9]+", "_", value).strip("_")
    return slug or "unknown"


def _first_sentence(text: str, max_chars: int = 220) -> str:
    first = re.split(r"(?<=[.!?])\s+", _clean(text), maxsplit=1)[0]
    return first[:max_chars]


def _clip_lines(lines: Iterable[str], *, max_chars: int) -> str:
    output: list[str] = []
    total = 0
    for line in lines:
        text = _clean(line)
        if not text:
            continue
        next_total = total + len(text) + (1 if output else 0)
        if next_total > max_chars:
            break
        output.append(text)
        total = next_total
    return "\n".join(output)


def _dedupe(lines: Iterable[str]) -> list[str]:
    output = []
    seen = set()
    for line in lines:
        text = _clean(line)
        key = text.casefold()
        if text and key not in seen:
            output.append(text)
            seen.add(key)
    return output


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()


def _value(row: Mapping[str, Any], key: str) -> Any:
    try:
        return row[key]
    except (KeyError, TypeError):
        get = getattr(row, "get", None)
        if get is not None:
            return get(key)
    return None


def _to_vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{float(value):.10g}" for value in values) + "]"
