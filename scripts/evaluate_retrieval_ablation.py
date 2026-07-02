from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.pool import close_pool
from app.evaluation.metrics import compare_retrieval_runs
from app.retrieval.hybrid_search import hybrid_search


def load_labels(path: Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return rows[:limit] if limit else rows


async def run_rankings(
    labels: list[dict[str, Any]], *, top_k: int, include_raptor: bool
) -> dict[str, list[str]]:
    rankings: dict[str, list[str]] = {}
    for label in labels:
        candidates = await hybrid_search(
            query=str(label["query"]),
            top_k=top_k,
            include_raptor=include_raptor,
        )
        rankings[str(label["case_id"])] = [candidate.job_id for candidate in candidates]
    return rankings


async def _main_async(args: argparse.Namespace) -> None:
    try:
        labels = load_labels(args.labels, limit=args.limit_cases)
        no_raptor = await run_rankings(
            labels, top_k=args.top_k, include_raptor=False
        )
        with_raptor = await run_rankings(
            labels, top_k=args.top_k, include_raptor=True
        )
        comparison = compare_retrieval_runs(labels, no_raptor, with_raptor, k=args.top_k)
        print(
            json.dumps(
                {
                    "metrics": comparison,
                    "rankings": {
                        "no_raptor": no_raptor,
                        "with_raptor": with_raptor,
                    },
                },
                indent=2,
            )
        )
    finally:
        await close_pool()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare no-RAPTOR vs with-RAPTOR retrieval Top-K metrics."
    )
    parser.add_argument(
        "--labels",
        type=Path,
        default=Path("data/eval/relevance_labels.jsonl"),
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--limit-cases", type=int)
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
