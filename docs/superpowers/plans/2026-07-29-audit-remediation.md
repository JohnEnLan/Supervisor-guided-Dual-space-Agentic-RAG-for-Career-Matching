# Audit Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair all approved high/medium findings and remove the seven
approved dead/duplicate code targets while retaining the existing behavior and
green backend/frontend baselines.

**Architecture:** Keep the existing FastAPI/asyncpg/plain-function harness.
Apply isolated changes at module boundaries: validate inputs before retrieval,
lock and mutate state in PostgreSQL transactions, make temporary files unique
and lifecycle-bound, ground normalization/evaluation in real evidence, and
centralize only the identical pgvector serialization primitive.

**Tech Stack:** Python 3.11, FastAPI, asyncio, asyncpg, PostgreSQL/pgvector,
Pydantic, pytest, React/TypeScript/Vite/Vitest.

## Global Constraints

- State is never stored in process-global application variables.
- Concurrency uses asyncio, not threads or processes.
- Shared state stays keyed by `session_id` in PostgreSQL.
- Hard filters remain deterministic SQL/metadata logic.
- LLM-derived resume facts must trace to retained evidence spans.
- External LLM/embedding calls remain semaphore-limited.
- No P2 expansion; RAPTOR behavior is unchanged except the approved evaluation
  correction and shared serialization helper.
- One module is changed and verified before starting the next.

---

### Task 1: Establish baselines and test map

**Files:** Read-only inventory of `app/`, `scripts/`, `tests/`, and `frontend/`.

- [ ] Run the required backend command and record exact collected/passed count.
- [ ] Run frontend typecheck, tests, and build and record their outputs.
- [ ] Map every finding to its existing tests and choose the smallest new
  regression-test location.

### Task 2: Foundation validation and concurrency guards

**Files:**
- Modify: `app/config.py`, `app/db/pool.py`, `app/agents/base.py`
- Test: focused existing config, pool, and agent tests under `tests/`

- [ ] Add one failing test for zero concurrency settings, then enforce
  `Field(ge=1)` and rerun it.
- [ ] Add one failing concurrent-initialization test, then add an
  `asyncio.Lock` plus double-check and rerun it.
- [ ] Add one failing legal-non-object JSON test, then require `dict` after JSON
  parsing and rerun it.

### Task 3: Resume intake evidence integrity

**Files:**
- Modify: `app/normalization/resume_intake.py`
- Test: normalization tests under `tests/`

- [ ] Add a failing DOCX ordering test containing interleaved paragraphs and
  tables; implement ordered block/cell traversal; rerun it.
- [ ] Add failing tests showing the LLM prompt receives only retained span text
  and invented/missing span IDs cannot become verified facts.
- [ ] Implement minimal span-ID validation and an explicit unverified policy,
  then rerun the normalization suite.

### Task 4: Retrieval input and hydration correctness

**Files:**
- Modify: `app/retrieval/hybrid_search.py`
- Test: hybrid retrieval tests under `tests/`

- [ ] Add failing cases for string-as-list constraints and negative/oversized
  `top_k`; implement type checks and bounded clamping.
- [ ] Add a failing case where an unhydrated late fused row could enter Top-K;
  rerank only the hydrated subset.
- [ ] Rerun the retrieval suite.

### Task 5: Atomic state operations and production callers

**Files:**
- Modify: `app/db/state_store.py`, `app/api/v1/sessions.py`,
  `app/agents/orchestrator.py`, and only the production callers proven to save
  stale snapshots
- Test: state-store/session/orchestrator tests under `tests/`

- [ ] Add a transaction-spy test proving normalized resume state and
  `resume_version` update occur under one acquired connection, transaction, and
  locked session row.
- [ ] Implement one atomic state-store API for that compound mutation and adopt
  it from the session endpoint.
- [ ] Add interleaving regression tests for each long-running production path
  that currently writes a stale whole snapshot.
- [ ] Replace those writes with `mutate_state_atomically` field-level mutators
  and rerun each focused suite.

### Task 6: API upload and task lifecycle

**Files:**
- Modify: `app/api/routes.py`, `app/api/v1/runs.py`, application startup module
- Test: API route/run tests under `tests/`

- [ ] Add failing upload tests for colliding session IDs, repeated uploads,
  oversize bodies, chunked writes, and temp-file cleanup on success/failure.
- [ ] Implement full-session hashing plus random upload IDs, bounded streaming,
  immutable task paths, and background `finally` cleanup.
- [ ] Add a failing test for an exception on the first legacy background
  state operation; wrap the whole task and persist a failure fallback.
- [ ] Add failing startup recovery tests for old queued/running rows; implement
  a bounded stale-run database update during lifespan startup.

### Task 7: Avoid-role enforcement

**Files:**
- Modify: `app/agents/orchestrator.py`
- Test: orchestrator tests under `tests/`

- [ ] Add a failing candidate test covering case-insensitive deterministic
  role exclusion and a corresponding `filter_log` entry.
- [ ] Implement the post-candidate filter without an LLM call and rerun the
  orchestrator suite.

### Task 8: Evaluation correctness

**Files:**
- Modify: `scripts/evaluate_system.py`, `app/evaluation/metrics.py`
- Test: evaluation/metrics tests under `tests/`

- [ ] Add a failing latent-group test requiring `dual_space_search` and proving
  RAPTOR configuration is not mutated between experiment groups.
- [ ] Add failing faithfulness tests requiring real recommended-role
  explanation/citations and `not_evaluated` when absent.
- [ ] Add failing hard-filter tests for every relevant column and a separate
  unknown count.
- [ ] Add a failing per-job evidence test, then scope cited evidence by job ID.
- [ ] Implement each minimum correction and rerun evaluation tests.

### Task 9: Loader lifecycle

**Files:**
- Modify: `scripts/load_jobs.py`
- Test: loader tests under `tests/`

- [ ] Add a failing CLI orchestration test proving `--stage all` uses one event
  loop and closes the pool in `finally`.
- [ ] Implement `_main_async`, keep stages sequential, and rerun loader tests.
- [ ] Remove the zero-reference `JobChunk` after static reference verification.

### Task 10: Shared pgvector serializer

**Files:**
- Create: one helper under `app/db/`
- Modify: `app/retrieval/hybrid_search.py`, `app/retrieval/raptor.py`,
  `app/memory/case_base.py`, `scripts/load_jobs.py`
- Test: serializer call-site tests under `tests/`

- [ ] Add direct edge-case tests for the canonical serializer and observe RED.
- [ ] Implement the helper with the exact existing wire format.
- [ ] Migrate one consumer at a time, running its focused suite after each.
- [ ] Verify `rg` finds no duplicate serializer definitions.

### Task 11: Approved dead-code removals

**Files:**
- Modify: `frontend/src/app/App.tsx`, `app/domain/match_brief.py`,
  `app/memory/case_base.py`, `app/memory/private_memory.py`,
  `app/agents/orchestrator.py`, `tests/test_orchestrator_persistence.py`

- [ ] For each target, verify zero production references with `rg`.
- [ ] Run its closest characterization/focused tests before deletion.
- [ ] Apply Fowler “Remove Dead Code” to D1-D6 one module at a time and rerun
  the focused tests after each.
- [ ] Remove only the D6 tests tied exclusively to the deleted entrypoints.

### Task 12: Final verification and report

**Files:** All changed files; no new behavior.

- [ ] Run the exact backend command from the user.
- [ ] Run frontend typecheck, test, and build.
- [ ] Review the diff against H1-H11, M1-M9, D1-D7 and protected items.
- [ ] Report per-item fix, any minimal-safe trade-off, changed files, dead-code
  measurements, and exact command outputs.
