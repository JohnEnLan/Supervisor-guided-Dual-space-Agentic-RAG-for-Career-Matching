# Feedback Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make persisted application feedback produce durable anonymous-case ranking hints that affect the next retrieval plan.

**Architecture:** Keep explicit preferences in `CareerState` and learned case hints in `FeedbackState`. The feedback endpoint records first, processes the closure synchronously, persists learned hints without changing the session workflow status, and reports processed/skipped/error status.

**Tech Stack:** Python 3.12 runtime, Pydantic, FastAPI async routes, asyncpg state store, pytest/pytest-asyncio.

## Global Constraints

- Shared state remains PostgreSQL-backed by `session_id`; no user state is added to process globals.
- All code remains async; no threading or multiprocessing.
- Anonymous cases remain P1 soft-ranking hints and never bypass SQL hard filters.
- Raw resume text is not copied into the anonymous case base.
- Every production behavior change begins with a failing test.

---

### Task 1: Persist learned case preferences in SharedState

**Files:**
- Modify: `app/state/schema.py`
- Modify: `app/memory/case_base.py`
- Modify: `app/memory/feedback_loop.py`
- Test: `tests/test_feedback_loop.py`

**Interfaces:**
- Produces: `FeedbackState.case_soft_preferences: dict`
- Produces: `merge_case_soft_preferences(base_soft_prefs: dict[str, Any], case_updates: dict[str, list[str]]) -> dict[str, Any]`
- Changes: `run_feedback_closure(...)` mutates the supplied state with durable learned hints.

- [ ] **Step 1: Write the failing persistence assertion**

Extend `test_feedback_loop_writes_anonymous_case_and_returns_case_weight_hints`:

```python
assert state.feedback_state.case_soft_preferences == {
    "case_target_roles": ["Data Analyst"],
    "case_bridge_roles": ["Business Analyst Intern"],
}
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m pytest tests/test_feedback_loop.py::test_feedback_loop_writes_anonymous_case_and_returns_case_weight_hints -v`

Expected: FAIL because `FeedbackState` has no `case_soft_preferences` field.

- [ ] **Step 3: Add the schema field and merge helper**

Add to `FeedbackState`:

```python
case_soft_preferences: dict = Field(default_factory=dict)
```

Move the existing list-preserving merge behavior into `app/memory/case_base.py`:

```python
def merge_case_soft_preferences(
    base_soft_prefs: dict[str, Any],
    case_updates: dict[str, list[str]],
) -> dict[str, Any]:
    merged = {
        key: list(value) if isinstance(value, list) else value
        for key, value in base_soft_prefs.items()
    }
    for key, values in case_updates.items():
        existing = merged.get(key)
        merged[key] = list(existing) if isinstance(existing, list) else []
        for value in values:
            if value and value not in merged[key]:
                merged[key].append(value)
    return merged
```

After `build_case_soft_preferences` in `run_feedback_closure`, assign:

```python
state.feedback_state.case_soft_preferences = merge_case_soft_preferences(
    state.feedback_state.case_soft_preferences,
    soft_preference_updates,
)
```

- [ ] **Step 4: Run focused feedback tests and verify GREEN**

Run: `python -m pytest tests/test_feedback_loop.py -v`

Expected: all feedback-loop tests pass.

- [ ] **Step 5: Commit Task 1**

```bash
git add app/state/schema.py app/memory/case_base.py app/memory/feedback_loop.py tests/test_feedback_loop.py
git commit -m "Persist case-derived feedback preferences"
```

### Task 2: Merge learned hints into Supervisor retrieval planning

**Files:**
- Modify: `app/agents/supervisor.py`
- Test: `tests/test_agents_phase_c.py`

**Interfaces:**
- Consumes: `FeedbackState.case_soft_preferences`
- Consumes: `merge_case_soft_preferences(...)`
- Produces: retrieval plan `soft_prefs` containing explicit and learned list values.

- [ ] **Step 1: Write a failing Supervisor merge test**

Create a state with explicit title keywords and learned case roles, monkeypatch the planning LLM, then assert:

```python
assert plan["soft_prefs"] == {
    "title_keywords": ["analyst"],
    "case_target_roles": ["Data Analyst"],
    "case_bridge_roles": ["Business Analyst Intern"],
}
assert state.career_state.soft_preferences == {"title_keywords": ["analyst"]}
```

- [ ] **Step 2: Run the new test and verify RED**

Run: `python -m pytest tests/test_agents_phase_c.py -k learned_case_preferences -v`

Expected: FAIL because `plan_retrieval` currently ignores `feedback_state.case_soft_preferences`.

- [ ] **Step 3: Merge at the planning boundary**

Import the helper from `app.memory.case_base` and compute:

```python
explicit_soft_prefs = (
    state.career_state.soft_preferences
    or _as_dict(llm_plan.get("soft_preferences"))
)
soft_prefs = merge_case_soft_preferences(
    explicit_soft_prefs,
    state.feedback_state.case_soft_preferences,
)
```

Use `soft_prefs` in both the returned plan and planning log. Do not mutate explicit career preferences.

- [ ] **Step 4: Run agent and hybrid-search tests**

Run: `python -m pytest tests/test_agents_phase_c.py tests/test_hybrid_search.py -v`

Expected: all selected tests pass.

- [ ] **Step 5: Commit Task 2**

```bash
git add app/agents/supervisor.py tests/test_agents_phase_c.py
git commit -m "Apply feedback hints during retrieval planning"
```

### Task 3: Connect the feedback API to closure processing

**Files:**
- Modify: `app/memory/feedback_loop.py`
- Modify: `app/api/routes.py`
- Test: `tests/test_feedback_loop.py`
- Test: `tests/test_api_routes.py`

**Interfaces:**
- Produces: `process_feedback_closure_for_session(session_id: str, feedback: dict[str, Any]) -> dict[str, Any]`
- Changes: `POST /feedback` returns `closure_status`, `case_written`, and `soft_preference_updates`.

- [ ] **Step 1: Write failing session-processor and API tests**

The session processor test must fake `load_state_with_status` and `save_state`, then assert the original `agentic_done` status is preserved. The API test must fake `add_feedback` and the processor, then assert:

```python
assert response.json() == {
    "session_id": "s1",
    "feedback_id": 42,
    "status": "feedback_processed",
    "closure_status": "processed",
    "case_written": True,
    "soft_preference_updates": {"case_target_roles": ["Data Analyst"]},
}
```

Add a rejected-feedback API test expecting `closure_status="skipped"` and `case_written=False`.

- [ ] **Step 2: Run the new tests and verify RED**

Run: `python -m pytest tests/test_feedback_loop.py tests/test_api_routes.py -k "session or feedback" -v`

Expected: FAIL because the processor and closure response do not exist.

- [ ] **Step 3: Implement the session processor**

In `feedback_loop.py`, load state and status, run the existing closure, save with the same status, and return the result:

```python
async def process_feedback_closure_for_session(
    *, session_id: str, feedback: dict[str, Any]
) -> dict[str, Any]:
    state_with_status = await load_state_with_status(session_id)
    if state_with_status is None:
        raise KeyError(session_id)
    state, status = state_with_status
    result = await run_feedback_closure(state, feedback=feedback)
    await save_state(state, status=status)
    return result
```

- [ ] **Step 4: Implement API orchestration and explicit failure reporting**

After `add_feedback`, call the processor with the returned ID. Return `processed` when a case is written and `skipped` otherwise. Catch ordinary closure exceptions after the durable feedback write and return:

```python
{
    "session_id": request.session_id,
    "feedback_id": feedback_id,
    "status": "feedback_recorded",
    "closure_status": "error",
    "case_written": False,
    "soft_preference_updates": {},
}
```

Append a best-effort `feedback_closure_error` supervisor log entry without changing the current workflow status.

- [ ] **Step 5: Run focused and full feedback tests**

Run: `python -m pytest tests/test_feedback_loop.py tests/test_memory_phase_e.py tests/test_api_routes.py -v`

Expected: all selected tests pass.

- [ ] **Step 6: Commit Task 3**

```bash
git add app/memory/feedback_loop.py app/api/routes.py tests/test_feedback_loop.py tests/test_api_routes.py
git commit -m "Connect feedback API to anonymous case closure"
```

### Task 4: Verify Phase 1 end to end

- [ ] Run: `python -m pytest tests/test_feedback_loop.py tests/test_agents_phase_c.py tests/test_hybrid_search.py tests/test_api_routes.py tests/test_memory_phase_e.py -v`
- [ ] Run: `python -m pytest`
- [ ] Confirm no test failure and no unrelated tracked files in `git status --short`.
