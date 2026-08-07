# Final Review Fix Report

## Status

Complete on branch `codex/week3-reoptimization`, starting from `e5e82df`.

The fix wave stays within P0/P1. It adds no P2 retrieval mechanism, queue,
retry framework, thread, process-global user state, schema migration, or external
network call.

## Implementation Commits

The final evidence-only report commit is intentionally excluded from this list
because a commit cannot embed its own final hash.

1. `452d2048d6399a6b090a7d811396452b62e34655` - Preserve feedback across stale state saves
2. `5b8510095b540d2f5099142ceffbff056dccd9f5` - Constrain anonymous feedback cases
3. `a03a6e7202ee8681dd152dadd4e3d081d8ff48f4` - Make feedback closure truthful and idempotent
4. `6e34c94f059e30e805f63eeb8518bd37b5fb62d2` - Add deterministic 1000-job lexical baseline
5. `05aa74ada982d4afb012423a7adcc3b120e899a0` - Close new-session state save race

## Files Changed

- `app/agents/supervisor.py`
- `app/api/routes.py`
- `app/db/state_store.py`
- `app/evaluation/metrics.py`
- `app/memory/case_base.py`
- `app/memory/feedback_loop.py`
- `data/eval/evaluation_manifest.json`
- `data/eval/offline_lexical_rankings_1000.json`
- `scripts/evaluate_system.py`
- `scripts/generate_lexical_rankings.py`
- `tests/test_api_routes.py`
- `tests/test_eval_dataset.py`
- `tests/test_evaluate_system_script.py`
- `tests/test_feedback_loop.py`
- `tests/test_generate_lexical_rankings.py`
- `tests/test_memory_phase_e.py`
- `tests/test_metrics.py`

The unrelated untracked `.planning/`,
`docs/career_matching_claude_code_inspiration.md`, and
`docs/codex_step_plan_dual_space_link.md` paths were not modified or staged.

## Implemented Requirements

### Conflict-aware saves

- Every ordinary `save_state` transaction first establishes the session row with
  `INSERT ... ON CONFLICT DO NOTHING`, then locks it with `SELECT ... FOR UPDATE`.
- The locked latest state wins for feedback-owned append-only entries, bounded
  case preferences, and supervisor logs. Incoming ordinary workflow fields and
  status remain intentional save inputs.
- Feedback-only atomic mutations still update JSON state without changing status.
- The initial implementation's missing-row race was found during self-review and
  fixed in `05aa74a`.

### Controlled anonymous cases

- `background_type` accepts only exact canonical tags from a bounded technical
  and professional skill allowlist.
- Current goals, normalized/raw resume text, evidence text, LLM explanation text,
  and unknown skill labels are excluded from case fields.
- Successful features are fixed categorical labels. Missing skills are canonical
  allowlist values. Target and bridge titles come from retrieved role metadata.
- Case IDs depend on session, job, and normalized outcome, not feedback ID.
- Case preference updates accept only `case_target_roles` and
  `case_bridge_roles`; values are deduplicated and capped at 10 per key.

### Truthful, idempotent feedback

- `FeedbackRequest.idempotency_key` is optional and capped at 128 characters.
- The idempotency key is persisted in `feedback_state.user_feedback`. A repeated
  key returns the existing feedback ID inside the row-locked transaction and
  does not insert another `feedback_memory` row.
- Matching feedback entries persist `closure_status`, `case_written`, `case_id`,
  and a stable `error_code` when applicable.
- A similar-case search failure after a successful upsert returns and persists
  `case_written=true` with the real case ID.
- API `status` remains `feedback_recorded`; `closure_status` is `processed`,
  `skipped`, or `error`.
- Invalid outcomes are rejected by Pydantic/FastAPI with HTTP 422.
- Shared state contains stable error codes only. Exception messages are not stored.

### Offline ranking and metrics

- `scripts/generate_lexical_rankings.py` uses only Python standard-library CSV,
  JSON, hashing, tokenization, counters, and math.
- It reads all 1,000 corpus rows and all 15 query rows. It does not import or call
  live retrieval, PostgreSQL, embeddings, model clients, or network APIs.
- `scripts/evaluate_system.py` accepts both the metadata-wrapped artifact and the
  pre-existing plain run-map format.
- Qualitative latent first-relevant-rank comparison now deduplicates IDs exactly
  as quantitative MRR does.

## TDD Evidence

The first attempted test command used the default Hermes Python and stopped at
`No module named pytest`; this was an environment error and is not counted as RED.
All test evidence below uses `.venv\Scripts\python.exe`.

### State interleaving

RED:

```text
.\.venv\Scripts\python.exe -m pytest tests/test_memory_phase_e.py::test_stale_stage_save_preserves_concurrently_committed_feedback_state -q
1 failed: save_state executed the stale upsert without entering a transaction.
```

GREEN:

```text
.\.venv\Scripts\python.exe -m pytest tests/test_memory_phase_e.py::test_stale_stage_save_preserves_concurrently_committed_feedback_state tests/test_memory_phase_e.py::test_state_store_feedback_locks_and_updates_latest_state_atomically tests/test_memory_phase_e.py::test_mutate_state_atomically_locks_and_updates_state_without_status -q
3 passed

.\.venv\Scripts\python.exe -m pytest tests/test_memory_phase_e.py -q
12 passed
```

### Privacy and preference bounds

RED:

```text
.\.venv\Scripts\python.exe -m pytest tests/test_feedback_loop.py::test_case_soft_preferences_restrict_keys_deduplicate_and_cap_values tests/test_feedback_loop.py::test_anonymous_feedback_case_uses_only_controlled_non_private_content -q
2 failed: no cap constant; free-form private content reached the case builder.

.\.venv\Scripts\python.exe -m pytest tests/test_feedback_loop.py::test_similar_case_preferences_are_bounded_before_persistence -q
1 failed: 15 target roles were returned instead of the cap of 10.
```

GREEN:

```text
.\.venv\Scripts\python.exe -m pytest tests/test_feedback_loop.py tests/test_agents_phase_c.py::test_supervisor_planning_merges_learned_case_preferences tests/test_memory_phase_e.py::test_stale_stage_save_preserves_concurrently_committed_feedback_state -q
11 passed
```

### Feedback truth and idempotency

RED:

```text
.\.venv\Scripts\python.exe -m pytest tests/test_memory_phase_e.py::test_state_store_feedback_reuses_persisted_idempotency_key tests/test_feedback_loop.py::test_feedback_loop_reports_case_written_when_similar_search_fails tests/test_feedback_loop.py::test_process_feedback_closure_for_session_uses_atomic_state_mutation tests/test_api_routes.py::test_feedback_is_written_by_session_id tests/test_api_routes.py::test_feedback_returns_skipped_when_closure_rejects_feedback tests/test_api_routes.py::test_feedback_rejects_invalid_outcome_with_422 tests/test_api_routes.py::test_feedback_response_preserves_partial_case_write_truth -q
7 failed for missing idempotency input, propagated search failure, missing closure metadata, incompatible top-level status, missing 422 validation, and inaccurate partial failure response.
```

GREEN:

```text
.\.venv\Scripts\python.exe -m pytest tests/test_memory_phase_e.py::test_state_store_feedback_reuses_persisted_idempotency_key tests/test_feedback_loop.py::test_feedback_loop_reports_case_written_when_similar_search_fails tests/test_feedback_loop.py::test_process_feedback_closure_for_session_uses_atomic_state_mutation tests/test_api_routes.py::test_feedback_is_written_by_session_id tests/test_api_routes.py::test_feedback_returns_skipped_when_closure_rejects_feedback tests/test_api_routes.py::test_feedback_rejects_invalid_outcome_with_422 tests/test_api_routes.py::test_feedback_response_preserves_partial_case_write_truth -q
7 passed

.\.venv\Scripts\python.exe -m pytest tests/test_memory_phase_e.py tests/test_feedback_loop.py tests/test_api_routes.py -q
34 passed
```

### Ranking artifact and loader

RED:

```text
.\.venv\Scripts\python.exe -m pytest tests/test_generate_lexical_rankings.py tests/test_evaluate_system_script.py::test_load_offline_rankings_accepts_wrapped_and_plain_formats tests/test_eval_dataset.py::test_relevance_labels_are_bound_to_the_full_linkedin_corpus -q
5 failed: generator/fixture/loader/manifest fields did not yet exist.
```

GREEN:

```text
.\.venv\Scripts\python.exe -m pytest tests/test_generate_lexical_rankings.py tests/test_evaluate_system_script.py tests/test_eval_dataset.py -q
9 passed
```

### Duplicate-normalized qualitative rank

RED:

```text
.\.venv\Scripts\python.exe -m pytest tests/test_metrics.py::test_latent_qualitative_rank_comparison_ignores_duplicate_ids -q
1 failed: qualitative comparison reported improved instead of unchanged.
```

GREEN:

```text
.\.venv\Scripts\python.exe -m pytest tests/test_metrics.py tests/test_evaluate_system_script.py tests/test_generate_lexical_rankings.py tests/test_eval_dataset.py -q
17 passed
```

### Self-review missing-row race

RED:

```text
.\.venv\Scripts\python.exe -m pytest tests/test_memory_phase_e.py::test_save_state_establishes_session_row_before_acquiring_row_lock -q
1 failed: row lock was attempted before the session row was established.
```

GREEN:

```text
.\.venv\Scripts\python.exe -m pytest tests/test_memory_phase_e.py -q
14 passed
```

## Generated Ranking Metadata

Command:

```text
.\.venv\Scripts\python.exe scripts/generate_lexical_rankings.py --corpus data/jobs/linkedin_postings_1000.csv --queries data/eval/resume_queries.jsonl --output data/eval/offline_lexical_rankings_1000.json --top-k 20
```

Result:

```json
{
  "artifact_kind": "offline_lexical_baseline",
  "label": "Offline lexical baseline (not live hybrid-system performance)",
  "corpus_path": "data/jobs/linkedin_postings_1000.csv",
  "corpus_sha256": "a375454912fb311ebbf9797963efa4c3adb9a75db7bd820e7a111f13ed52931a",
  "corpus_row_count": 1000,
  "query_path": "data/eval/resume_queries.jsonl",
  "query_count": 15,
  "method": "deterministic_weighted_token_overlap_v1",
  "top_k": 20
}
```

Independent `Get-FileHash` produced the same SHA-256. The fixture contains 234
distinct ranked job IDs outside `linkedin_postings_50.csv`.

## Offline Lexical Baseline Table

Command:

```text
.\.venv\Scripts\python.exe scripts/evaluate_system.py --rankings data/eval/offline_lexical_rankings_1000.json --format table --table-k 1 3 5 10 20
```

| run | k | cases | precision | recall | mrr | ndcg |
| --- | --- | --- | --- | --- | --- | --- |
| offline_lexical_baseline | 1 | 15 | 0.600000 | 0.082059 | 0.600000 | 0.600000 |
| offline_lexical_baseline | 3 | 15 | 0.511111 | 0.199282 | 0.700000 | 0.521045 |
| offline_lexical_baseline | 5 | 15 | 0.400000 | 0.250001 | 0.700000 | 0.447162 |
| offline_lexical_baseline | 10 | 15 | 0.346667 | 0.434229 | 0.717857 | 0.457624 |
| offline_lexical_baseline | 20 | 15 | 0.223333 | 0.558509 | 0.717857 | 0.515837 |

These numbers are an offline lexical baseline only. They are not live hybrid,
BM25+dense+RRF, embedding, or PostgreSQL performance.

## Final Verification

```text
.\.venv\Scripts\python.exe -m pytest -q
92 passed in 1.72s

git diff --check e5e82df..HEAD
exit 0, no output
```

## Limitations

- `TEST_DATABASE_URL` is not configured. PostgreSQL transaction behavior was not
  claimed as live integration-tested.
- Row locking, transaction order, interleaving, idempotent short-circuiting, and
  status-preservation behavior have rigorous unit coverage using the repository's
  async fake pool/connection/transaction pattern.
- No external API or network call was made during implementation or verification.
- The lexical ranking artifact intentionally does not measure the live hybrid path.

## Self-review

- Requirements pass: all Critical/Important brief items are mapped to code and tests.
- Concurrency pass: found and fixed the missing-row lock gap in `05aa74a`.
- Privacy pass: adversarial case payload excludes all supplied private fragments;
  raw and normalized resumes remain private matching inputs only.
- API pass: backward-compatible top-level status and additive closure fields verified.
- Evaluation pass: corpus membership, corpus hash, all 15 queries, old-50 escape,
  deterministic regeneration, and wrapped/plain loader compatibility verified.
- Scope pass: no P2, queue, retry framework, threads, global state, migration, or
  unrelated-file edits.
- Independent multi-agent audit was unavailable because this session exposed no
  subagent dispatch capability. The coordinator performed the plan, test, style,
  docs, dead-code, and comment review passes directly; this is a residual review
  limitation, not a fabricated independent review result.
