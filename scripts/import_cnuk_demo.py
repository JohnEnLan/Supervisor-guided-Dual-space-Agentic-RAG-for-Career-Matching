"""Resumable bounded importer for the W5 CN/UK synthetic demo corpus."""

from __future__ import annotations

import argparse
import asyncio
import csv
import inspect
import json
import math
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Protocol

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings
from app.db.pool import close_pool, get_pool
from app.db.vector import to_pgvector
from app.llm.qwen_embed import embed_texts
from scripts.load_jobs import _build_chunk_specs
from scripts.transform_jobs_cn_uk import DATASET_ID


DEFAULT_WINDOW_SIZE = 500
DEFAULT_EMBED_WORKERS = 4
DEFAULT_EMBED_BATCH_SIZE = 10
DEFAULT_EMBED_TIMEOUT_SECONDS = 60.0
DEFAULT_EMBED_ATTEMPTS = 3
SPLITTER_VERSION = "load_jobs_splitter_v1:max_chars=1800"
EMBEDDING_BUILD_ID = "cnuk_demo_embedding_v1"


class FingerprintMismatch(RuntimeError):
    pass


@dataclass(frozen=True)
class EmbeddingFingerprint:
    model: str
    dimension: int
    splitter_version: str
    build_id: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ImportWindow:
    number: int
    row_start: int
    row_end: int
    rows: list[Mapping[str, str]]


@dataclass(frozen=True)
class WindowPayload:
    jobs: list[Mapping[str, str]]
    chunks: list[tuple[Any, ...]]


class WindowBackend(Protocol):
    async def ensure_window(
        self,
        window: ImportWindow,
        fingerprint: EmbeddingFingerprint,
    ) -> str: ...

    async def mark_running(self, window: ImportWindow) -> None: ...

    async def commit(
        self,
        window: ImportWindow,
        payload: WindowPayload,
    ) -> None: ...

    async def mark_failed(self, window: ImportWindow, error: str) -> None: ...


async def embed_batches_bounded(
    texts: list[str],
    *,
    embedder: Callable[[list[str]], Awaitable[list[list[float]]]] = embed_texts,
    dimension: int,
    workers: int = DEFAULT_EMBED_WORKERS,
    batch_size: int = DEFAULT_EMBED_BATCH_SIZE,
    timeout_seconds: float = DEFAULT_EMBED_TIMEOUT_SECONDS,
    max_attempts: int = DEFAULT_EMBED_ATTEMPTS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> list[list[float]]:
    if not texts:
        return []
    if workers < 1 or batch_size < 1 or max_attempts < 1:
        raise ValueError("workers, batch_size, and max_attempts must be positive")

    batches = [texts[start : start + batch_size] for start in range(0, len(texts), batch_size)]
    queue: asyncio.Queue[tuple[int, list[str]]] = asyncio.Queue()
    for index, batch in enumerate(batches):
        queue.put_nowait((index, batch))
    results: dict[int, list[list[float]]] = {}

    async def worker() -> None:
        while True:
            try:
                index, batch = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                for attempt in range(max_attempts):
                    try:
                        vectors = await asyncio.wait_for(
                            embedder(batch),
                            timeout=timeout_seconds,
                        )
                        if len(vectors) != len(batch):
                            raise ValueError("embedding response count mismatch")
                        if any(
                            len(vector) != dimension
                            or any(not math.isfinite(value) for value in vector)
                            for vector in vectors
                        ):
                            raise ValueError("embedding dimension or finite-value mismatch")
                        results[index] = vectors
                        break
                    except Exception:
                        if attempt + 1 >= max_attempts:
                            raise
                        await sleep(float(2**attempt))
            finally:
                queue.task_done()

    tasks = [
        asyncio.create_task(worker())
        for _ in range(min(workers, len(batches)))
    ]
    await asyncio.gather(*tasks)
    return [vector for index in range(len(batches)) for vector in results[index]]


async def run_resumable_import(
    rows: list[Mapping[str, str]],
    *,
    source_tag: str,
    fingerprint: EmbeddingFingerprint,
    backend: WindowBackend,
    process_window: Callable[[ImportWindow], Awaitable[WindowPayload]],
    window_size: int = DEFAULT_WINDOW_SIZE,
) -> dict[str, int]:
    if window_size < 1:
        raise ValueError("window_size must be positive")
    windows = [
        ImportWindow(
            number=number,
            row_start=start,
            row_end=min(start + window_size, len(rows)),
            rows=rows[start : start + window_size],
        )
        for number, start in enumerate(range(0, len(rows), window_size))
    ]
    skipped = completed = jobs_committed = chunks_committed = 0
    for window in windows:
        status = await backend.ensure_window(window, fingerprint)
        if status == "succeeded":
            skipped += 1
            continue
        await backend.mark_running(window)
        try:
            payload = await process_window(window)
            await backend.commit(window, payload)
        except Exception as exc:
            await backend.mark_failed(window, f"{type(exc).__name__}: {exc}")
            raise
        completed += 1
        jobs_committed += len(payload.jobs)
        chunks_committed += len(payload.chunks)
    return {
        "windows_total": len(windows),
        "windows_skipped": skipped,
        "windows_completed": completed,
        "jobs_committed": jobs_committed,
        "chunks_committed": chunks_committed,
    }


def current_embedding_fingerprint() -> EmbeddingFingerprint:
    source = inspect.getsource(_build_chunk_specs).encode("utf-8")
    import hashlib

    splitter_digest = hashlib.sha256(source).hexdigest()[:16]
    return EmbeddingFingerprint(
        model=settings.qwen_embed_model,
        dimension=settings.embed_dim,
        splitter_version=f"{SPLITTER_VERSION}:{splitter_digest}",
        build_id=EMBEDDING_BUILD_ID,
    )


def freeze_manifest_embedding_fingerprint(
    manifest_path: Path,
    fingerprint: EmbeddingFingerprint,
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = fingerprint.to_dict()
    existing = manifest.get("embedding_fingerprint") or {}
    populated = {value for value in existing.values() if value is not None}
    if populated and existing != expected:
        raise FingerprintMismatch(
            f"manifest embedding fingerprint mismatch: {existing!r} != {expected!r}"
        )
    if existing != expected:
        manifest["embedding_fingerprint"] = expected
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    return manifest


def read_converted_rows(path: Path, *, limit: int | None = None) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    selected = rows if limit is None else rows[:limit]
    if not selected:
        raise ValueError(f"no converted rows found in {path}")
    if any(row.get("demo_synthetic") != "true" for row in selected):
        raise ValueError("converted corpus contains a row without demo_synthetic=true")
    return selected


def _json_list(value: str) -> list[str]:
    parsed = json.loads(value or "[]")
    if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
        raise ValueError("expected a JSON string array")
    return parsed


async def build_window_payload(
    window: ImportWindow,
    *,
    fingerprint: EmbeddingFingerprint,
    embedder: Callable[[list[str]], Awaitable[list[list[float]]]] = embed_texts,
) -> WindowPayload:
    chunk_inputs: list[tuple[str, str, str, str]] = []
    for row in window.rows:
        chunk_source = {
            "title": row.get("title"),
            "company": row.get("company"),
            "location": row.get("location"),
            "role_cluster": row.get("role_cluster"),
            "degree_required": row.get("degree_required"),
            "min_years_exp": None,
            "responsibilities": row.get("responsibilities") or None,
            "required_skills": _json_list(row.get("required_skills", "[]")),
            "nice_to_have": _json_list(row.get("nice_to_have", "[]")),
            "raw_jd": row.get("raw_jd"),
        }
        for index, (field, content) in enumerate(_build_chunk_specs(chunk_source), start=1):
            chunk_inputs.append(
                (f"{row['job_id']}:{field}:{index}", row["job_id"], field, content)
            )

    vectors = await embed_batches_bounded(
        [content for _, _, _, content in chunk_inputs],
        embedder=embedder,
        dimension=fingerprint.dimension,
    )
    chunks = [
        (chunk_id, job_id, field, content, to_pgvector(vector))
        for (chunk_id, job_id, field, content), vector in zip(
            chunk_inputs,
            vectors,
            strict=True,
        )
    ]
    return WindowPayload(jobs=list(window.rows), chunks=chunks)


class PostgresWindowBackend:
    def __init__(
        self,
        pool,
        *,
        source_tag: str,
    ) -> None:
        self.pool = pool
        self.source_tag = source_tag

    async def ensure_window(
        self,
        window: ImportWindow,
        fingerprint: EmbeddingFingerprint,
    ) -> str:
        payload = json.dumps(fingerprint.to_dict(), sort_keys=True)
        async with self.pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO job_import_windows (
                    source_tag, window_number, row_start, row_end,
                    status, embedding_fingerprint
                )
                VALUES ($1, $2, $3, $4, 'pending', $5::jsonb)
                ON CONFLICT (source_tag, window_number) DO NOTHING
                """,
                self.source_tag,
                window.number,
                window.row_start,
                window.row_end,
                payload,
            )
            record = await connection.fetchrow(
                """
                SELECT status, embedding_fingerprint
                FROM job_import_windows
                WHERE source_tag = $1 AND window_number = $2
                """,
                self.source_tag,
                window.number,
            )
        stored = record["embedding_fingerprint"]
        if isinstance(stored, str):
            stored = json.loads(stored)
        if stored != fingerprint.to_dict():
            raise FingerprintMismatch(
                f"window {window.number} embedding fingerprint mismatch"
            )
        return str(record["status"])

    async def mark_running(self, window: ImportWindow) -> None:
        async with self.pool.acquire() as connection:
            updated = await connection.fetchval(
                """
                UPDATE job_import_windows
                SET status = 'running', attempts = attempts + 1,
                    started_at = now(), completed_at = NULL,
                    error_detail = NULL, updated_at = now()
                WHERE source_tag = $1 AND window_number = $2
                  AND status IN ('pending', 'failed', 'running')
                RETURNING TRUE
                """,
                self.source_tag,
                window.number,
            )
        if not updated:
            raise RuntimeError(f"window {window.number} could not be claimed")

    async def commit(
        self,
        window: ImportWindow,
        payload: WindowPayload,
    ) -> None:
        job_ids = [str(row["job_id"]) for row in payload.jobs]
        jobs = [
            (
                row["job_id"],
                row.get("title") or None,
                row.get("company") or None,
                row.get("location") or None,
                row.get("visa_sponsor") == "true",
                row.get("degree_required") or "unknown",
                None,
                row.get("role_cluster") or "other",
                False,
                None,
                row.get("responsibilities") or None,
                _json_list(row.get("required_skills", "[]")),
                _json_list(row.get("nice_to_have", "[]")),
                row.get("raw_jd") or "",
                True,
                row.get("country_code") or None,
                self.source_tag,
                row.get("source_metadata") or "{}",
            )
            for row in payload.jobs
        ]
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await connection.executemany(
                    """
                    INSERT INTO jobs (
                        job_id, title, company, location, visa_sponsor,
                        degree_required, min_years_exp, role_cluster, is_open,
                        deadline, responsibilities, required_skills, nice_to_have,
                        raw_jd, demo_synthetic, country_code, source_tag,
                        source_metadata
                    ) VALUES (
                        $1, $2, $3, $4, $5,
                        $6, $7, $8, $9,
                        $10::date, $11, $12::text[], $13::text[],
                        $14, $15, $16, $17, $18::jsonb
                    )
                    ON CONFLICT (job_id) DO UPDATE SET
                        title = EXCLUDED.title,
                        company = EXCLUDED.company,
                        location = EXCLUDED.location,
                        visa_sponsor = EXCLUDED.visa_sponsor,
                        degree_required = EXCLUDED.degree_required,
                        min_years_exp = EXCLUDED.min_years_exp,
                        role_cluster = EXCLUDED.role_cluster,
                        is_open = EXCLUDED.is_open,
                        deadline = EXCLUDED.deadline,
                        responsibilities = EXCLUDED.responsibilities,
                        required_skills = EXCLUDED.required_skills,
                        nice_to_have = EXCLUDED.nice_to_have,
                        raw_jd = EXCLUDED.raw_jd,
                        demo_synthetic = EXCLUDED.demo_synthetic,
                        country_code = EXCLUDED.country_code,
                        source_tag = EXCLUDED.source_tag,
                        source_metadata = EXCLUDED.source_metadata
                    """,
                    jobs,
                )
                await connection.execute(
                    "DELETE FROM job_chunks WHERE job_id = ANY($1::text[])",
                    job_ids,
                )
                await connection.executemany(
                    """
                    INSERT INTO job_chunks (chunk_id, job_id, field, content, embedding, tsv)
                    VALUES ($1, $2, $3, $4, $5::vector, to_tsvector('english', $4))
                    ON CONFLICT (chunk_id) DO UPDATE SET
                        job_id = EXCLUDED.job_id,
                        field = EXCLUDED.field,
                        content = EXCLUDED.content,
                        embedding = EXCLUDED.embedding,
                        tsv = EXCLUDED.tsv
                    """,
                    payload.chunks,
                )
                await connection.execute(
                    """
                    UPDATE job_import_windows
                    SET status = 'succeeded', job_count = $3, chunk_count = $4,
                        completed_at = now(), updated_at = now(), error_detail = NULL
                    WHERE source_tag = $1 AND window_number = $2
                    """,
                    self.source_tag,
                    window.number,
                    len(payload.jobs),
                    len(payload.chunks),
                )

    async def mark_failed(self, window: ImportWindow, error: str) -> None:
        async with self.pool.acquire() as connection:
            await connection.execute(
                """
                UPDATE job_import_windows
                SET status = 'failed', error_detail = $3, updated_at = now()
                WHERE source_tag = $1 AND window_number = $2
                """,
                self.source_tag,
                window.number,
                error[:2000],
            )


async def import_corpus(
    pool,
    *,
    input_path: Path,
    manifest_path: Path,
    source_tag: str,
    limit: int | None,
    embedder: Callable[[list[str]], Awaitable[list[list[float]]]] = embed_texts,
) -> dict[str, Any]:
    fingerprint = current_embedding_fingerprint()
    manifest = freeze_manifest_embedding_fingerprint(manifest_path, fingerprint)
    rows = read_converted_rows(input_path, limit=limit)
    backend = PostgresWindowBackend(pool, source_tag=source_tag)

    async def process(window: ImportWindow) -> WindowPayload:
        return await build_window_payload(
            window,
            fingerprint=fingerprint,
            embedder=embedder,
        )

    started = time.perf_counter()
    summary = await run_resumable_import(
        rows,
        source_tag=source_tag,
        fingerprint=fingerprint,
        backend=backend,
        process_window=process,
    )
    async with pool.acquire() as connection:
        counts = await connection.fetchrow(
            """
            SELECT count(*) AS jobs,
                   (SELECT count(*) FROM job_chunks c
                    JOIN jobs j ON j.job_id = c.job_id
                    WHERE j.source_tag = $1) AS chunks,
                   count(*) FILTER (WHERE is_open = TRUE) AS open_jobs
            FROM jobs
            WHERE source_tag = $1
            """,
            source_tag,
        )
    expected_jobs = len(rows)
    if int(counts["jobs"]) != expected_jobs:
        raise RuntimeError(
            f"job count mismatch for {source_tag}: {counts['jobs']} != {expected_jobs}"
        )
    if int(counts["open_jobs"]) != 0:
        raise RuntimeError("staged demo rows unexpectedly became retrieval-visible")
    summary.update(
        {
            "source_tag": source_tag,
            "jobs_total": int(counts["jobs"]),
            "chunks_total": int(counts["chunks"]),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "embedding_fingerprint": fingerprint.to_dict(),
            "manifest_chunk_count": manifest.get("chunk_count"),
        }
    )
    return summary


async def cleanup_trial(pool, *, source_tag: str) -> dict[str, int]:
    async with pool.acquire() as connection:
        async with connection.transaction():
            chunk_count = await connection.fetchval(
                """
                SELECT count(*) FROM job_chunks c
                JOIN jobs j ON j.job_id = c.job_id
                WHERE j.source_tag = $1
                """,
                source_tag,
            )
            job_count = await connection.fetchval(
                "SELECT count(*) FROM jobs WHERE source_tag = $1",
                source_tag,
            )
            await connection.execute(
                """
                DELETE FROM job_chunks
                WHERE job_id IN (SELECT job_id FROM jobs WHERE source_tag = $1)
                """,
                source_tag,
            )
            await connection.execute(
                "DELETE FROM jobs WHERE source_tag = $1",
                source_tag,
            )
            await connection.execute(
                "DELETE FROM job_import_windows WHERE source_tag = $1",
                source_tag,
            )
    return {"jobs_deleted": int(job_count), "chunks_deleted": int(chunk_count)}


async def _main_async(args: argparse.Namespace) -> None:
    pool = await get_pool()
    try:
        if args.cleanup_trial:
            result = await cleanup_trial(pool, source_tag=f"{DATASET_ID}_trial")
        else:
            limits = {"trial": 100, "preview": 3_000, "full": None}
            source_tag = f"{DATASET_ID}_trial" if args.stage == "trial" else DATASET_ID
            result = await import_corpus(
                pool,
                input_path=args.input,
                manifest_path=args.manifest,
                source_tag=source_tag,
                limit=limits[args.stage],
            )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    finally:
        await close_pool()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--stage", choices=("trial", "preview", "full"), default="trial")
    parser.add_argument("--cleanup-trial", action="store_true")
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
