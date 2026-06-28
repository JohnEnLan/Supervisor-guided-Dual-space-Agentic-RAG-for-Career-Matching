"""混合检索：硬过滤(SQL) → 三路并行召回(metadata/BM25/dense) → RRF → bi-encoder 排序。

这是单请求内并发的核心示例：三路独立召回用 asyncio.gather 并行，而不是串行排队。
"""
import asyncio
from dataclasses import dataclass
from app.db.pool import get_pool
from app.llm.qwen_embed import embed_one
from app.retrieval.rrf import rrf_fuse


@dataclass
class JobCandidate:
    job_id: str
    score: float
    evidence_span_ids: list[str]


async def _hard_filter_ids(conn, hard_constraints: dict) -> list[str]:
    """硬过滤走 SQL，绝不交给 LLM。返回通过硬约束的 job_id 白名单。"""
    clauses, params = ["is_open = TRUE"], []
    if loc := hard_constraints.get("location"):
        params.append(loc); clauses.append(f"location = ${len(params)}")
    if hard_constraints.get("need_visa_sponsor"):
        clauses.append("visa_sponsor = TRUE")
    if (yrs := hard_constraints.get("max_years_exp")) is not None:
        params.append(yrs); clauses.append(f"min_years_exp <= ${len(params)}")
    sql = f"SELECT job_id FROM jobs WHERE {' AND '.join(clauses)}"
    rows = await conn.fetch(sql, *params)
    return [r["job_id"] for r in rows]


async def _bm25(conn, query: str, allow_ids: list[str], k: int):
    rows = await conn.fetch(
        """
        SELECT job_id, ts_rank(tsv, plainto_tsquery($1)) AS score
        FROM job_chunks
        WHERE job_id = ANY($2) AND tsv @@ plainto_tsquery($1)
        ORDER BY score DESC LIMIT $3
        """,
        query, allow_ids, k,
    )
    return [(r["job_id"], r["score"]) for r in rows]


async def _dense(conn, query_emb: list[float], allow_ids: list[str], k: int):
    rows = await conn.fetch(
        """
        SELECT job_id, 1 - (embedding <=> $1) AS score
        FROM job_chunks
        WHERE job_id = ANY($2)
        ORDER BY embedding <=> $1 LIMIT $3
        """,
        query_emb, allow_ids, k,
    )
    return [(r["job_id"], r["score"]) for r in rows]


async def hybrid_search(
    query: str,
    hard_constraints: dict,
    soft_prefs: dict,
    top_k: int = 20,
) -> list[JobCandidate]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        allow_ids = await _hard_filter_ids(conn, hard_constraints)
        if not allow_ids:
            return []

        query_emb = await embed_one(query)

        # —— 单请求内并发：BM25 与 dense 同时跑 ——
        bm25_res, dense_res = await asyncio.gather(
            _bm25(conn, query, allow_ids, top_k * 2),
            _dense(conn, query_emb, allow_ids, top_k * 2),
        )

    fused = rrf_fuse([bm25_res, dense_res])  # RRF 融合
    # TODO(P0): bi-encoder 粗排（可直接用上面的 dense score 作为近似，先跑通）
    # TODO(soft): 用 soft_prefs 给排序加权
    # TODO(P2): 可选 cross-encoder 对 Top-20 重排
    return [JobCandidate(job_id=jid, score=s, evidence_span_ids=[])
            for jid, s in fused[:top_k]]
