# Run Conversation Projection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic, privacy-safe run conversation endpoint with incremental progress messages and generated API contracts.

**Architecture:** A pure projector converts `MatchRun`, allow-listed recovery events, and optional `ProductResult` into public message DTOs. The v1 route performs only data loading and validation, while `trace.py` remains the sole boundary that reduces supervisor log entries to public recovery events.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, pytest, OpenAPI, openapi-typescript

## Global Constraints

- Do not change SharedState or database schemas.
- Do not call an LLM or embedding provider.
- Do not change existing endpoint behavior.
- Access no SharedState snapshot key other than `supervisor_log`.
- Conversation text may contain only approved-plan fields, allow-listed recovery events, ProductResult counts, and warning/error codes.
- Preserve all pre-existing untracked files.
- Use the existing 1500 ms non-terminal polling interval and `null` for terminal runs.

---

### Task 1: Lock the Conversation API Behavior

**Files:**
- Create: `tests/test_conversation_api.py`

**Interfaces:**
- Consumes: `MatchRun`, `RunStage`, `RunStatus`, `ProductResult`, and the v1 router.
- Produces: executable API expectations for `GET /api/v1/runs/{run_id}/conversation`.

- [ ] **Step 1: Write failing API tests**

Create tests that monkeypatch `app.api.v1.runs.get_run` and
`load_state_snapshot`. Assert:

```python
payload == {
    "run_id": "run-1",
    "status": "running",
    "stage": "retrieval",
    "next_poll_ms": 1500,
    "messages": [...],
}
```

The completed fixture must assert persona order contains all of:

```python
["pm", "intent_consultant", "job_scout", "strategist"]
```

Recovery fixtures must contain `reretrieval_loop` and `repair_loop`, warning
fixtures must contain known and unknown Chinese explanations, and serialized
output must exclude:

```python
["normalized_base_resume", "user_id", "这是一段绝不能泄露的简历原文"]
```

- [ ] **Step 2: Verify the tests fail for the missing route**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_conversation_api.py -q -p no:cacheprovider --basetemp=tmp/ptx-conversation-red
```

Expected: failures with HTTP 404 because the conversation route is absent.

### Task 2: Add Public DTOs and Trace Allow-List Helper

**Files:**
- Modify: `app/api/v1/schemas.py`
- Modify: `app/agents/trace.py`

**Interfaces:**
- Consumes: supervisor log dictionaries.
- Produces: `build_public_recovery_events(supervisor_log)` plus
  `ConversationMessageResponse` and `RunConversationResponse`.

- [ ] **Step 1: Add strict Pydantic response models**

Add:

```python
class ConversationMessageResponse(PublicDTO):
    seq: int = Field(ge=1)
    persona: Literal["intent_consultant", "job_scout", "strategist", "pm"]
    display_name: str
    kind: Literal[
        "intro", "brief", "progress", "checkpoint",
        "recovery", "result", "warning", "error"
    ]
    text: str
    stage: str


class RunConversationResponse(PublicDTO):
    run_id: str
    status: str
    stage: str | None = None
    next_poll_ms: int | None = None
    messages: list[ConversationMessageResponse] = Field(default_factory=list)
```

- [ ] **Step 2: Extract the existing recovery allow-list**

Refactor `build_public_explain` to call:

```python
def build_public_recovery_events(
    supervisor_log: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ...
```

The helper must retain only events with stages `clarification_loop`,
`reretrieval_loop`, and `repair_loop`, and return only `stage`, `reason`,
`attempt`, and `max_attempts`.

- [ ] **Step 3: Run existing public trace tests**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_public_trace.py -q -p no:cacheprovider --basetemp=tmp/ptx-trace
```

Expected: all existing tests pass.

### Task 3: Implement the Pure Projector and Route

**Files:**
- Create: `app/api/conversation_projector.py`
- Modify: `app/api/v1/runs.py`

**Interfaces:**
- Consumes: `project_run_conversation(run, recovery_events, result)`.
- Produces: ordered `ConversationMessageResponse` values and the HTTP endpoint.

- [ ] **Step 1: Implement deterministic projection**

Define:

```python
def project_run_conversation(
    *,
    run: MatchRun,
    recovery_events: list[dict[str, Any]],
    result: ProductResult | None,
) -> list[ConversationMessageResponse]:
    ...
```

Use fixed stage gates, stable public-value formatting, stable de-duplication,
tier counts for `now_fit`, `stretch_fit`, and `bridge_role`, and known-code
translation dictionaries with the confirmed unknown-code fallback.

- [ ] **Step 2: Add the route adapter**

Add:

```python
@router.get(
    "/runs/{run_id}/conversation",
    response_model=RunConversationResponse,
)
async def run_conversation(run_id: str) -> RunConversationResponse:
    ...
```

The route must return 404 for a missing run, validate an optional result
snapshot, load only `snapshot.get("supervisor_log", [])`, pass that list through
`build_public_recovery_events`, and set:

```python
next_poll_ms = None if run.status in TERMINAL_STATUSES else 1500
```

- [ ] **Step 3: Verify the focused tests turn green**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_conversation_api.py tests/test_public_trace.py -q -p no:cacheprovider --basetemp=tmp/ptx-conversation-green
```

Expected: all focused tests pass.

### Task 4: Update OpenAPI and Frontend Types

**Files:**
- Modify: `tests/test_api_v1.py`
- Modify: `tests/snapshots/openapi_v1.json`
- Modify: `frontend/src/api/generated.ts`

**Interfaces:**
- Consumes: FastAPI's registered response model.
- Produces: current OpenAPI snapshot and generated TypeScript route/schema types.

- [ ] **Step 1: Add the conversation path to the public route assertion**

Add:

```python
"/api/v1/runs/{run_id}/conversation",
```

to `PUBLIC_PATHS`.

- [ ] **Step 2: Regenerate the OpenAPI snapshot**

Run:

```powershell
.venv\Scripts\python.exe scripts/export_openapi.py
```

Expected: `tests/snapshots/openapi_v1.json` contains the conversation path and
response schemas.

- [ ] **Step 3: Regenerate and check TypeScript API types**

Run:

```powershell
npm run api:generate
npm run api:check
```

from `frontend`.

Expected: `frontend/src/api/generated.ts` includes the conversation operation,
and the check exits with code 0.

- [ ] **Step 4: Run API contract tests**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_api_v1.py tests/test_conversation_api.py -q -p no:cacheprovider --basetemp=tmp/ptx-api-contract
```

Expected: all tests pass, including the OpenAPI snapshot assertion.

### Task 5: Full Verification

**Files:**
- Verify only.

**Interfaces:**
- Consumes: the complete repository test suite.
- Produces: fresh evidence that the feature and baseline remain green.

- [ ] **Step 1: Check diff scope and whitespace**

Run:

```powershell
git diff --check
git status --short
```

Expected: only the planned feature, generated contracts, tests, and new design
and plan documents differ; all historical untracked files remain untouched.

- [ ] **Step 2: Run the required full suite**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/ -q -p no:cacheprovider --basetemp=tmp/ptx
```

Expected: at least 240 tests plus the new conversation tests pass with zero
failures.
