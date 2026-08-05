"""Strict-offline transactional cutover for the W5 CN/UK demo corpus."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
from typing import Literal

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.pool import close_pool, get_pool
from scripts.import_cnuk_demo import (
    FingerprintMismatch,
    current_embedding_fingerprint,
)
from scripts.transform_jobs_cn_uk import DATASET_ID


Direction = Literal["forward", "rollback"]


class CutoverBlocked(RuntimeError):
    pass


async def _validate_offline_state(
    connection,
    *,
    source_tag: str,
    expected_jobs: int,
    expected_chunks: int,
) -> None:
    await connection.execute(
        "SELECT pg_advisory_xact_lock(hashtext('cnuk_demo_cutover_v1'))"
    )
    active_runs = int(
        await connection.fetchval(
            """
            SELECT count(*)
            FROM match_runs
            WHERE lower(status) IN ('queued', 'running')
            """
        )
    )
    if active_runs:
        raise CutoverBlocked(f"cutover refused: {active_runs} active runs")

    jobs = int(
        await connection.fetchval(
            "SELECT count(*) FROM jobs WHERE source_tag = $1",
            source_tag,
        )
    )
    chunks = int(
        await connection.fetchval(
            """
            SELECT count(*)
            FROM job_chunks c
            JOIN jobs j ON j.job_id = c.job_id
            WHERE j.source_tag = $1
            """,
            source_tag,
        )
    )
    if jobs != expected_jobs or chunks != expected_chunks:
        raise CutoverBlocked(
            "cutover count mismatch: "
            f"jobs={jobs}/{expected_jobs}, chunks={chunks}/{expected_chunks}"
        )


async def _flip(
    connection,
    *,
    direction: Direction,
    source_tag: str,
    old_source_tags: tuple[str, ...],
) -> None:
    if direction == "forward":
        await connection.execute(
            """
            UPDATE jobs
            SET is_open = FALSE
            WHERE source_tag IS NULL OR source_tag = ANY($1::text[])
            """,
            list(old_source_tags),
        )
        await connection.execute(
            "UPDATE jobs SET is_open = TRUE WHERE source_tag = $1",
            source_tag,
        )
        expected_open = True
    else:
        await connection.execute(
            "UPDATE jobs SET is_open = FALSE WHERE source_tag = $1",
            source_tag,
        )
        await connection.execute(
            """
            UPDATE jobs
            SET is_open = TRUE
            WHERE source_tag IS NULL OR source_tag = ANY($1::text[])
            """,
            list(old_source_tags),
        )
        expected_open = False
    state_matches = await connection.fetchval(
        """
        SELECT bool_and(is_open = $2)
        FROM jobs
        WHERE source_tag = $1
        """,
        source_tag,
        expected_open,
    )
    if state_matches is not True:
        raise CutoverBlocked("post-cutover visibility verification failed")


async def switch_corpus(
    pool,
    *,
    direction: Direction,
    source_tag: str = DATASET_ID,
    expected_jobs: int,
    expected_chunks: int,
    old_source_tags: tuple[str, ...] = (),
) -> dict[str, int | str]:
    async with pool.acquire() as connection:
        async with connection.transaction():
            await _validate_offline_state(
                connection,
                source_tag=source_tag,
                expected_jobs=expected_jobs,
                expected_chunks=expected_chunks,
            )
            await _flip(
                connection,
                direction=direction,
                source_tag=source_tag,
                old_source_tags=old_source_tags,
            )
    return {
        "direction": direction,
        "source_tag": source_tag,
        "jobs": expected_jobs,
        "chunks": expected_chunks,
    }


async def rehearse_both_directions(
    pool,
    *,
    source_tag: str,
    expected_jobs: int,
    expected_chunks: int,
    old_source_tags: tuple[str, ...] = (),
) -> dict[str, int | str]:
    """Flip forward and back inside one transaction, committing restored state."""
    async with pool.acquire() as connection:
        async with connection.transaction():
            await _validate_offline_state(
                connection,
                source_tag=source_tag,
                expected_jobs=expected_jobs,
                expected_chunks=expected_chunks,
            )
            await _flip(
                connection,
                direction="forward",
                source_tag=source_tag,
                old_source_tags=old_source_tags,
            )
            await _flip(
                connection,
                direction="rollback",
                source_tag=source_tag,
                old_source_tags=old_source_tags,
            )
    return {
        "direction": "forward_then_rollback_rehearsal",
        "source_tag": source_tag,
        "jobs": expected_jobs,
        "chunks": expected_chunks,
    }


def _manifest_counts_and_fingerprint(path: Path) -> tuple[int, int]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    expected_fingerprint = current_embedding_fingerprint().to_dict()
    if manifest.get("embedding_fingerprint") != expected_fingerprint:
        raise FingerprintMismatch("cutover embedding fingerprint does not match runtime")
    return int(manifest["row_count"]), int(manifest["chunk_count"])


async def _main_async(args: argparse.Namespace) -> None:
    expected_jobs, expected_chunks = _manifest_counts_and_fingerprint(args.manifest)
    if args.expected_jobs is not None:
        expected_jobs = args.expected_jobs
    if args.expected_chunks is not None:
        expected_chunks = args.expected_chunks
    pool = await get_pool()
    try:
        kwargs = {
            "source_tag": args.source_tag,
            "expected_jobs": expected_jobs,
            "expected_chunks": expected_chunks,
            "old_source_tags": tuple(args.old_source_tag),
        }
        if args.rehearse:
            result = await rehearse_both_directions(pool, **kwargs)
        else:
            result = await switch_corpus(pool, direction=args.direction, **kwargs)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    finally:
        await close_pool()


def build_parser(*, default_direction: Direction = "forward") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--source-tag", default=DATASET_ID)
    parser.add_argument("--old-source-tag", action="append", default=[])
    parser.add_argument(
        "--direction",
        choices=("forward", "rollback"),
        default=default_direction,
    )
    parser.add_argument("--rehearse", action="store_true")
    parser.add_argument("--expected-jobs", type=int)
    parser.add_argument("--expected-chunks", type=int)
    return parser


def main(*, default_direction: Direction = "forward") -> None:
    args = build_parser(default_direction=default_direction).parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
