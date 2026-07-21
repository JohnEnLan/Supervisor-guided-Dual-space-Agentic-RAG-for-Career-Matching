# RAPTOR-lite Leaf Propagation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Propagate optional RAPTOR summary recall through relevant original job chunks, aggregate to jobs, and publish only original JD evidence.

**Architecture:** Add an offline node-to-chunk mapping, query mapped leaves with the existing query embedding, apply bounded depth/fan-out propagation, collapse to `job_id`, and then use the existing job-level RRF path. BM25/dense remain unchanged and RAPTOR stays opt-in.

**Tech Stack:** Python 3.11+, PostgreSQL/pgvector SQL, asyncpg, asyncio, pytest.

## Global Constraints

- RAPTOR remains optional P2 and disabled in the normal v1 product path.
- SQL hard filters apply before any RAPTOR contribution reaches a job.
- Final JD evidence must come from `job_chunks`, never summary text.
- No complete RAPTOR tree, knowledge graph, skill graph, or cross-encoder.
- Run the Supervisor Harness module tests before changing this module.

---

### Task 1: Persist node-to-chunk lineage

**Files:**
- Modify: `app/db/schema.sql`
- Create: `app/db/migrations/0004_raptor_node_chunks.sql`
- Modify: `app/retrieval/raptor.py`
- Modify: `tests/test_raptor.py`

**Interfaces:**
- `RaptorNode` gains `source_chunk_ids: list[str]`.
- The builder writes `(node_id, chunk_id, job_id, depth, leaf_rank)` rows to `raptor_node_chunks` after upserting nodes.

- [ ] **Step 1: Write failing node-lineage and schema tests** for job and role summary mappings.
- [ ] **Step 2: Run `pytest tests/test_raptor.py -q`** and confirm the lineage assertions fail.
- [ ] **Step 3: Add the mapping schema and minimal builder upsert/delete logic.**
- [ ] **Step 4: Run `pytest tests/test_raptor.py -q`** and confirm the builder contract passes.

### Task 2: Propagate node recall to relevant original leaves

**Files:**
- Modify: `app/retrieval/raptor.py`
- Modify: `tests/test_raptor.py`

**Interfaces:**
- Produces pure `propagate_raptor_hits(...) -> list[RaptorHit]` where each hit contains `node_id`, original `chunk_id`, `job_id`, field, and propagated score.
- `search_raptor_nodes` fetches mapped leaves and returns only propagated original-chunk hits.

- [ ] **Step 1: Write failing tests** for allowed-job filtering, depth decay, role-job diversity, fan-out normalization, combined duplicate-chunk contribution, and Top-N limits.
- [ ] **Step 2: Run the propagation tests** and verify they fail because propagation is absent.
- [ ] **Step 3: Implement pure propagation and the second async leaf fetch** using the existing query vector.
- [ ] **Step 4: Run `pytest tests/test_raptor.py -q`** and confirm all RAPTOR unit tests pass.

### Task 3: Fuse at job level and hydrate only original evidence

**Files:**
- Modify: `app/retrieval/hybrid_search.py`
- Modify: `tests/test_hybrid_search.py`

**Interfaces:**
- RAPTOR `RaptorHit.chunk_id` becomes the `ChunkHit.chunk_id` used for evidence.
- RAPTOR leaf contributions are summed per job before their rank list enters `rrf_fuse`.

- [ ] **Step 1: Write a failing hybrid-search test** whose RAPTOR node maps to an original chunk and assert the result exposes the chunk ID, not `node_id`.
- [ ] **Step 2: Run the targeted hybrid-search test** and confirm it fails with summary-node evidence.
- [ ] **Step 3: Use propagated leaf IDs and RAPTOR-specific job aggregation** while preserving existing BM25/dense aggregation.
- [ ] **Step 4: Run `pytest tests/test_raptor.py tests/test_hybrid_search.py -q`** and confirm the optional path passes.

### Task 4: Full verification

**Files:**
- Verify only.

**Interfaces:** None.

- [ ] **Step 1: Run the complete backend test suite** with `pytest -q`.
- [ ] **Step 2: Review `git diff --check`, `git diff --stat`, and the exact changed-file list.**
- [ ] **Step 3: Confirm RAPTOR remains disabled in the approved Match Brief path and no LangGraph/microservice dependency was added.**

