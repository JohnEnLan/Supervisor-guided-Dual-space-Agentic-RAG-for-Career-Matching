# Supervisor Harness Deterministic Checkpoints Design

## Goal

Define the existing orchestration and Supervisor policy as one lightweight
Supervisor Harness, then add deterministic checks before and after the Intent,
Matching, and Strategy agents plus a final publication gate.

## Scope

The implementation keeps ordinary async Python functions, one FastAPI service,
PostgreSQL-backed `SharedState`, three prompt-differentiated business agents, and
the existing bounded recovery loops. It does not add LangGraph, new services, or
an LLM call at every checkpoint.

## Architecture

`app/agents/orchestrator.py` remains the workflow executor. Together with the LLM
policy in `app/agents/supervisor.py` and the new deterministic checkpoint policy,
it is documented and operated as the Supervisor Harness:

- workflow orchestration;
- state and locked-constraint management;
- agent input/output verification;
- bounded re-retrieval and repair;
- final publication gate.

Checkpoint records are appended to the existing `state.supervisor_log`; no new
process-global or database state is introduced.

## Checkpoints

The harness records these checkpoints for every execution path, including a
bounded recovery attempt:

1. `intent_input`: validates the explicit goal and presence of resume context.
2. `intent_output`: checks whether a usable goal/profile exists after Intent.
3. `matching_input`: validates `top_k`, retrieval-plan shapes, and equality with
   any approved locked hard constraints.
4. `matching_output`: checks candidate uniqueness, ranking-row alignment, and
   whether retrieved evidence exists.
5. `strategy_input`: records whether the Strategy Agent has candidates to use.
6. `strategy_output`: checks that recommendations belong to the retrieved set
   and carry JD evidence identifiers.
7. `publication_gate`: combines deterministic findings with final Supervisor
   verification before `project_product_result` filters unsafe recommendations.

Input contract failures that would make an external Agent call invalid are
blocking. Empty retrieval and missing optional outputs are warnings, so the
existing product projector can still return an empty or warning-bearing result.

## Logging contract

Each record contains only structural information:

```json
{
  "stage": "supervisor_checkpoint",
  "checkpoint": "matching_output",
  "agent": "matching_agent",
  "phase": "after",
  "attempt": 1,
  "status": "passed | warning | blocked",
  "issue_codes": [],
  "metrics": {}
}
```

It does not copy resume text, private user identifiers, or full job content.

## Error and recovery behavior

- Blocking input-contract failures raise a typed `SupervisorCheckpointError`
  before the expensive Agent call.
- Warnings are logged and processing continues.
- Re-retrieval remains bounded by the existing configured maximum and may not
  relax approved hard constraints.
- The final projector remains the only public-output projection and removes
  recommendations with verified hard failures or missing original JD evidence.

## Tests

- Unit tests cover checkpoint status, locked-constraint rejection, and structural
  warning detection.
- Orchestration tests prove the six Agent checkpoints and publication gate occur
  in order without extra LLM calls.
- Existing run-persistence tests continue to prove state is saved between stages.

