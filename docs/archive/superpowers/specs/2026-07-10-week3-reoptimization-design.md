# Week 3 Re-optimization Design

Status: Awaiting written-spec review

## Goal

Complete the Week 3 mechanisms in this order:

1. Connect recorded application feedback to durable case-based ranking hints.
2. Correct ranking metrics and make the evaluation corpus genuinely use 1,000 Kaggle jobs.
3. Isolate per-job LLM explanation failures while preserving bounded concurrency.

The main job-matching path remains unchanged: a user's private uploaded resume is
parsed and normalized with evidence spans, then used for retrieval and agent
reasoning. Anonymous cases are only a small soft-ranking signal and never replace
the resume.

## Scope

This design stays inside P0/P1. It does not add RAPTOR work, a cross-encoder,
another agent framework, a task queue, or model training. The existing anonymous
career-case schema remains intentionally compact and never stores raw resume text.

## Phase 1: Complete Feedback Closure

### Persistent learned preferences

Add `case_soft_preferences` to `FeedbackState`. It stores only case-derived keys:

- `case_target_roles`
- `case_bridge_roles`

These values are separate from `career_state.soft_preferences`, which represents
preferences explicitly extracted from the user's current request. This prevents
the Intent Agent from erasing learned case hints on the next match.

### Feedback processing flow

The `/feedback` endpoint will:

1. Record and persist the canonical feedback through `add_feedback`.
2. Reload the session state and its current status.
3. Run `run_feedback_closure` with the persisted `feedback_id`.
4. For valuable positive feedback, create or update the deterministic anonymous
   case, retrieve similar cases, and merge their hints into
   `feedback_state.case_soft_preferences`.
5. Persist the state while preserving the previous workflow status, such as
   `agentic_done`.
6. Return whether the closure was processed, skipped, or failed, whether a case
   was written, and which preference hints were added.

Positive outcomes remain the existing screen/OA/interview/offer set. Rejections
are still recorded, but they do not become positive career cases. A job that was
not present in the session's recommendations is also recorded but skipped for
case creation.

### Applying learned preferences

`Supervisor.plan_retrieval` will merge explicit soft preferences with the durable
case preferences immediately before retrieval. List values are deduplicated while
preserving order. Case preferences can add ranking bonuses only; they cannot
modify hard constraints or make a filtered job eligible.

The existing `hybrid_search` bonuses remain the enforcement point:

- matching a case target role adds the existing target-role bonus;
- matching a case bridge role adds the existing bridge-role bonus;
- the total soft-preference bonus remains capped.

### Failure and retry behavior

The feedback record is durable before case processing begins. If case embedding,
case storage, or case search fails, the endpoint reports `closure_status=error`
instead of claiming that the closure completed. A best-effort supervisor-log entry
records the error. The deterministic hashed case ID makes a later retry an upsert
rather than a duplicate.

### Phase 1 verification

- A positive feedback API request writes an anonymous case and persists learned
  preferences.
- A rejected feedback request is persisted and returns a skipped closure without
  creating a case.
- A subsequent retrieval plan contains both explicit and learned preferences.
- Intent Agent execution does not erase learned preferences.
- Existing hard-filter behavior remains unchanged.

## Phase 2: Metrics and 1,000-Job Evaluation Corpus

### Metric correctness

Before applying K, predicted job IDs will be deduplicated by first occurrence.
This prevents one relevant job repeated twice from being counted as two hits.
Recall, Precision, MRR, and NDCG must remain between 0 and 1 for every valid input.
Existing metric names and table output remain compatible.

### Evaluation corpus

The evaluation manifest and tests will designate
`data/jobs/linkedin_postings_1000.csv` as the candidate corpus and verify exactly
1,000 unique, loadable job IDs. The 15 existing resume-query cases remain the
query set.

Relevance judgments will be reviewed against titles and descriptions across all
1,000 jobs, not only the original 50-job slice. The committed labels will record
the annotation scope and will contain only IDs present in the 1,000-job corpus.
Candidate discovery for annotation may use transparent title/description keyword
pooling, but it will not use rankings produced by the retrieval system under test.

An evaluation manifest will record:

- source dataset and sampled corpus file;
- corpus row and unique-ID counts;
- query-case count;
- relevance-judgment method and scope.

### Phase 2 verification

- The duplicate-ranking regression test fails before the fix and passes after it.
- Every metric is bounded in `[0, 1]`.
- The corpus contract confirms 1,000 unique Kaggle jobs.
- Every relevance label references the 1,000-job corpus.
- The evaluation CLI renders a Recall/Precision/MRR/NDCG table from the updated
  fixtures.

Live hybrid retrieval evaluation still requires a populated PostgreSQL/pgvector
database and configured embedding service. Deterministic fixture validation and
offline metric-table generation must run without network access.

## Phase 3: Concurrent Explanation Stability

Top-N explanations remain concurrent and continue to call `deepseek.chat`, so the
existing configured semaphore remains the global limit. Each candidate call will
receive an exception-isolation wrapper that catches ordinary API/parse failures
for that candidate, records the failure, and allows successful sibling calls to
update their roles. Task cancellation is not swallowed.

The matching supervisor log will report:

- requested explanation count;
- successfully updated count;
- failed count and failed job IDs;
- parallel execution mode.

The benchmark remains based on controlled simulated latency so results are
repeatable and cost-free. It will continue to report serial versus parallel
latency and maximum active calls under a chosen semaphore limit.

### Phase 3 verification

- One failed LLM call does not discard four successful explanations.
- A cancellation still propagates.
- The real DeepSeek wrapper semaphore test continues to enforce its configured
  concurrency limit.
- The benchmark produces a fresh serial/parallel latency table.

## Compatibility

Existing session JSON remains readable because the new feedback field has a
default empty dictionary. No SQL schema migration is required for session state.
Career-case rows and the 1,000-job CSV format remain compatible. API feedback
responses gain closure details but retain `session_id` and `feedback_id`.

## Delivery Order

Each phase uses a separate test-first cycle and focused verification before the
next phase begins. The full test suite and relevant benchmark/data checks run at
the end. Unrelated user files and P2 modules are not modified.
