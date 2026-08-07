# Career RAG Load Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add reproducible, privacy-safe validation for complex business paths, 20 concurrent runs, 200 read requests, retrieval parallelism, and provider semaphore limits without calling real external providers.

**Architecture:** Pure latency statistics live in `app/evaluation/load_validation.py`; integration tests inject deterministic async state, LLM, embedding, and persistence substitutes into the existing FastAPI and orchestrator boundaries. The tests measure the concurrency contracts that are semantically valid: hard-filter allow-list first, then BM25 and dense concurrently; explicit and implicit retrieval concurrently; provider calls within configured semaphores.

**Tech Stack:** Python 3.11+, asyncio, pytest, pytest-asyncio, httpx ASGITransport, FastAPI

## Global Constraints

- Never read, print, or upload `.env`; use `os.environ.setdefault` test placeholders only.
- Never call DeepSeek, DashScope, GitHub, GitLab, or another network service from load tests.
- Use `asyncio.gather`; do not introduce threading, multiprocessing, Celery, RQ, or a global business-state cache.
- Preserve SQL hard filtering as the prerequisite allow-list; do not parallelize work that depends on its result.
- Report only synthetic session/run IDs, counts, status codes, durations, and allow-list error codes.
- Millisecond values are report data, not brittle cross-machine pass/fail thresholds.

---

### Task 1: Deterministic Latency Summaries

**Files:**
- Create: `app/evaluation/load_validation.py`
- Test: `tests/test_load_validation_metrics.py`

**Interfaces:**
- Produces: `summarize_latencies(latencies_ms: list[float], *, success_count: int, elapsed_ms: float, peak_concurrency: int) -> LoadSummary`.
- Produces: immutable `LoadSummary` fields `request_count`, `success_count`, `failure_count`, `success_rate`, `throughput_rps`, `p50_ms`, `p95_ms`, `max_ms`, and `peak_concurrency`.

- [ ] **Step 1: Write failing metric tests**

```python
from app.evaluation.load_validation import summarize_latencies


def test_summarize_latencies_uses_nearest_rank_percentiles() -> None:
    summary = summarize_latencies(
        [10.0, 20.0, 30.0, 40.0, 100.0],
        success_count=4,
        elapsed_ms=200.0,
        peak_concurrency=3,
    )
    assert summary.request_count == 5
    assert summary.failure_count == 1
    assert summary.success_rate == 0.8
    assert summary.throughput_rps == 25.0
    assert summary.p50_ms == 30.0
    assert summary.p95_ms == 100.0
    assert summary.max_ms == 100.0
    assert summary.peak_concurrency == 3


def test_summarize_latencies_handles_an_empty_sample() -> None:
    summary = summarize_latencies([], success_count=0, elapsed_ms=0, peak_concurrency=0)
    assert summary.request_count == 0
    assert summary.success_rate == 0.0
    assert summary.throughput_rps == 0.0
    assert summary.p95_ms == 0.0
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `\.venv\Scripts\python.exe -m pytest tests\test_load_validation_metrics.py -q`

Expected: FAIL because `app.evaluation.load_validation` does not exist.

- [ ] **Step 3: Implement the pure summary module**

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import ceil


@dataclass(frozen=True)
class LoadSummary:
    request_count: int
    success_count: int
    failure_count: int
    success_rate: float
    throughput_rps: float
    p50_ms: float
    p95_ms: float
    max_ms: float
    peak_concurrency: int

    def as_public_dict(self) -> dict[str, int | float]:
        return asdict(self)


def _nearest_rank(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, ceil(quantile * len(ordered)) - 1)
    return round(ordered[index], 3)


def summarize_latencies(
    latencies_ms: list[float],
    *,
    success_count: int,
    elapsed_ms: float,
    peak_concurrency: int,
) -> LoadSummary:
    request_count = len(latencies_ms)
    bounded_success = min(max(success_count, 0), request_count)
    return LoadSummary(
        request_count=request_count,
        success_count=bounded_success,
        failure_count=request_count - bounded_success,
        success_rate=round(bounded_success / request_count, 4) if request_count else 0.0,
        throughput_rps=round(request_count / (elapsed_ms / 1000), 3) if elapsed_ms > 0 else 0.0,
        p50_ms=_nearest_rank(latencies_ms, 0.50),
        p95_ms=_nearest_rank(latencies_ms, 0.95),
        max_ms=round(max(latencies_ms), 3) if latencies_ms else 0.0,
        peak_concurrency=max(peak_concurrency, 0),
    )
```

- [ ] **Step 4: Run tests and verify GREEN**

Run: `\.venv\Scripts\python.exe -m pytest tests\test_load_validation_metrics.py -q`

Expected: 2 tests pass.

- [ ] **Step 5: Commit metrics**

```powershell
git add app/evaluation/load_validation.py tests/test_load_validation_metrics.py
git commit -m "test: add deterministic load metrics"
```

### Task 2: Twenty Concurrent Run Isolation

**Files:**
- Modify: `tests/test_api_concurrency.py`

**Interfaces:**
- Consumes: `summarize_latencies` from Task 1 and `run_persisted_agentic_match_run(run_id: str)`.
- Produces: a 20-run isolation test with ten sessions, mixed goals, exact per-run evidence, and measured timings.

- [ ] **Step 1: Scale the existing v1 run fixture before changing production code**

Replace the three-entry `run_specs` literal in `test_two_sessions_three_v1_runs_keep_snapshots_and_results_isolated` with:

```python
run_specs = {
    f"run-{index:02d}": (
        f"session-{index % 10:02d}",
        (
            f"Target Data Analyst at Company {index}"
            if index % 2 == 0
            else f"Explore evidence-backed direction {index}"
        ),
    )
    for index in range(20)
}
```

Wrap each orchestrator call with `perf_counter`, return `(run_id, elapsed_ms)`, pass the latencies to `summarize_latencies`, and assert:

```python
assert set(results) == set(run_specs)
assert summary.request_count == 20
assert summary.success_count == 20
assert summary.failure_count == 0
assert summary.peak_concurrency == 20
assert all(results[run_id]["recommended_roles"][0]["job_id"] == f"job-{run_id}" for run_id in run_specs)
```

- [ ] **Step 2: Run the focused concurrency test**

Run: `\.venv\Scripts\python.exe -m pytest tests\test_api_concurrency.py -q`

Expected: all concurrency tests pass; no production change is allowed to make a synthetic isolation failure disappear.

- [ ] **Step 3: Commit the expanded isolation contract**

```powershell
git add tests/test_api_concurrency.py
git commit -m "test: exercise twenty isolated matching runs"
```

### Task 3: Two Hundred Read Requests and Competing Execute

**Files:**
- Modify: `tests/test_api_concurrency.py`

**Interfaces:**
- Consumes: FastAPI `app`, `httpx.ASGITransport`, `RunStatusResponse`, and Task 1 summaries.
- Produces: an API-level 200-request read benchmark and a same-run execute race contract.

- [ ] **Step 1: Add a 200-request status test**

Monkeypatch `app.api.v1.runs.get_run` to return a completed synthetic `MatchRun` whose `run_id` is copied from the request. Use 20 async workers controlled by `asyncio.Semaphore(20)` to issue 200 GET requests to `/api/v1/runs/load-{index}/status`. Measure each request with `perf_counter` and assert:

```python
assert all(response.status_code == 200 for response in responses)
assert {response.json()["run_id"] for response in responses} == {f"load-{index}" for index in range(200)}
assert summary.request_count == 200
assert summary.failure_count == 0
assert summary.peak_concurrency <= 20
assert summary.peak_concurrency > 1
```

- [ ] **Step 2: Add a same-run execute race test**

Monkeypatch `app.api.v1.runs.queue_run` with an async lock and a `queued` flag. The first call returns a synthetic queued `MatchRun`; the other 19 calls raise `RunConflict`. Monkeypatch the background executor to a no-op. Send 20 concurrent POST requests with the same canonical plan version/hash and assert one 202, nineteen 409 responses, and one queued transition.

- [ ] **Step 3: Run the focused tests**

Run: `\.venv\Scripts\python.exe -m pytest tests\test_api_concurrency.py -q -s`

Expected: 20-run isolation, 200 reads, and competing execute all pass; printed summaries contain counts and latencies only.

- [ ] **Step 4: Commit API load contracts**

```powershell
git add tests/test_api_concurrency.py
git commit -m "test: validate concurrent read and execute load"
```

### Task 4: Retrieval Parallelism and Provider Limits

**Files:**
- Modify: `tests/test_hybrid_search.py`
- Modify: `tests/test_dual_space_search.py`
- Modify: `tests/test_llm_concurrency.py`

**Interfaces:**
- Consumes: `hybrid_search`, `dual_space_search`, `deepseek.chat`, and `qwen_embed.embed_texts`.
- Produces: measured overlap assertions and peak active provider counts.

- [ ] **Step 1: Characterize BM25 and dense overlap**

Monkeypatch `_hard_filter_ids` to return `{"job-1"}`, then patch `_bm25` and `_dense` with a two-party rendezvous using an `asyncio.Event`. Patch metadata and evidence fetches with deterministic payloads. Call `hybrid_search` through `asyncio.wait_for(..., timeout=0.5)` and assert both branches entered before either completed.

This test must keep the hard filter before the rendezvous because BM25 and dense consume its allow-list.

- [ ] **Step 2: Add elapsed-time evidence for explicit and implicit overlap**

Extend `test_explicit_and_implicit_io_start_concurrently` so both branches sleep for 50ms after the rendezvous, measure wall-clock duration, and assert duration is below 90ms. Keep the event assertion so a fast machine cannot pass on timing alone.

- [ ] **Step 3: Add Qwen semaphore coverage**

Add a fake embedding client equivalent to the existing DeepSeek fake, replace `qwen_embed._sem` with `asyncio.Semaphore(3)`, issue nine `embed_texts` calls, and assert `max_active == 3`. The fake response data must contain one embedding per input string.

- [ ] **Step 4: Run parallelism tests**

Run: `\.venv\Scripts\python.exe -m pytest tests\test_hybrid_search.py tests\test_dual_space_search.py tests\test_llm_concurrency.py -q`

Expected: retrieval overlap, cancellation propagation, implicit fallback, DeepSeek limit, and Qwen limit pass without network access.

- [ ] **Step 5: Commit parallelism coverage**

```powershell
git add tests/test_hybrid_search.py tests/test_dual_space_search.py tests/test_llm_concurrency.py
git commit -m "test: measure retrieval and provider parallelism"
```

### Task 5: Complex Business Matrix and Final Report

**Files:**
- Create after measurements: `docs/validation/2026-07-14-load-validation-report.md`
- Modify only when a failing regression test identifies a real defect.

**Interfaces:**
- Consumes: existing targeted/explore, run lifecycle, result projector, dual-space, monitoring, and concurrency tests.
- Produces: a privacy-safe report containing commands, environment class, request counts, success rates, P50/P95/max, and discovered defects.

- [ ] **Step 1: Run the complex business matrix**

```powershell
\.venv\Scripts\python.exe -m pytest tests\test_intent_consultation.py tests\test_match_brief.py tests\test_api_v1.py tests\test_result_projector.py tests\test_public_trace.py tests\test_dual_space_search.py tests\test_api_concurrency.py -q -s
```

Expected: targeted/explore, clarification bound, stale plan, evidence gate, warning result, dual-space degradation, and isolation tests pass.

- [ ] **Step 2: Run the full backend regression**

Run: `\.venv\Scripts\python.exe -m pytest -q`

Expected: all tests pass with no new warning category.

- [ ] **Step 3: Write the measured report**

The report must contain these fixed headings and fill them only with exact fresh command output:

```markdown
# Career RAG Load Validation Report

## Scope and Safety
## Complex Business Scenarios
## Concurrent Run Isolation
## Read API Load
## Retrieval Parallelism
## Provider Semaphore Limits
## P50, P95, Throughput, and Failures
## Defects Found and Resolved
## Remaining Production Limitations
```

State explicitly that dependencies were deterministic substitutes, no `.env` value was read, and results are a local engineering baseline rather than internet-scale capacity claims.

- [ ] **Step 4: Run a redacted secret scan**

Run `git ls-files .env .env.*`, `git check-ignore -v .env`, and filename-only `git grep -l` scans for common API key and private-key signatures. The output must show only `.env.example` as tracked and no real signature matches.

- [ ] **Step 5: Commit validation evidence**

```powershell
git add app/evaluation/load_validation.py tests/test_load_validation_metrics.py tests/test_api_concurrency.py tests/test_hybrid_search.py tests/test_dual_space_search.py tests/test_llm_concurrency.py docs/validation/2026-07-14-load-validation-report.md
git commit -m "test: validate complex concurrent matching load"
```

### Task 6: Review, Verify, and Publish

**Files:**
- Review all files changed by both implementation plans.

**Interfaces:**
- Consumes: completed onboarding and load-validation work.
- Produces: reviewed commits on both `origin/codex/week3-reoptimization` and `gitlab/codex/week3-reoptimization`.

- [ ] **Step 1: Request an independent code review**

Provide the reviewer with the approved design, both plans, base commit `8f84e47`, current HEAD, and require all Critical/Important findings to be fixed before publication.

- [ ] **Step 2: Run final combined verification**

```powershell
\.venv\Scripts\python.exe -m pytest -q
cd frontend
npm.cmd run api:check
npm.cmd test
npm.cmd run typecheck
npm.cmd run build
npm.cmd run e2e
```

Expected: every command exits 0 with fresh output.

- [ ] **Step 3: Verify repository scope**

Run `git status -sb`, `git diff --check`, and inspect the commits. Confirm unrelated untracked planning/output files remain uncommitted and `.env` is ignored.

- [ ] **Step 4: Push GitHub and GitLab**

```powershell
git push origin codex/week3-reoptimization
git push gitlab codex/week3-reoptimization
```

- [ ] **Step 5: Verify both remote refs**

Run `git ls-remote origin refs/heads/codex/week3-reoptimization` and the equivalent GitLab command. Both hashes must equal local `git rev-parse HEAD`.
