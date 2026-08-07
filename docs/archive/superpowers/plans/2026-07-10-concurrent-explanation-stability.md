# Concurrent Explanation Stability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve successful Top-N explanation results when one LLM request fails, without weakening cancellation or semaphore limits.

**Architecture:** Keep `asyncio.gather` and the existing `deepseek.chat` semaphore. Wrap each candidate explanation in an ordinary-exception boundary, return structured failure metadata, and update only successful roles.

**Tech Stack:** Python `asyncio`, existing DeepSeek async wrapper, pytest/pytest-asyncio, simulated-latency benchmark.

## Global Constraints

- Top-N calls remain concurrent through `asyncio.gather`.
- All real LLM calls continue through `app.llm.deepseek.chat` and its semaphore.
- `asyncio.CancelledError` must propagate.
- A failed candidate must not erase successful sibling explanations.
- No retries, queue, threading, or new framework is introduced.

---

### Task 1: Isolate ordinary per-candidate failures

**Files:**
- Modify: `app/agents/matching_agent.py`
- Test: `tests/test_agents_phase_c.py`

**Interfaces:**
- Produces: `_explain_candidate_match_safely(...) -> tuple[str, dict[str, Any], str | None]`
- Changes: matching supervisor log adds `failed` and `failed_job_ids`.

- [ ] **Step 1: Write the failing partial-success test**

Create five candidates. Make `fake_chat` raise `RuntimeError` for `job-3` and return valid JSON for the other four. Assert:

```python
assert sum(bool(role["match_explanation"]) for role in roles) == 4
assert state.supervisor_log[-1]["requested"] == 5
assert state.supervisor_log[-1]["updated"] == 4
assert state.supervisor_log[-1]["failed"] == 1
assert state.supervisor_log[-1]["failed_job_ids"] == ["job-3"]
```

- [ ] **Step 2: Run the test and verify RED**

Run: `python -m pytest tests/test_agents_phase_c.py -k one_failed_explanation -v`

Expected: FAIL because the current `asyncio.gather` propagates `RuntimeError`.

- [ ] **Step 3: Add the safe wrapper**

```python
async def _explain_candidate_match_safely(...):
    try:
        job_id, explanation = await _explain_candidate_match(...)
    except Exception as exc:
        return candidate.job_id, {}, type(exc).__name__
    if not explanation:
        return job_id, {}, "invalid_response"
    return job_id, explanation, None
```

Gather this wrapper, apply successful explanations, and derive failure IDs from non-null error values. Catch `Exception`, not `BaseException`, so cancellation remains observable.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python -m pytest tests/test_agents_phase_c.py -k "top_five or one_failed_explanation" -v`

Expected: parallel execution and partial success tests pass.

- [ ] **Step 5: Commit Task 1**

```bash
git add app/agents/matching_agent.py tests/test_agents_phase_c.py
git commit -m "Isolate concurrent explanation failures"
```

### Task 2: Prove cancellation and semaphore behavior

**Files:**
- Modify: `tests/test_agents_phase_c.py`
- Verify: `tests/test_llm_concurrency.py`

- [ ] **Step 1: Add a cancellation propagation test**

Use a `chat_fn` that raises `asyncio.CancelledError` and assert:

```python
with pytest.raises(asyncio.CancelledError):
    await enrich_top_match_explanations(state, candidates, chat_fn=cancelled_chat)
```

- [ ] **Step 2: Run cancellation and real-wrapper semaphore tests**

Run: `python -m pytest tests/test_agents_phase_c.py -k cancellation -v`

Run: `python -m pytest tests/test_llm_concurrency.py -v`

Expected: cancellation propagates and maximum active DeepSeek client calls equals the monkeypatched semaphore limit.

- [ ] **Step 3: Commit Task 2**

```bash
git add tests/test_agents_phase_c.py
git commit -m "Verify explanation cancellation behavior"
```

### Task 3: Capture fresh serial/parallel evidence

**Files:**
- Verify: `scripts/benchmark_matching_explanations.py`
- Verify: `tests/test_matching_explanation_benchmark.py`

- [ ] Run: `python -m pytest tests/test_matching_explanation_benchmark.py tests/test_llm_concurrency.py -v`
- [ ] Run: `python scripts/benchmark_matching_explanations.py --candidates 5 --simulated-latency-ms 300 --semaphore-limit 5 --format table`
- [ ] Confirm serial max active calls is 1, parallel max active calls is 5, and parallel elapsed time is lower.

### Task 4: Final verification

- [ ] Run: `python -m pytest`
- [ ] Run: `git diff --check`
- [ ] Review `git status --short` and ensure unrelated user files remain untouched.
