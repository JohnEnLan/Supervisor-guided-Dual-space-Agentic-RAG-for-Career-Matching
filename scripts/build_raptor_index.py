from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.pool import close_pool, get_pool
from app.retrieval.raptor import build_raptor_index


async def _main_async(args: argparse.Namespace) -> None:
    pool = await get_pool()
    try:
        stats = await build_raptor_index(
            pool,
            limit=args.limit,
            batch_size=args.batch_size,
            include_role_summaries=not args.no_role_summaries,
        )
        print(json.dumps(asdict(stats), indent=2))
    finally:
        await close_pool()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build RAPTOR-lite job and role summary nodes from job_chunks."
    )
    parser.add_argument("--limit", type=int, help="Limit number of jobs to index.")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument(
        "--no-role-summaries",
        action="store_true",
        help="Only build job summary nodes.",
    )
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
