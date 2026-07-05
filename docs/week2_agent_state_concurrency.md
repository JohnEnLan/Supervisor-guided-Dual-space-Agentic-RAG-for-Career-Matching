# Week 2 Milestone: Agent Design, Shared State, and Multi-user Concurrency

This note can be used as draft dissertation material for the Week 2 milestone of
the Supervisor-guided Dual-space Agentic RAG career matching system. It describes
the implemented architecture rather than a future design.

## 1. Agent Design

The system implements a lightweight Agentic RAG pipeline without introducing a
heavy orchestration framework. The three business agents are ordinary async
Python components built on a shared `BaseAgent` abstraction:

```text
read SharedState -> build prompt -> call LLM -> parse JSON -> write SharedState
```

This keeps the agent layer close to the project constraints: the agents are not
separate services, and they communicate through one typed state object rather
than by passing informal natural-language summaries between each other.

The implemented stages are:

```text
Stage 0  Resume intake and normalization
Stage 1  Intent and career profile agent
Stage 2  Supervisor retrieval planning
Stage 3  Retrieval and matching agent
Stage 4  Resume and career strategy agent
Stage 5  Supervisor final verification
```

### Stage 1: Intent and Career Profile Agent

`IntentAgent` reads the normalized resume and the user's explicit goal text. It
extracts:

- current career goals
- hard constraints
- soft preferences
- roles to avoid

The important design choice is the distinction between hard constraints and soft
preferences. Hard constraints, such as location or visa requirements, are later
enforced by retrieval filters. Soft preferences are used for ranking or
relaxation. The agent also avoids inferring long-term goals unless the user
explicitly provides a long-term signal.

### Stage 2: Supervisor Planning

The Supervisor planning step checks whether the user's goal is too vague and
creates a retrieval plan. It can record a clarification loop, but the loop is
bounded by configuration. This satisfies the project rule that Supervisor logic
must be implemented as a controlled verification and intervention mechanism,
not as an open-ended autonomous loop.

The retrieval plan records:

- hard constraints
- soft preferences
- requested top-k
- whether the optional RAPTOR path is included

The plan is appended to `supervisor_log`, which makes the intervention traceable
for debugging and dissertation demonstration.

### Stage 3: Retrieval and Matching Agent

`MatchingAgent` wraps the hybrid retrieval layer. It builds a retrieval query
from the normalized resume, calls `hybrid_search`, writes retrieval diagnostics
to `retrieval_state`, and asks the LLM to classify candidates into:

- `now_fit`
- `stretch_fit`
- `bridge_role`

Every recommended role keeps job evidence identifiers and evidence text from
the retrieved candidates. If the LLM omits or invents evidence identifiers, the
agent falls back to the evidence attached to the retrieved candidate.

### Stage 4: Strategy Agent

`StrategyAgent` produces:

- skill gap analysis
- resume revision advice
- short, medium, and long-term career path suggestions

This stage is evidence-gated. Resume revision items must cite original resume
evidence spans. Skill gaps and career path items must cite either resume
evidence or job evidence. Unsupported items are dropped and counted in
`supervisor_log`.

### Stage 5: Supervisor Final Verification

The final Supervisor pass checks for:

- hard filter violations
- missing recommendation evidence
- resume advice fabrication risks
- too few retrieval results

If too few results are found and the retrieval plan contains soft preferences,
the orchestrator can run one re-retrieval pass with relaxed soft preferences.
The loop is explicitly marked in `supervisor_log` with `loop_used = 1` and the
final verification entry records `reretrieval_loop_used = 1`.

## 2. Shared Structured State

The central state object is `SharedState` in `app/state/schema.py`. It is the
single contract shared by normalization, agents, retrieval, Supervisor, API
routes, memory, and evaluation.

The main sub-states are:

```text
resume_state      normalized resume, extracted fields, original evidence spans
career_state      current goals, hard constraints, soft preferences, avoid roles
retrieval_state   candidate ids, filter log, ranking scores, evidence ids
strategy_state    recommended roles, resume advice, skill gaps, career path
feedback_state    application history, interview outcomes, user feedback
supervisor_log    planning, verification, repair, and re-retrieval records
```

The most important field for faithfulness is
`resume_state.original_evidence_spans`. Later agents are not allowed to invent
resume achievements. Resume advice is only accepted when it cites these original
evidence span ids. Matching explanations are similarly tied to job evidence ids
from the retrieval layer.

State is persisted through `app/db/state_store.py`. The API and orchestrator
always save and load by `session_id`:

```text
save_state(state, status)
load_state(session_id)
load_state_with_status(session_id)
```

This design makes the FastAPI process stateless with respect to business data.
The only process-level singleton is the asyncpg connection pool, which is
infrastructure rather than user state.

## 3. Multi-user Concurrency Architecture

The service exposes a submit-and-poll API:

```text
POST /resume          upload resume and queue normalization
POST /match           submit matching job and return immediately
GET  /status/{sid}    poll status and final state when ready
GET  /result/{sid}    fetch state for a session
POST /feedback        record outcome feedback
```

Long-running work is executed in FastAPI background tasks. The HTTP request
returns quickly with a `session_id` and a status, while the client polls
`/status/{session_id}`. Each background task reloads the state from Postgres by
session id before continuing, so work for one user does not depend on mutable
in-memory objects from another request.

The status lifecycle is stored alongside the JSON state:

```text
resume_queued -> resume_running -> resume_ready
match_queued  -> match_running  -> intent_done
              -> supervisor_planning_done -> retrieval_done
              -> strategy_done -> agentic_done
```

On errors, the background task appends a compact error record to
`supervisor_log` and writes a terminal error status such as `resume_error` or
`match_error`.

Concurrency is based on `asyncio`. Database access uses asyncpg with a reusable
pool, and external LLM or embedding calls are routed through asynchronous
clients with semaphores. This matches the workload profile: most time is spent
waiting for database, embedding, and LLM calls rather than doing CPU-bound work.

## 4. Day 14 Concurrency Self-test

The Day 14 buffer task adds a regression test for the Week 2 concurrency
milestone:

```text
tests/test_api_concurrency.py
```

The test starts three independent sessions and submits `/match` for all of them
concurrently with `asyncio.gather`. The mocked persisted orchestrator writes a
different recommendation into each session:

```text
day14-a -> day14-a-job
day14-b -> day14-b-job
day14-c -> day14-c-job
```

It then polls `/status/{session_id}` for every session and verifies:

- all three submissions return `202`
- each session reaches `agentic_done`
- each status response contains the same `session_id` that was requested
- each result contains only its own recommendation evidence
- no recommendation from one session appears in another session's state

This test provides a concrete Week 2 acceptance check: multiple users can submit
matching jobs concurrently, and the state and status for each session remain
isolated.

## 5. Dissertation Framing

The Week 2 implementation turns the project from a retrieval-only RAG baseline
into an Agentic RAG service with an auditable state contract. The main research
engineering contribution is not that the agents are complex autonomous workers,
but that each agent is constrained by a shared structured state and evidence
contract. This reduces unsupported generation and makes the pipeline inspectable.

The Supervisor is implemented as a bounded control layer. It does not replace
the retrieval and matching logic; instead, it checks planning quality and final
answer faithfulness, records interventions, and can trigger at most one
controlled re-retrieval or repair pass. This is suitable for a one-month
dissertation system because it demonstrates agentic supervision without
introducing unstable open-ended behavior.

The multi-user service architecture supports the dissertation's deployment
claim. FastAPI remains stateless, session state lives in PostgreSQL, and clients
interact through a submit-and-poll workflow. The Day 14 concurrent-session test
is the practical evidence that the Week 2 milestone has been reached.
