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

CREATE TABLE IF NOT EXISTS raptor_node_chunks (
    node_id   TEXT NOT NULL REFERENCES raptor_nodes(node_id) ON DELETE CASCADE,
    chunk_id  TEXT NOT NULL REFERENCES job_chunks(chunk_id) ON DELETE CASCADE,
    job_id    TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    depth     SMALLINT NOT NULL CHECK (depth >= 1),
    leaf_rank INTEGER NOT NULL CHECK (leaf_rank >= 1),
    PRIMARY KEY (node_id, chunk_id)
);

CREATE INDEX IF NOT EXISTS idx_raptor_node_chunks_job
    ON raptor_node_chunks (job_id, node_id);
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
    chunk_id: str | None = None
    field: str | None = None


@dataclass(frozen=True)
class RaptorBuildStats:
    job_nodes: int
    role_nodes: int
    total_nodes: int


@dataclass(frozen=True)
class RaptorNodeChunk:
    node_id: str
    chunk_id: str
    job_id: str
    depth: int
    leaf_rank: int


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


def build_node_chunk_mappings(
    nodes: Sequence[RaptorNode],
    *,
    jobs_with_chunks: Mapping[str, Mapping[str, Any]],
) -> list[RaptorNodeChunk]:
    mappings: list[RaptorNodeChunk] = []
    for node in nodes:
        depth = 1 if node.node_type == "job_summary" else 2
        leaf_rank = 0
        for job_id in _dedupe(node.source_job_ids):
            job_payload = jobs_with_chunks.get(job_id) or {}
            for chunk in job_payload.get("chunks") or []:
                chunk_id = str(_value(chunk, "chunk_id") or "").strip()
                if not chunk_id:
                    continue
                leaf_rank += 1
                mappings.append(
                    RaptorNodeChunk(
                        node_id=node.node_id,
                        chunk_id=chunk_id,
                        job_id=job_id,
                        depth=depth,
                        leaf_rank=leaf_rank,
                    )
                )
    return mappings


def propagate_raptor_hits(
    *,
    node_rows: Sequence[Mapping[str, Any]],
    leaf_rows: Sequence[Mapping[str, Any]],
    allow_ids: Sequence[str],
    max_leaf_chunks_per_node: int = 8,
    level_decay: float = 0.65,
) -> list[RaptorHit]:
    """Project summary-node recall through relevant original JD chunks."""
    if max_leaf_chunks_per_node <= 0:
        return []

    allowed = {str(job_id) for job_id in allow_ids}
    nodes = {
        str(_value(row, "node_id")): row
        for row in node_rows
        if _value(row, "node_id")
    }
    leaves_by_node: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in leaf_rows:
        node_id = str(_value(row, "node_id") or "")
        job_id = str(_value(row, "job_id") or "")
        if node_id in nodes and job_id in allowed and _value(row, "chunk_id"):
            leaves_by_node[node_id].append(row)

    combined: dict[tuple[str, str], dict[str, Any]] = {}
    for node_id, node in nodes.items():
        node_type = str(_value(node, "node_type") or "")
        candidates = sorted(
            leaves_by_node.get(node_id, []),
            key=lambda row: float(_value(row, "leaf_score") or 0.0),
            reverse=True,
        )
        if node_type == "role_summary":
            candidates = _best_leaf_per_job(candidates)
        selected = candidates[:max_leaf_chunks_per_node]
        if not selected:
            continue

        node_score = max(0.0, float(_value(node, "score") or 0.0))
        fanout = len(selected)
        for leaf in selected:
            depth = max(1, int(_value(leaf, "depth") or 1))
            leaf_score = max(0.0, float(_value(leaf, "leaf_score") or 0.0))
            contribution = (
                node_score
                * leaf_score
                * (level_decay ** (depth - 1))
                / fanout
            )
            if contribution <= 0:
                continue

            job_id = str(_value(leaf, "job_id"))
            chunk_id = str(_value(leaf, "chunk_id"))
            key = (job_id, chunk_id)
            current = combined.setdefault(
                key,
                {
                    "score": 0.0,
                    "best_contribution": -1.0,
                    "node_id": node_id,
                    "node_type": node_type,
                    "field": _value(leaf, "field"),
                },
            )
            current["score"] += contribution
            if contribution > current["best_contribution"]:
                current["best_contribution"] = contribution
                current["node_id"] = node_id
                current["node_type"] = node_type
                current["field"] = _value(leaf, "field")

    hits = [
        RaptorHit(
            job_id=job_id,
            node_id=str(payload["node_id"]),
            score=round(float(payload["score"]), 6),
            node_type=str(payload["node_type"]),
            chunk_id=chunk_id,
            field=(str(payload["field"]) if payload["field"] else None),
        )
        for (job_id, chunk_id), payload in combined.items()
    ]
    return sorted(hits, key=lambda hit: (-hit.score, hit.job_id, hit.chunk_id or ""))


def _best_leaf_per_job(
    candidates: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    selected = []
    seen_jobs: set[str] = set()
    for row in candidates:
        job_id = str(_value(row, "job_id") or "")
        if not job_id or job_id in seen_jobs:
            continue
        seen_jobs.add(job_id)
        selected.append(row)
    return selected


def _limit_hits_to_top_jobs(
    hits: Sequence[RaptorHit], *, top_k: int
) -> list[RaptorHit]:
    if top_k <= 0:
        return []

    scores_by_job: dict[str, float] = defaultdict(float)
    for hit in hits:
        scores_by_job[hit.job_id] += max(0.0, hit.score)

    top_job_ids = {
        job_id
        for job_id, _score in sorted(
            scores_by_job.items(), key=lambda item: (-item[1], item[0])
        )[:top_k]
    }
    return [hit for hit in hits if hit.job_id in top_job_ids]


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
    await _replace_node_chunk_mappings(
        pool,
        node_ids=[node.node_id for node in nodes],
        mappings=build_node_chunk_mappings(
            nodes,
            jobs_with_chunks=jobs_with_chunks,
        ),
    )
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
    max_leaf_chunks_per_node: int = 8,
    level_decay: float = 0.65,
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
        node_rows = await conn.fetch(
            """
            SELECT node_id,
                   node_type,
                   job_id,
                   source_job_ids,
                   1 - (embedding <=> $1::vector) AS score
            FROM raptor_nodes
            WHERE embedding IS NOT NULL
              AND (job_id IS NULL OR job_id = ANY($2::text[]))
            ORDER BY embedding <=> $1::vector
            LIMIT $3
            """,
            query_vector,
            list(allow_ids),
            node_k or max(top_k * 4, top_k, 10),
        )
        node_ids = [str(_value(row, "node_id")) for row in node_rows]
        if not node_ids:
            return []
        leaf_rows = await conn.fetch(
            """
            SELECT mapping.node_id,
                   mapping.chunk_id,
                   mapping.job_id,
                   mapping.depth,
                   chunks.field,
                   1 - (chunks.embedding <=> $1::vector) AS leaf_score
            FROM raptor_node_chunks AS mapping
            JOIN job_chunks AS chunks ON chunks.chunk_id = mapping.chunk_id
            WHERE mapping.node_id = ANY($2::text[])
              AND mapping.job_id = ANY($3::text[])
              AND chunks.embedding IS NOT NULL
            ORDER BY mapping.node_id,
                     chunks.embedding <=> $1::vector,
                     mapping.leaf_rank
            """,
            query_vector,
            node_ids,
            list(allow_ids),
        )

    hits = propagate_raptor_hits(
        node_rows=node_rows,
        leaf_rows=leaf_rows,
        allow_ids=allow_ids,
        max_leaf_chunks_per_node=max_leaf_chunks_per_node,
        level_decay=level_decay,
    )
    return _limit_hits_to_top_jobs(hits, top_k=top_k)


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


async def _replace_node_chunk_mappings(
    pool,
    *,
    node_ids: Sequence[str],
    mappings: Sequence[RaptorNodeChunk],
) -> None:
    if not node_ids:
        return

    records = [
        (
            item.node_id,
            item.chunk_id,
            item.job_id,
            item.depth,
            item.leaf_rank,
        )
        for item in mappings
    ]
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM raptor_node_chunks WHERE node_id = ANY($1::text[])",
            list(node_ids),
        )
        if records:
            await conn.executemany(
                """
                INSERT INTO raptor_node_chunks (
                    node_id, chunk_id, job_id, depth, leaf_rank
                )
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (node_id, chunk_id) DO UPDATE SET
                    job_id = EXCLUDED.job_id,
                    depth = EXCLUDED.depth,
                    leaf_rank = EXCLUDED.leaf_rank
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
