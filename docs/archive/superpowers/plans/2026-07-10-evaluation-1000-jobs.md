# Metrics and 1,000-Job Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct duplicate-sensitive ranking metrics and evaluate the 15 resume queries against a documented 1,000-job Kaggle corpus.

**Architecture:** Normalize each ranking to unique job IDs before applying K. Keep the 15 static query cases, expand relevance judgments after title/description review of the full sample, and add a machine-checked evaluation manifest.

**Tech Stack:** Python standard library (`csv`, `json`, `math`), pytest, existing evaluation CLI and Kaggle CSV fixtures.

## Global Constraints

- Metrics remain API-compatible and bounded in `[0, 1]`.
- Evaluation fixtures run offline without PostgreSQL or external APIs.
- The candidate corpus is exactly `data/jobs/linkedin_postings_1000.csv` with 1,000 unique IDs.
- Relevance discovery does not consume rankings from the retrieval system under test.
- RAPTOR remains optional and is not expanded.

---

### Task 1: Make ranking metrics duplicate-safe

**Files:**
- Modify: `app/evaluation/metrics.py`
- Test: `tests/test_metrics.py`

**Interfaces:**
- Produces: `_unique_ranked_ids(values: Sequence[object]) -> list[str]`
- Changes: `evaluate_rankings` deduplicates before slicing to K.

- [ ] **Step 1: Write the failing regression test**

```python
def test_evaluate_rankings_deduplicates_predictions_before_k():
    labels = [{"case_id": "eval-1", "relevant_job_ids": ["a"]}]
    rankings = {"eval-1": ["a", "a"]}

    metrics = evaluate_rankings(labels, rankings, k=2)

    assert metrics == {
        "cases": 1,
        "precision@2": 0.5,
        "recall@2": 1.0,
        "mrr@2": 1.0,
        "ndcg@2": 1.0,
    }
```

- [ ] **Step 2: Run the test and verify RED**

Run: `python -m pytest tests/test_metrics.py::test_evaluate_rankings_deduplicates_predictions_before_k -v`

Expected: FAIL with recall `2.0` and NDCG greater than `1.0`.

- [ ] **Step 3: Implement first-occurrence deduplication**

```python
def _unique_ranked_ids(values: Sequence[object]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values))
```

Use `_unique_ranked_ids(rankings.get(case_id, []))[:k]` in `evaluate_rankings`.

- [ ] **Step 4: Run all metric tests and verify GREEN**

Run: `python -m pytest tests/test_metrics.py -v`

Expected: all metric tests pass and every returned score is at most `1.0`.

- [ ] **Step 5: Commit Task 1**

```bash
git add app/evaluation/metrics.py tests/test_metrics.py
git commit -m "Make ranking metrics duplicate-safe"
```

### Task 2: Bind evaluation labels to the full 1,000-job corpus

**Files:**
- Create: `data/eval/evaluation_manifest.json`
- Modify: `data/eval/relevance_labels.jsonl`
- Modify: `tests/test_eval_dataset.py`

**Interfaces:**
- Produces: manifest fields `source`, `corpus_file`, `corpus_rows`, `unique_job_ids`, `query_cases`, `annotation_method`, and `annotation_scope`.
- Changes: each relevance-label row includes `annotation_scope="linkedin_1000_title_description_review"`.

- [ ] **Step 1: Strengthen the failing corpus contract**

Update the dataset test to load the 1,000-job CSV and assert:

```python
assert len(job_rows) == 1000
assert len({row["job_id"] for row in job_rows}) == 1000
assert len(labels) == 15
assert all(row["annotation_scope"] == "linkedin_1000_title_description_review" for row in labels)
assert all(set(row["relevant_job_ids"]) <= job_ids for row in labels)
assert sum(bool(set(row["relevant_job_ids"]) - original_50_ids) for row in labels) >= 10
```

Validate that manifest counts and paths match the files.

- [ ] **Step 2: Run the dataset tests and verify RED**

Run: `python -m pytest tests/test_eval_dataset.py -v`

Expected: FAIL because labels have 50-job notes/scope and no evaluation manifest.

- [ ] **Step 3: Review relevance pools across all 1,000 jobs**

For each of the 15 intents, inspect candidate titles and descriptions selected by explicit role-family terms. Accept a job only when its title or core description matches the stated intent; adjacent bridge roles remain relevant only where the existing notes already define adjacency. Do not use `hybrid_search` output during this review.

Update every JSONL row with the fixed scope value and the reviewed job IDs. Preserve `case_id`, query, expected intent, and explanatory notes.

- [ ] **Step 4: Add the manifest**

Create:

```json
{
  "source": "Kaggle arshkon/linkedin-job-postings",
  "corpus_file": "data/jobs/linkedin_postings_1000.csv",
  "corpus_rows": 1000,
  "unique_job_ids": 1000,
  "query_cases": 15,
  "labels_file": "data/eval/relevance_labels.jsonl",
  "queries_file": "data/eval/resume_queries.jsonl",
  "annotation_method": "case-specific title and description relevance review",
  "annotation_scope": "linkedin_1000_title_description_review"
}
```

- [ ] **Step 5: Run dataset tests and verify GREEN**

Run: `python -m pytest tests/test_eval_dataset.py tests/test_sample_kaggle_jobs.py -v`

Expected: all tests pass with exactly 1,000 unique corpus jobs and at least 10 cases expanded beyond the original 50 IDs.

- [ ] **Step 6: Commit Task 2**

```bash
git add data/eval/evaluation_manifest.json data/eval/relevance_labels.jsonl tests/test_eval_dataset.py
git commit -m "Evaluate resume queries against 1000 jobs"
```

### Task 3: Produce and verify the metric table

**Files:**
- Verify: `scripts/evaluate_system.py`
- Verify: `data/eval/offline_rankings_example.json`
- Test: `tests/test_evaluate_system_script.py`

- [ ] **Step 1: Add a bounded-table assertion**

Extend the table test:

```python
assert table
for row in table:
    assert 0.0 <= row["precision"] <= 1.0
    assert 0.0 <= row["recall"] <= 1.0
    assert 0.0 <= row["mrr"] <= 1.0
    assert 0.0 <= row["ndcg"] <= 1.0
```

- [ ] **Step 2: Run the test, then run the offline CLI**

Run: `python -m pytest tests/test_evaluate_system_script.py -v`

Run: `python scripts/evaluate_system.py --rankings data/eval/offline_rankings_example.json --format table --table-k 1 3 5`

Expected: a Markdown table with baseline/with_raptor/with_latent rows and bounded Precision, Recall, MRR, and NDCG values.

- [ ] **Step 3: Commit Task 3 only if the test file changed**

```bash
git add tests/test_evaluate_system_script.py
git commit -m "Verify bounded evaluation table output"
```

### Task 4: Verify Phase 2

- [ ] Run: `python -m pytest tests/test_metrics.py tests/test_eval_dataset.py tests/test_evaluate_system_script.py tests/test_sample_kaggle_jobs.py -v`
- [ ] Run the offline metric-table command and retain its measured output for final reporting.
- [ ] Run: `python -m pytest`
