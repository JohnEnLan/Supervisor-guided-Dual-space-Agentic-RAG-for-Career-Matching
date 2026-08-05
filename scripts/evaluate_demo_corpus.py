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
from hashlib import sha256
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.pool import close_pool, get_pool
from app.config import settings
from app.evaluation.artifacts import load_jsonl
from app.evaluation.metrics import (
    build_metric_table,
    format_metric_table_markdown,
)
from app.llm import deepseek
from app.llm.reranker import _require_rerank_endpoint
from app.retrieval.hybrid_search import JobCandidate, hybrid_search

QUERIES_PATH = ROOT / "data/eval/resume_queries.jsonl"
OUTPUT_DIR = ROOT / "data/eval/demo_corpus_cross_v1"
SOURCE_TAG = "linkedin_ml_cnuk_demo_v1"

RUN_SPECS = {
    "base": {"include_raptor": False, "use_cross_encoder": False},
    "raptor": {"include_raptor": True, "use_cross_encoder": False},
    "cross": {"include_raptor": False, "use_cross_encoder": True},
    "raptor_cross": {"include_raptor": True, "use_cross_encoder": True},
}

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


def _selected_run_specs(
    *,
    include_raptor: bool,
    use_cross_encoder: bool,
) -> dict[str, dict[str, bool]]:
    selected = {"base": dict(RUN_SPECS["base"])}
    if include_raptor:
        selected["raptor"] = dict(RUN_SPECS["raptor"])
    if use_cross_encoder:
        selected["cross"] = dict(RUN_SPECS["cross"])
    if include_raptor and use_cross_encoder:
        selected["raptor_cross"] = dict(RUN_SPECS["raptor_cross"])
    return selected


def _pool_fingerprint(pool_job_ids: dict[str, list[str]]) -> str:
    canonical = json.dumps(
        pool_job_ids,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


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
    parser.add_argument("--use-cross-encoder", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()

    selected_runs = _selected_run_specs(
        include_raptor=args.include_raptor,
        use_cross_encoder=args.use_cross_encoder,
    )
    if args.use_cross_encoder:
        if not 1 <= args.top_k <= 100:
            parser.error("--top-k must be between 1 and 100 for cross runs")
        _require_rerank_endpoint()

    queries = load_jsonl(QUERIES_PATH)
    if args.limit:
        queries = queries[: args.limit]

    pool = await get_pool()
    labels: list[dict[str, Any]] = []
    rankings_by_run: dict[str, dict[str, list[str]]] = {
        run_name: {} for run_name in selected_runs
    }
    rankings_by_run["bm25_within_pool"] = {}
    rankings_by_run["dense_within_pool"] = {}
    cross_encoder_windows: dict[str, dict[str, dict[str, Any]]] = {
        run_name: {} for run_name in selected_runs
    }
    pool_job_ids: dict[str, list[str]] = {}
    judged_total = 0

    try:
        for row in queries:
            case_id = str(row["case_id"])
            query = str(row["query"])
            candidates_by_run: dict[str, list[JobCandidate]] = {}
            for run_name, run_spec in selected_runs.items():
                search_kwargs: dict[str, Any] = {
                    "top_k": args.top_k,
                    "include_raptor": run_spec["include_raptor"],
                    "use_cross_encoder": run_spec["use_cross_encoder"],
                }
                if run_spec["use_cross_encoder"]:
                    audit: dict[str, Any] = {}
                    search_kwargs.update(
                        {
                            "rerank_top_n": 2 * args.top_k,
                            "rerank_audit": audit,
                        }
                    )
                else:
                    audit = {
                        "requested": 0,
                        "effective": 0,
                        "applied": False,
                        "reason_code": "disabled",
                    }
                candidates = await hybrid_search(query, **search_kwargs)
                candidates_by_run[run_name] = candidates
                rankings_by_run[run_name][case_id] = [
                    item.job_id for item in candidates
                ]
                cross_encoder_windows[run_name][case_id] = {
                    "requested": int(audit.get("requested", 0)),
                    "effective": int(audit.get("effective", 0)),
                    "applied": bool(audit.get("applied", False)),
                    "reason_code": str(audit.get("reason_code", "unknown")),
                }

            base_candidates = candidates_by_run["base"]
            rankings_by_run["bm25_within_pool"][case_id] = _channel_ranking(
                base_candidates,
                "bm25_score",
            )
            rankings_by_run["dense_within_pool"][case_id] = _channel_ranking(
                base_candidates,
                "dense_score",
            )
            ordered_pool = list(
                dict.fromkeys(
                    candidate.job_id
                    for run_name in selected_runs
                    for candidate in candidates_by_run[run_name]
                )
            )
            pool_job_ids[case_id] = ordered_pool

            job_texts = await _fetch_job_texts(pool, ordered_pool)
            verdicts = await asyncio.gather(
                *[
                    _judge(query, job_texts.get(job_id, ""))
                    for job_id in ordered_pool
                ]
            )
            judged_total += len(ordered_pool)
            relevant = [
                job_id
                for job_id, verdict in zip(ordered_pool, verdicts)
                if verdict
            ]
            labels.append(
                {
                    "case_id": case_id,
                    "query": query,
                    "relevant_job_ids": relevant,
                    "pool_size": len(ordered_pool),
                    "annotation_method": "llm_judged_pooled",
                }
            )
            print(
                f"{case_id}: pool={len(ordered_pool)} relevant={len(relevant)}",
                flush=True,
            )
    finally:
        await close_pool()

    cross_encoder_applied_ratio = {}
    for run_name, run_spec in selected_runs.items():
        if not run_spec["use_cross_encoder"]:
            continue
        run_windows = cross_encoder_windows[run_name]
        ratio = (
            sum(window["applied"] for window in run_windows.values())
            / len(run_windows)
            if run_windows
            else 0.0
        )
        cross_encoder_applied_ratio[run_name] = ratio
        if ratio <= 0:
            raise RuntimeError(
                f"cross run {run_name} applied ratio must be greater than zero"
            )

    table = build_metric_table(
        labels, rankings_by_run, k_values=args.k_values
    )
    markdown = format_metric_table_markdown(table)
    print()
    print(markdown)

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "labels.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in labels)
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "rankings.json").write_text(
        json.dumps(rankings_by_run, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    (output_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "demo_corpus_cross_v1",
                "dataset": SOURCE_TAG,
                "generated_on": date.today().isoformat(),
                "queries_file": "data/eval/resume_queries.jsonl",
                "query_cases": len(labels),
                "pooling": {
                    "top_k_per_channel_pool": args.top_k,
                    "channels": sorted(rankings_by_run),
                },
                "runs": [
                    {"name": run_name, **run_spec}
                    for run_name, run_spec in selected_runs.items()
                ],
                "pool_job_ids": pool_job_ids,
                "pool_fingerprint_sha256": _pool_fingerprint(pool_job_ids),
                "cross_encoder_windows": cross_encoder_windows,
                "cross_encoder_applied_ratio": cross_encoder_applied_ratio,
                "rerank_budget": {
                    "query_max_chars": settings.rerank_query_max_chars,
                    "document_max_chars": settings.rerank_doc_max_chars,
                    "item_max_est_tokens": 3800,
                    "request_max_est_tokens": 27000,
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
    print(f"\nartifacts written to {output_dir}")


if __name__ == "__main__":
    if sys.platform == "win32":
        with asyncio.Runner(
            loop_factory=asyncio.SelectorEventLoop
        ) as runner:
            runner.run(main())
    else:
        asyncio.run(main())
