"""在 CN/UK 演示语料上重跑检索评估（LLM 辅助池化标注）。

背景：原评估集（data/eval，arshkon 1000 岗 + 15 个人工标注 case）与 W5 演示语料
（linkedin_ml_cnuk_demo_v1，31,879 岗）是两个数据集，117 个标注岗位在新语料中
命中 0 个，旧标签完全不可复用。本脚本在"系统实际服务的语料"上产出新指标：

方法（TREC 池化 + LLM 评审）：
  1. 复用原 15 条查询（纯语义查询，不带地点/签证约束）；
  2. 每条查询跑一次真实 hybrid_search(top_k=N)，取融合候选池；
     同一池内按 bm25_score / dense_score 排序重建两条单通道基线；
  3. 池内每个 (query, job) 由 DeepSeek fast 判定相关/不相关（严格 JSON，
     判据=岗位职责与查询技能方向是否实质匹配）；
  4. 用 app.evaluation.metrics 计算 Precision/Recall/MRR/NDCG@K。

诚实声明（写进论文时必须带上）：
  * 相关标签由 LLM 评审产生（annotation_method=llm_judged_pooled），
    与原人工标注口径不同，两组数字不可直接横向比较；
  * 池化评估的 Recall 是"池内召回"：池外可能存在未被任何通道召回的相关岗，
    因此 Recall 数字偏乐观，主要价值在于通道间的相对比较（hybrid vs 单通道）。

用法：
  .venv\\Scripts\\python scripts\\evaluate_demo_corpus.py            # 全量 15 case
  .venv\\Scripts\\python scripts\\evaluate_demo_corpus.py --limit 3  # 冒烟
可选 --include-raptor：hybrid 走 include_raptor=True 做消融对比（需先建索引）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.pool import close_pool, get_pool
from app.evaluation.artifacts import load_jsonl
from app.evaluation.metrics import (
    build_metric_table,
    format_metric_table_markdown,
)
from app.llm import deepseek
from app.retrieval.hybrid_search import JobCandidate, hybrid_search

QUERIES_PATH = ROOT / "data/eval/resume_queries.jsonl"
OUTPUT_DIR = ROOT / "data/eval/demo_corpus_v1"
SOURCE_TAG = "linkedin_ml_cnuk_demo_v1"

JUDGE_SYSTEM = (
    "You are a strict relevance judge for a job-search system. "
    "Given a candidate query and one job posting, answer whether the job is a "
    "substantively relevant match for the query (same occupational direction "
    "and required skills; synthetic company/city names must be ignored). "
    'Return strict JSON: {"relevant": true} or {"relevant": false}.'
)


def _channel_ranking(
    candidates: list[JobCandidate], score_attr: str
) -> list[str]:
    scored = [
        (getattr(item, score_attr), item.job_id)
        for item in candidates
        if getattr(item, score_attr) > 0
    ]
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [job_id for _score, job_id in scored]


async def _fetch_job_texts(pool, job_ids: list[str]) -> dict[str, str]:
    async with pool.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT job_id, title, raw_jd
            FROM jobs
            WHERE job_id = ANY($1::text[])
            """,
            job_ids,
        )
    return {
        row["job_id"]: f"Title: {row['title']}\n{(row['raw_jd'] or '')[:700]}"
        for row in rows
    }


async def _judge(query: str, job_text: str) -> bool:
    raw = await deepseek.chat(
        JUDGE_SYSTEM,
        f"Query: {query}\n\nJob posting:\n{job_text}",
        json_mode=True,
    )
    payload = deepseek.extract_json_response(raw)
    return bool(isinstance(payload, dict) and payload.get("relevant") is True)


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pooled LLM-judged retrieval eval on the demo corpus"
    )
    parser.add_argument("--top-k", type=int, default=30)
    parser.add_argument("--k-values", type=int, nargs="+", default=[5, 10])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--include-raptor", action="store_true")
    args = parser.parse_args()

    queries = load_jsonl(QUERIES_PATH)
    if args.limit:
        queries = queries[: args.limit]

    pool = await get_pool()
    labels: list[dict[str, Any]] = []
    rankings_by_run: dict[str, dict[str, list[str]]] = {
        "hybrid_rrf_biencoder": {},
        "bm25_only": {},
        "dense_only": {},
    }
    if args.include_raptor:
        rankings_by_run["hybrid_with_raptor"] = {}
    judged_total = 0

    for row in queries:
        case_id = str(row["case_id"])
        query = str(row["query"])
        candidates = await hybrid_search(query, top_k=args.top_k)
        rankings_by_run["hybrid_rrf_biencoder"][case_id] = [
            item.job_id for item in candidates
        ]
        rankings_by_run["bm25_only"][case_id] = _channel_ranking(
            candidates, "bm25_score"
        )
        rankings_by_run["dense_only"][case_id] = _channel_ranking(
            candidates, "dense_score"
        )
        pool_ids = [item.job_id for item in candidates]
        if args.include_raptor:
            raptor_candidates = await hybrid_search(
                query, top_k=args.top_k, include_raptor=True
            )
            rankings_by_run["hybrid_with_raptor"][case_id] = [
                item.job_id for item in raptor_candidates
            ]
            pool_ids = list(
                dict.fromkeys(
                    pool_ids + [item.job_id for item in raptor_candidates]
                )
            )

        job_texts = await _fetch_job_texts(pool, pool_ids)
        verdicts = await asyncio.gather(
            *[_judge(query, job_texts.get(job_id, "")) for job_id in pool_ids]
        )
        judged_total += len(pool_ids)
        relevant = [
            job_id
            for job_id, verdict in zip(pool_ids, verdicts)
            if verdict
        ]
        labels.append(
            {
                "case_id": case_id,
                "query": query,
                "relevant_job_ids": relevant,
                "pool_size": len(pool_ids),
                "annotation_method": "llm_judged_pooled",
            }
        )
        print(
            f"{case_id}: pool={len(pool_ids)} relevant={len(relevant)}",
            flush=True,
        )

    table = build_metric_table(
        labels, rankings_by_run, k_values=args.k_values
    )
    markdown = format_metric_table_markdown(table)
    print()
    print(markdown)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "labels.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in labels)
        + "\n",
        encoding="utf-8",
    )
    (OUTPUT_DIR / "rankings.json").write_text(
        json.dumps(rankings_by_run, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(
            {
                "dataset": SOURCE_TAG,
                "generated_on": date.today().isoformat(),
                "queries_file": "data/eval/resume_queries.jsonl",
                "query_cases": len(labels),
                "pooling": {
                    "top_k_per_channel_pool": args.top_k,
                    "channels": sorted(rankings_by_run),
                },
                "judged_pairs": judged_total,
                "annotation_method": "llm_judged_pooled",
                "judge_model": "deepseek_fast_json_mode",
                "caveats": [
                    "pooled recall is optimistic (pool-relative)",
                    "labels are LLM-judged, not comparable to the human-annotated arshkon-1000 numbers",
                ],
                "metric_table_markdown": markdown,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"\nartifacts written to {OUTPUT_DIR}")
    await close_pool()


if __name__ == "__main__":
    if sys.platform == "win32":
        with asyncio.Runner(
            loop_factory=asyncio.SelectorEventLoop
        ) as runner:
            runner.run(main())
    else:
        asyncio.run(main())
