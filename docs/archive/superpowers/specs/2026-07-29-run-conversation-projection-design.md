# Run Conversation Projection Design

## Goal

Expose `GET /api/v1/runs/{run_id}/conversation` so the frontend can render a
run's public execution progress as a deterministic Chinese group conversation.
The feature must not call an LLM, persist conversation state, or expose private
SharedState data.

## Public Contract

The response is:

```json
{
  "run_id": "run-1",
  "status": "running",
  "stage": "retrieval",
  "next_poll_ms": 1500,
  "messages": [
    {
      "seq": 1,
      "persona": "pm",
      "display_name": "项目经理·PM",
      "kind": "intro",
      "text": "……",
      "stage": "intent"
    }
  ]
}
```

`next_poll_ms` follows the existing status endpoint: `1500` for non-terminal
runs and `null` for terminal runs. A missing run returns HTTP 404.

Each message has exactly `seq`, `persona`, `display_name`, `kind`, `text`, and
`stage`. Personas are:

- `intent_consultant` / `需求顾问·小意`
- `job_scout` / `岗位顾问·小检`
- `strategist` / `规划师·小策`
- `pm` / `项目经理·PM`

## Architecture and Privacy Boundary

`app/api/conversation_projector.py` is a pure deterministic projector. It
accepts only:

- the persisted `MatchRun`, including public `approved_plan` and stage/status;
- recovery events already reduced to the public allow-list in
  `app/agents/trace.py`;
- an optional validated `ProductResult`.

The API adapter in `app/api/v1/runs.py` loads the run, validates the optional
result snapshot, and obtains recovery events through a focused trace helper.
It may retrieve the persisted snapshot to obtain `supervisor_log`, but it must
access no other snapshot key. The trace helper returns only `stage`, `reason`,
`attempt`, and `max_attempts`; prompts, provider errors, resume data, `user_id`,
and all non-allow-listed log content never reach the projector.

No SharedState schema, database schema, or existing endpoint behavior changes.
No LLM or embedding client is used.

## Message Timeline

Messages are rebuilt from public snapshots on every request. Sequence numbers
start at 1 and are assigned after deterministic timeline construction.

1. Any existing run receives the PM introduction.
2. Once intent is active or complete, the intent consultant restates the
   approved career goal, locked hard constraints, soft preferences, avoided
   roles, and requested result count.
3. During retrieval, the job scout announces SQL hard filtering followed by
   parallel BM25/Dense retrieval and job-id-level RRF fusion. Once retrieval is
   complete, a completion message is added; if a ProductResult exists it
   includes the candidate count.
4. During strategy, the strategist announces skill-gap analysis and
   evidence-grounded resume advice. A completion message is added once the
   stage has advanced.
5. During verification, the PM announces the publication checkpoint. Each
   allow-listed `reretrieval_loop` or `repair_loop` event produces one bounded
   recovery message in source order.
6. A completed run receives a tier-count summary, warning count, and Results
   page prompt. A failed, cancelled, or stale run receives a truthful terminal
   status message.
7. Warning and error codes are translated through deterministic Chinese
   templates. Known codes have specific explanations. Unknown codes use the
   fallback `中文兜底说明（代码：原始码）`.

Active-stage messages represent work in progress. Completion messages only
appear after the run advances beyond that stage or reaches a terminal status.
This makes polling incremental while keeping all earlier messages stable.

## Error Handling

- Missing run: HTTP 404 with the existing `run_id not found` detail.
- Non-terminal run: HTTP 200 with messages available through the current stage
  and `next_poll_ms=1500`.
- Terminal run: HTTP 200 with `next_poll_ms=null`.
- A result snapshot is validated as `ProductResult` before projection.
- Duplicate warning codes from the run and ProductResult are de-duplicated in
  first-seen order.

## Tests and Generated Contracts

`tests/test_conversation_api.py` covers:

- all four personas and stable ordering for a completed run;
- reretrieval and repair recovery announcements;
- known and unknown warning translations;
- 404;
- non-terminal incremental output and polling;
- serialized privacy assertions covering `normalized_base_resume`, `user_id`,
  and a resume text sample.

The OpenAPI snapshot is regenerated with `scripts/export_openapi.py`, then
`frontend/src/api/generated.ts` is regenerated with the existing
`frontend/package.json` `api:generate` command. The snapshot test, focused
conversation tests, frontend API check, and the requested full pytest command
must pass before completion is reported.
