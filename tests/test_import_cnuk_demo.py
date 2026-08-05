from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest

from scripts.import_cnuk_demo import (
    EmbeddingFingerprint,
    FingerprintMismatch,
    ImportWindow,
    WindowPayload,
    cleanup_trial,
    embed_batches_bounded,
    run_resumable_import,
)


def _fingerprint(build_id: str = "build-v1") -> EmbeddingFingerprint:
    return EmbeddingFingerprint(
        model="text-embedding-v4",
        dimension=3,
        splitter_version="load_jobs_splitter_v1:max_chars=1800",
        build_id=build_id,
    )


@pytest.mark.asyncio
async def test_embedding_pool_batches_ten_retries_and_preserves_order() -> None:
    calls: dict[tuple[str, ...], int] = {}
    sleeps: list[float] = []

    async def embedder(texts: list[str]) -> list[list[float]]:
        key = tuple(texts)
        calls[key] = calls.get(key, 0) + 1
        if texts[0] == "text-10" and calls[key] == 1:
            raise TimeoutError("transient")
        await asyncio.sleep(0)
        return [[float(text.removeprefix("text-")), 1.0, 2.0] for text in texts]

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    vectors = await embed_batches_bounded(
        [f"text-{index}" for index in range(25)],
        embedder=embedder,
        dimension=3,
        workers=4,
        batch_size=10,
        timeout_seconds=1,
        max_attempts=3,
        sleep=fake_sleep,
    )

    assert [vector[0] for vector in vectors] == list(map(float, range(25)))
    assert sorted(len(batch) for batch in calls) == [5, 10, 10]
    assert calls[tuple(f"text-{index}" for index in range(10, 20))] == 2
    assert sleeps == [1.0]


class MemoryBackend:
    def __init__(self):
        self.records = {}
        self.committed: list[int] = []
        self.failed: list[int] = []

    async def ensure_window(self, window: ImportWindow, fingerprint):
        existing = self.records.get(window.number)
        if existing and existing["fingerprint"] != fingerprint:
            raise FingerprintMismatch("fingerprint mismatch")
        if existing is None:
            existing = {"status": "pending", "fingerprint": fingerprint}
            self.records[window.number] = existing
        return existing["status"]

    async def mark_running(self, window: ImportWindow):
        self.records[window.number]["status"] = "running"

    async def commit(self, window: ImportWindow, payload: WindowPayload):
        self.records[window.number].update(
            status="succeeded",
            job_count=len(payload.jobs),
            chunk_count=len(payload.chunks),
        )
        self.committed.append(window.number)

    async def mark_failed(self, window: ImportWindow, error: str):
        self.records[window.number].update(status="failed", error=error)
        self.failed.append(window.number)


@pytest.mark.asyncio
async def test_resumable_windows_skip_success_and_resume_after_failure() -> None:
    backend = MemoryBackend()
    processed: list[int] = []
    fail_once = True

    async def process(window: ImportWindow) -> WindowPayload:
        nonlocal fail_once
        processed.append(window.number)
        if window.number == 1 and fail_once:
            fail_once = False
            raise RuntimeError("embedding unavailable")
        return WindowPayload(
            jobs=list(window.rows),
            chunks=[(f"chunk-{window.number}",)],
        )

    rows = [{"job_id": f"job-{index}"} for index in range(1_201)]
    with pytest.raises(RuntimeError, match="embedding unavailable"):
        await run_resumable_import(
            rows,
            source_tag="demo",
            fingerprint=_fingerprint(),
            backend=backend,
            process_window=process,
            window_size=500,
        )

    assert backend.committed == [0]
    assert backend.failed == [1]

    summary = await run_resumable_import(
        rows,
        source_tag="demo",
        fingerprint=_fingerprint(),
        backend=backend,
        process_window=process,
        window_size=500,
    )

    assert processed == [0, 1, 1, 2]
    assert backend.committed == [0, 1, 2]
    assert summary == {
        "windows_total": 3,
        "windows_skipped": 1,
        "windows_completed": 2,
        "jobs_committed": 701,
        "chunks_committed": 2,
    }


@pytest.mark.asyncio
async def test_resume_rejects_changed_embedding_fingerprint() -> None:
    backend = MemoryBackend()

    async def process(window: ImportWindow) -> WindowPayload:
        return WindowPayload(jobs=list(window.rows), chunks=[])

    rows = [{"job_id": "job-1"}]
    await run_resumable_import(
        rows,
        source_tag="demo",
        fingerprint=_fingerprint(),
        backend=backend,
        process_window=process,
    )

    with pytest.raises(FingerprintMismatch):
        await run_resumable_import(
            rows,
            source_tag="demo",
            fingerprint=_fingerprint("build-v2"),
            backend=backend,
            process_window=process,
        )


@pytest.mark.asyncio
async def test_trial_cleanup_removes_isolated_resume_markers() -> None:
    class Connection:
        def __init__(self):
            self.commands = []

        @asynccontextmanager
        async def transaction(self):
            yield

        async def fetchval(self, sql, *_args):
            return 4 if "job_chunks" in sql else 2

        async def execute(self, sql, *args):
            self.commands.append((sql, args))

    class Pool:
        def __init__(self):
            self.connection = Connection()

        @asynccontextmanager
        async def acquire(self):
            yield self.connection

    pool = Pool()

    result = await cleanup_trial(pool, source_tag="demo-trial")

    assert result == {"jobs_deleted": 2, "chunks_deleted": 4}
    assert any(
        "DELETE FROM job_import_windows" in sql
        for sql, _args in pool.connection.commands
    )
