# Supervisor Harness Checkpoints Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic, logged Supervisor checkpoints around all three business agents and before final publication.

**Architecture:** Keep `orchestrator.py` as the async workflow portion of the Supervisor Harness and place deterministic checkpoint policy in a focused module. Checkpoints append privacy-safe records to `SharedState.supervisor_log`; only invalid input contracts block execution.

**Tech Stack:** Python 3.11+, Pydantic state models, asyncio orchestration, pytest.

## Global Constraints

- Do not introduce LangGraph, AutoGen, CrewAI, microservices, threads, or processes.
- Keep state in the existing PostgreSQL-backed `SharedState` contract.
- Do not add LLM calls at deterministic checkpoints.
- Preserve bounded clarification, re-retrieval, and repair loops with maximum 1.
- Implement and verify this module before beginning RAPTOR changes.

---

### Task 1: Deterministic checkpoint policy

**Files:**
- Create: `app/agents/supervisor_harness.py`
- Create: `tests/test_supervisor_harness.py`

**Interfaces:**
- Produces: `SupervisorCheckpointError` and `record_supervisor_checkpoint(state, *, checkpoint, user_goal_text="", retrieval_plan=None, locked_hard_constraints=None, verification=None, attempt=1) -> dict[str, Any]`.
- Appends one structural record to `state.supervisor_log` and raises only for blocking input issues.

- [ ] **Step 1: Write failing unit tests** for valid checkpoints, non-positive `top_k`, locked hard-constraint mismatch, unknown recommendation IDs, and publication warnings.
- [ ] **Step 2: Run `pytest tests/test_supervisor_harness.py -q`** and confirm failure because the policy module does not exist.
- [ ] **Step 3: Implement the minimal checkpoint validators** with stable issue codes and privacy-safe metrics.
- [ ] **Step 4: Run `pytest tests/test_supervisor_harness.py -q`** and confirm all checkpoint tests pass.

### Task 2: Wrap the three Agents in the Supervisor Harness

**Files:**
- Modify: `app/agents/orchestrator.py`
- Modify: `tests/test_run_orchestration.py`
- Verify: `tests/test_orchestrator_persistence.py`

**Interfaces:**
- Produces internal wrappers `_run_intent_under_supervision`, `_run_matching_under_supervision`, and `_run_strategy_under_supervision` that call the existing Agent functions exactly once per attempt.
- All orchestration entry points record `intent_input/output`, `matching_input/output`, `strategy_input/output`, and `publication_gate`.

- [ ] **Step 1: Write a failing orchestration test** asserting checkpoint order and proving no extra final-verifier call is added.
- [ ] **Step 2: Run the targeted orchestration test** and confirm the expected checkpoint sequence is missing.
- [ ] **Step 3: Add the three wrappers and publication-gate call** to current persisted, in-memory, and legacy persisted paths, including attempt 2 in bounded recovery.
- [ ] **Step 4: Run `pytest tests/test_supervisor_harness.py tests/test_run_orchestration.py tests/test_orchestrator_persistence.py -q`** and confirm they pass.

