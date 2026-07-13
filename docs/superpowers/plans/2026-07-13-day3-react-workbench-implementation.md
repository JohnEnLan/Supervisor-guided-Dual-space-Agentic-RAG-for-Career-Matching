# Day 3 React Workbench, Progress Board, and Monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the complete P0 React career-matching flow with visible Intent Agent consultation, server-authoritative progress, evidence explanations, and a privacy-safe read-only monitoring page.

**Architecture:** Keep FastAPI and PostgreSQL authoritative. Add the smallest public DTO and read-model increments needed by the React client, persist aggregate run metrics separately from private state, and generate all TypeScript API types from the committed OpenAPI snapshot. The React app uses route identifiers for recovery and TanStack Query for server-directed polling.

**Tech Stack:** Python 3.11+, FastAPI, asyncio, asyncpg, PostgreSQL/pgvector, Pydantic v2, React, TypeScript strict mode, Vite, React Router, TanStack Query, Vitest, Testing Library, Playwright, openapi-typescript.

## Global Constraints

- All user and run state remains in PostgreSQL by `session_id` or `run_id`; no business state enters process globals or browser storage.
- All FastAPI handlers and database/provider operations remain asynchronous; do not add threads, processes, Celery, or RQ.
- Three business Agents remain three bounded LLM calls with ordinary Python orchestration; do not add LangGraph, AutoGen, CrewAI, or another agent framework.
- Hard constraints remain SQL metadata filters. Add company-exclusive filtering to SQL and keep preferred companies as ranking preferences.
- Resume and JD explanations remain evidence-grounded; never render or claim hiring probability.
- Monitoring responses are explicit allow-lists and never expose `user_id`, resume text, prompts, provider errors, `state_snapshot`, or `supervisor_log`.
- P0 monitoring uses five-second HTTP polling; do not add WebSockets, Prometheus, Grafana, or a metrics message bus.
- Core TypeScript API code contains no explicit `any`; `tsconfig.json` enables `strict`.
- The primary flow is keyboard operable and has no horizontal overflow at 375, 768, or 1440 CSS pixels.
- External LLM and embedding calls continue to use their existing async Semaphores.

---

### Task 1: Visible Intent Consultation Contract

**Files:**
- Create: `app/domain/intent.py`
- Modify: `app/state/schema.py`
- Modify: `app/agents/intent_agent.py`
- Modify: `app/api/v1/schemas.py`
- Modify: `app/api/v1/sessions.py`
- Test: `tests/test_intent_consultation.py`
- Modify: `tests/test_api_v1.py`

**Interfaces:**
- Consumes: confirmed `SharedState.resume_state` and domain `IntentConsultInput` converted from the public request.
- Produces: `GET|POST /api/v1/sessions/{session_id}/intent-consult`, `CareerDirection`, `IntentConsultResponse`, and durable consultation fields in `CareerState`.

- [ ] **Step 1: Write failing domain and route tests**

```python
def test_intent_consult_requires_confirmed_resume(monkeypatch) -> None:
    async def metadata(_session_id: str):
        return {"exists": True, "resume_version": 1, "confirmed_resume_version": None}

    monkeypatch.setattr(sessions, "get_resume_metadata", metadata)
    response = client.post(
        "/api/v1/sessions/session-1/intent-consult",
        json={"mode": "explore", "target_roles": [], "target_companies": [], "company_exclusive": False},
    )
    assert response.status_code == 409


def test_explore_projection_drops_unknown_resume_evidence() -> None:
    state = SharedState(
        session_id="s1",
        user_id="u1",
        resume_state=ResumeState(original_evidence_spans=[{"span_id": "R1", "text": "Python"}]),
    )
    state.career_state.intent_directions = [
        {"role_family": "data", "title": "Data analyst", "rationale": "Python evidence", "resume_evidence_span_ids": ["R1", "UNKNOWN"], "primary_gap": "SQL", "entry_role": "Junior analyst"}
    ]
    payload = project_intent_consultation(state)
    assert payload.directions[0].resume_evidence_span_ids == ["R1"]
```

- [ ] **Step 2: Run the focused tests and confirm the missing-contract failure**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_intent_consultation.py tests/test_api_v1.py -q`

Expected: FAIL because the consultation DTOs, projector, and routes do not exist.

- [ ] **Step 3: Add durable consultation fields and strict public DTOs**

```python
class CareerState(BaseModel):
    current_goal: list[str] = Field(default_factory=list)
    long_term_goal: list[str] = Field(default_factory=list)
    hard_constraints: dict = Field(default_factory=dict)
    soft_preferences: dict = Field(default_factory=dict)
    avoid_roles: list[str] = Field(default_factory=list)
    intent_mode: Literal["targeted", "explore"] | None = None
    intent_consulted: bool = False
    intent_assistant_message: str = ""
    intent_directions: list[dict] = Field(default_factory=list)
    intent_needs_clarification: bool = False
    intent_clarification_question: str | None = None
    intent_clarification_used: int = Field(default=0, ge=0, le=1)


class IntentConsultInput(BaseModel):
    mode: Literal["targeted", "explore"]
    goal_text: str | None = Field(default=None, max_length=2000)
    target_roles: list[str] = Field(default_factory=list, max_length=10)
    target_companies: list[str] = Field(default_factory=list, max_length=10)
    company_exclusive: bool = False
    clarification_answer: str | None = Field(default=None, max_length=1000)
```

Define `IntentConsultInput` and `CareerDirection` in `app/domain/intent.py` so the Agent layer never imports API modules. Define `IntentConsultRequest`, `IntentConsultResponse`, and `ResumeEvidencePreview` in the API schema with `extra="forbid"`. Add an `evidence` list to `ResumePreviewResponse`, populated only from allow-listed `span_id` and `text` fields. Implement `project_intent_consultation(state)` by intersecting returned evidence IDs with confirmed resume evidence IDs.

- [ ] **Step 4: Implement one bounded visible Intent Agent call and GET/POST routes**

```python
async def run_visible_intent_consultation(
    state: SharedState, request: IntentConsultInput
) -> SharedState:
    if request.clarification_answer and state.career_state.intent_clarification_used >= 1:
        raise ValueError("clarification limit reached")
    goal = build_consultation_goal(request)
    state = await IntentConsultAgent(goal=goal, mode=request.mode).run(state)
    state.career_state.intent_consulted = not state.career_state.intent_needs_clarification
    return state
```

The targeted prompt normalizes roles, uses target companies as `preferred_companies`, and sets hard `companies` only for `company_exclusive=true`. The explore prompt returns at most three evidence-backed directions. POST saves the updated state; GET projects the last durable consultation or returns 404.

- [ ] **Step 5: Run focused tests and commit**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_intent_consultation.py tests/test_api_v1.py -q`

Expected: PASS.

Commit: `git commit -m "feat: add visible intent consultation API"`

---

### Task 2: Company Filters, Approved Brief Snapshot, and Intent Skip

**Files:**
- Modify: `app/agents/intent_agent.py`
- Modify: `app/retrieval/hybrid_search.py`
- Modify: `app/api/v1/sessions.py`
- Modify: `app/agents/orchestrator.py`
- Modify: `app/domain/run.py`
- Test: `tests/test_hybrid_search.py`
- Test: `tests/test_run_orchestration.py`
- Modify: `tests/test_api_v1.py`

**Interfaces:**
- Consumes: `CareerState.intent_consulted`, approved `MatchBrief`, hard `companies`, and soft `preferred_companies`.
- Produces: case-insensitive company SQL filtering, preferred-company score bonus, atomic session-state snapshot correctness, and no duplicate Intent call for consulted runs.

- [ ] **Step 1: Write failing filter and orchestration tests**

```python
def test_company_exclusive_constraint_is_case_insensitive_sql_filter() -> None:
    sql, params = _build_hard_filter_query({"companies": ["DeepMind", "OpenAI"]})
    assert "lower(company) = ANY" in sql
    assert params == [["deepmind", "openai"]]


@pytest.mark.asyncio
async def test_consulted_run_skips_execute_time_intent_agent(monkeypatch) -> None:
    state.career_state.intent_consulted = True
    calls = 0
    async def intent(current, _goal):
        nonlocal calls
        calls += 1
        return current
    monkeypatch.setattr(orchestrator, "run_intent_agent", intent)
    await orchestrator.run_persisted_agentic_match_run(run_id="run-1")
    assert calls == 0
```

- [ ] **Step 2: Verify the tests fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_hybrid_search.py tests/test_run_orchestration.py tests/test_api_v1.py -q`

Expected: FAIL because company filters and consulted-run skipping are absent.

- [ ] **Step 3: Extend filter allow-lists and scoring**

```python
companies = [str(value).casefold() for value in hard_constraints.get("companies") or [] if value]
if companies:
    placeholder = add_param(companies)
    clauses.append(f"lower(company) = ANY({placeholder}::text[])")

preferred_companies = {str(value).casefold() for value in soft_prefs.get("preferred_companies") or []}
if str(metadata.get("company") or "").casefold() in preferred_companies:
    bonus += 0.05
```

Add `companies` and `preferred_companies` to the Intent Agent allow-lists. Keep the total soft-preference bonus capped at `0.20`.

- [ ] **Step 4: Persist approved career inputs before `create_run` and skip duplicate intent**

Load the session state in `build_match_brief`, replace only the approved career fields, save it, and only then call `create_run`. Add `RunStage.INTENT`; a legacy run enters `intent`, performs the existing call, then moves to `retrieval`. A consulted run records a zero-cost skip and moves directly to `retrieval` without another LLM call.

- [ ] **Step 5: Run tests and commit**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_hybrid_search.py tests/test_run_orchestration.py tests/test_api_v1.py -q`

Expected: PASS.

Commit: `git commit -m "feat: lock consulted intent into run execution"`

---

### Task 3: Server-Authoritative Progress and Typed Examiner Evidence

**Files:**
- Modify: `app/api/v1/schemas.py`
- Modify: `app/api/v1/runs.py`
- Modify: `app/agents/trace.py`
- Modify: `app/domain/run.py`
- Test: `tests/test_run_progress.py`
- Modify: `tests/test_public_trace.py`
- Modify: `tests/test_api_v1.py`

**Interfaces:**
- Consumes: `MatchRun.status`, `MatchRun.stage`, `MatchRun.plan_version`, `MatchRun.plan_hash`, and implicit evidence in retrieval rows.
- Produces: `retry_after_ms`, `completed_stages`, `total_stages=7`, recoverable plan identifiers, and typed `case_evidence`.

- [ ] **Step 1: Write failing pure progress tests**

```python
@pytest.mark.parametrize(
    ("status", "stage", "completed"),
    [
        (RunStatus.QUEUED, None, ["resume"]),
        (RunStatus.RUNNING, RunStage.RETRIEVAL, ["resume", "intent"]),
        (RunStatus.RUNNING, RunStage.VERIFICATION, ["resume", "intent", "retrieval", "strategy"]),
        (RunStatus.COMPLETED, RunStage.FINALIZATION, ["resume", "intent", "retrieval", "strategy", "verification", "finalization", "result"]),
    ],
)
def test_public_progress(status, stage, completed) -> None:
    assert public_progress(status=status, stage=stage) == completed
```

- [ ] **Step 2: Verify failure**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_run_progress.py tests/test_public_trace.py tests/test_api_v1.py -q`

Expected: FAIL because progress fields and typed case evidence are missing.

- [ ] **Step 3: Implement deterministic progress mapping**

```python
PUBLIC_STAGE_ORDER = (
    "resume", "intent", "retrieval", "strategy", "verification", "finalization", "result"
)

def public_progress(*, status: RunStatus, stage: RunStage | None) -> list[str]:
    if status in {RunStatus.COMPLETED, RunStatus.COMPLETED_WITH_WARNINGS}:
        return list(PUBLIC_STAGE_ORDER)
    active = stage.value if stage else "intent"
    index = PUBLIC_STAGE_ORDER.index(active) if active in PUBLIC_STAGE_ORDER else 1
    return list(PUBLIC_STAGE_ORDER[:index])
```

Add `plan_hash: str | None` to `MatchRun` and select it in every run-store `RETURNING`/`SELECT` projection. Return `retry_after_ms=1500` for queued/running and `None` for terminal states. Return `total_stages=7`, the pure mapping output, `plan_version`, and `plan_hash`. The hash is a non-secret integrity value and lets a refreshed `plan_ready` Run page execute the approved immutable plan without browser storage.

- [ ] **Step 4: Add typed case evidence projection**

Define `CaseEvidenceResponse(case_id, highest_stage, confidence)` and add it to each `RankTraceResponse`. Project only those three fields from `implicit_evidence`; retain `case_ids` for compatibility during P0.

- [ ] **Step 5: Run tests and commit**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_run_progress.py tests/test_public_trace.py tests/test_api_v1.py -q`

Expected: PASS.

Commit: `git commit -m "feat: expose safe run progress and case evidence"`

---

### Task 4: Privacy-Safe Monitoring Read Model

**Files:**
- Create: `app/db/migrations/0003_run_monitoring_read_model.sql`
- Modify: `app/db/schema.sql`
- Create: `app/domain/monitoring.py`
- Create: `app/db/monitoring_store.py`
- Modify: `app/agents/orchestrator.py`
- Modify: `app/config.py`
- Modify: `.env.example`
- Test: `tests/test_monitoring_metrics.py`
- Test: `tests/test_monitoring_store.py`
- Modify: `tests/test_run_orchestration.py`

**Interfaces:**
- Consumes: final `SharedState`, `ProductResult`, and terminal `match_runs` rows.
- Produces: `RunMetricSnapshot`, `save_run_metrics`, `get_monitoring_overview`, and `list_recent_runs`.

- [ ] **Step 1: Write failing pure metric tests**

```python
def test_build_run_metrics_uses_only_allow_list_counts() -> None:
    metrics = build_run_metrics(state, result)
    assert metrics.recommendation_count == 2
    assert metrics.recommendations_with_jd_evidence == 2
    assert metrics.implicit_case_count == 1
    assert metrics.reordered_job_count == 1
    serialized = metrics.model_dump_json()
    assert "resume" not in serialized.casefold()
    assert "prompt" not in serialized.casefold()
```

- [ ] **Step 2: Verify failure**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_monitoring_metrics.py tests/test_monitoring_store.py tests/test_run_orchestration.py -q`

Expected: FAIL because monitoring domain/store files and table are absent.

- [ ] **Step 3: Add the additive read-model table**

```sql
CREATE TABLE IF NOT EXISTS run_metrics (
    run_id TEXT PRIMARY KEY REFERENCES match_runs(run_id) ON DELETE CASCADE,
    recommendation_count INTEGER NOT NULL DEFAULT 0,
    recommendations_with_jd_evidence INTEGER NOT NULL DEFAULT 0,
    implicit_case_count INTEGER NOT NULL DEFAULT 0,
    reordered_job_count INTEGER NOT NULL DEFAULT 0,
    stage_durations_ms JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_run_metrics_created ON run_metrics (created_at DESC);
```

Apply the same additive DDL to `app/db/schema.sql`.

- [ ] **Step 4: Implement the pure projector and async store**

`build_run_metrics` counts public recommendation evidence, unique implicit case IDs, explicit/final rank changes, and allow-listed stage durations. `save_run_metrics` upserts by `run_id`. `get_monitoring_overview(window_hours)` uses bounded `1..720` hours and PostgreSQL `percentile_cont` for total duration; it calculates per-stage percentiles from only `run_metrics.stage_durations_ms`. `list_recent_runs` returns at most 100 safe rows.

Measure finalization before the final state snapshot so every completed run has an allow-listed finalization duration. After `save_run_result`, the orchestrator attempts `save_run_metrics` in a protected observability block so a metrics write cannot downgrade a completed run. Add `monitoring_enabled: bool = False` and `MONITORING_ENABLED=false`.

- [ ] **Step 5: Run migration/store/orchestration tests and commit**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_monitoring_metrics.py tests/test_monitoring_store.py tests/test_run_orchestration.py tests/test_run_store.py -q`

Expected: PASS.

Commit: `git commit -m "feat: persist privacy-safe run monitoring metrics"`

---

### Task 5: Monitoring API and OpenAPI Contract

**Files:**
- Create: `app/api/v1/monitoring.py`
- Modify: `app/api/v1/schemas.py`
- Modify: `app/api/v1/router.py`
- Modify: `tests/test_api_v1.py`
- Create: `tests/test_monitoring_api.py`
- Modify: `tests/snapshots/openapi_v1.json`

**Interfaces:**
- Consumes: `settings.monitoring_enabled`, `get_monitoring_overview`, and `list_recent_runs`.
- Produces: capability-gated monitoring overview and recent-run endpoints.

- [ ] **Step 1: Write failing route and privacy tests**

```python
def test_monitoring_disabled_returns_404(monkeypatch) -> None:
    monkeypatch.setattr(monitoring.settings, "monitoring_enabled", False)
    assert client.get("/api/v1/monitoring/overview").status_code == 404


def test_monitoring_response_has_no_private_fields(monkeypatch) -> None:
    monkeypatch.setattr(monitoring.settings, "monitoring_enabled", True)
    response = client.get("/api/v1/monitoring/runs?window_hours=24&limit=20")
    assert response.status_code == 200
    for forbidden in ("user_id", "state_snapshot", "resume", "prompt", "provider_error"):
        assert forbidden not in response.text.casefold()
```

- [ ] **Step 2: Verify failure**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_monitoring_api.py tests/test_api_v1.py -q`

Expected: FAIL because the monitoring router and DTOs are absent.

- [ ] **Step 3: Add strict DTOs and capability-gated routes**

Define `MonitoringOverviewResponse`, `StageLatencyResponse`, `RecentRunResponse`, and `RecentRunsResponse`, all inheriting `PublicDTO`. Validate `window_hours` with `ge=1, le=720` and `limit` with `ge=1, le=100`. Return 404 when capability is disabled and include `monitoring_enabled` in `CapabilitiesResponse`.

- [ ] **Step 4: Export and verify OpenAPI**

Run: `./.venv/Scripts/python.exe scripts/export_openapi.py`

Expected: `tests/snapshots/openapi_v1.json` includes intent, progress, typed evidence, and monitoring schemas/routes.

Run: `./.venv/Scripts/python.exe -m pytest tests/test_api_v1.py tests/test_monitoring_api.py -q`

Expected: PASS, including snapshot equality.

- [ ] **Step 5: Commit**

Commit: `git commit -m "feat: expose read-only monitoring API"`

---

### Task 6: React Toolchain and Generated API Client

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/package-lock.json`
- Create: `frontend/index.html`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tsconfig.node.json`
- Create: `frontend/playwright.config.ts`
- Create: `frontend/src/vite-env.d.ts`
- Create: `frontend/src/test/setup.ts`
- Create: `frontend/src/api/generated.ts`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/api/queries.ts`
- Test: `frontend/src/api/client.test.ts`

**Interfaces:**
- Consumes: `tests/snapshots/openapi_v1.json`.
- Produces: strict generated `paths` types, `ApiError`, typed request helpers, and query factories.

- [ ] **Step 1: Create the package scripts and install dependencies**

`package.json` scripts:

```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "typecheck": "tsc -b --pretty false",
    "test": "vitest run",
    "test:watch": "vitest",
    "api:generate": "openapi-typescript ../tests/snapshots/openapi_v1.json -o src/api/generated.ts",
    "e2e": "playwright test"
  }
}
```

Install React, React DOM, React Router, TanStack Query, and Lucide React. Install Vite, TypeScript, the React Vite plugin, Vitest, jsdom, Testing Library, jest-dom, user-event, openapi-typescript, and Playwright as development dependencies. Generate and commit `package-lock.json`.

- [ ] **Step 2: Generate API types and write a failing client test**

Run: `npm.cmd run api:generate`

```typescript
it("throws a typed safe error", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(
    JSON.stringify({ detail: { message: "not ready", recovery: { action: "poll_status" } } }),
    { status: 409, headers: { "content-type": "application/json" } },
  )));
  await expect(apiRequest("/runs/r1/result", { method: "GET" })).rejects.toMatchObject({ status: 409 });
});
```

- [ ] **Step 3: Implement the typed client and query factories**

```typescript
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly recovery?: { action?: string; status_url?: string },
  ) { super(message); }
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1${path}`, init);
  const payload: unknown = await response.json();
  if (!response.ok) throw toApiError(response.status, payload);
  return payload as T;
}
```

Query factories use generated response aliases and stable keys: `capabilities`, `resumePreview(sessionId)`, `intentConsult(sessionId)`, `runStatus(runId)`, `runResult(runId)`, `runExplain(runId)`, `monitoringOverview(hours)`, and `monitoringRuns(hours)`.

- [ ] **Step 4: Run client tests, typecheck, and commit**

Run: `npm.cmd test -- src/api/client.test.ts`

Expected: PASS.

Run: `npm.cmd run typecheck`

Expected: PASS with no explicit `any` in core API files.

Commit: `git commit -m "feat: scaffold typed React API client"`

---

### Task 7: Application Shell and Whole-Flow Progress Board

**Files:**
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/app/App.tsx`
- Create: `frontend/src/app/router.tsx`
- Create: `frontend/src/app/providers.tsx`
- Create: `frontend/src/app/ProgressBoard.tsx`
- Create: `frontend/src/app/ProgressBoard.test.tsx`
- Create: `frontend/src/styles/tokens.css`
- Create: `frontend/src/styles/global.css`

**Interfaces:**
- Consumes: route context plus `completed_stages`, active stage, and `total_stages`.
- Produces: responsive workbench shell, capability-aware navigation, and accessible progress rendering.

- [ ] **Step 1: Write failing progress-board tests**

```tsx
it("renders seven real stages without a percentage", () => {
  render(<ProgressBoard completedStages={["resume", "intent"]} activeStage="retrieval" totalStages={7} />);
  expect(screen.getByText("检索匹配")).toHaveAttribute("aria-current", "step");
  expect(screen.getByText("第 3/7 阶段")).toBeInTheDocument();
  expect(screen.queryByText(/%/)).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Verify failure**

Run: `npm.cmd test -- src/app/ProgressBoard.test.tsx`

Expected: FAIL because the application shell does not exist.

- [ ] **Step 3: Implement providers, router, shell, and progress board**

Use `QueryClientProvider`, `RouterProvider`, an error boundary, and routes from the approved spec. `ProgressBoard` uses an ordered constant with Chinese labels, `<ol>`, `aria-current="step"`, visible text completion marks, and a native `<details>` compact representation below 600 px.

Tokens use ivory background, white surfaces, navy primary, teal evidence, amber warnings, restrained red failures, system fonts, 44 px minimum control targets, visible `:focus-visible`, and `prefers-reduced-motion`.

- [ ] **Step 4: Run tests/build and commit**

Run: `npm.cmd test -- src/app/ProgressBoard.test.tsx && npm.cmd run build`

Expected: PASS.

Commit: `git commit -m "feat: add responsive workbench progress shell"`

---

### Task 8: Session Upload and Resume Review

**Files:**
- Create: `frontend/src/features/session/NewSessionPage.tsx`
- Create: `frontend/src/features/session/NewSessionPage.test.tsx`
- Create: `frontend/src/features/session/ResumeReviewPage.tsx`
- Create: `frontend/src/features/session/ResumeReviewPage.test.tsx`

**Interfaces:**
- Consumes: session-create, resume-upload, resume-preview, and resume-confirm API operations.
- Produces: upload-to-confirm flow and navigation to `/sessions/:sessionId/brief`.

- [ ] **Step 1: Write failing upload and review tests**

```tsx
it("accepts one supported resume and navigates after upload", async () => {
  const file = new File(["resume"], "resume.txt", { type: "text/plain" });
  await user.upload(screen.getByLabelText("选择简历文件"), file);
  await user.click(screen.getByRole("button", { name: "上传并开始" }));
  expect(mockNavigate).toHaveBeenCalledWith("/sessions/session-1/resume");
});

it("shows one primary confirmation action", () => {
  renderResumeReview();
  expect(screen.getAllByRole("button", { name: "确认简历" })).toHaveLength(1);
  expect(screen.getByText("Python")).toBeInTheDocument();
});
```

- [ ] **Step 2: Verify failure**

Run: `npm.cmd test -- src/features/session`

Expected: FAIL because the pages do not exist.

- [ ] **Step 3: Implement upload and resume review**

Create an opaque `crypto.randomUUID()` visitor ID only for the session-create request. Validate `.pdf`, `.docx`, and `.txt`, then send `FormData`. Resume Review polls only while preview returns 409, renders skills, experience, education, projects, and quality warnings, and uses one primary “确认简历” button. It never renders normalized full resume text.

- [ ] **Step 4: Run tests and commit**

Run: `npm.cmd test -- src/features/session && npm.cmd run typecheck`

Expected: PASS.

Commit: `git commit -m "feat: add resume upload and confirmation flow"`

---

### Task 9: Intent Consultation and Match Brief

**Files:**
- Create: `frontend/src/features/brief/MatchBriefPage.tsx`
- Create: `frontend/src/features/brief/MatchBriefPage.test.tsx`

**Interfaces:**
- Consumes: intent GET/POST and match-brief POST operations.
- Produces: targeted/explore interaction, one clarification, approved canonical brief, and run creation.

- [ ] **Step 1: Write failing branch tests**

```tsx
it("shows target role and company fields only for targeted mode", async () => {
  await user.click(screen.getByRole("radio", { name: "我已有目标" }));
  expect(screen.getByLabelText("目标岗位" )).toBeInTheDocument();
  expect(screen.getByLabelText("目标公司" )).toBeInTheDocument();
});

it("selects one explored direction without another agent call", async () => {
  await user.click(screen.getByRole("button", { name: "选择数据分析方向" }));
  expect(intentMutation).toHaveBeenCalledTimes(1);
  expect(screen.getByLabelText("职业目标")).toHaveValue("Data analyst");
});
```

- [ ] **Step 2: Verify failure**

Run: `npm.cmd test -- src/features/brief/MatchBriefPage.test.tsx`

Expected: FAIL because the page does not exist.

- [ ] **Step 3: Implement both Intent branches and approved brief**

Ask the target-career/company question first. Targeted mode submits roles, companies, context, and company-exclusive choice. Explore mode renders at most three direction cards with evidence references and lets selection populate the form locally. Show at most one clarification field. After consultation, reveal only goal, locations, visa requirement, role families, avoided roles, company fields, and result count. Display canonical brief and an eight-character plan-hash fingerprint before execute.

- [ ] **Step 4: Run tests and commit**

Run: `npm.cmd test -- src/features/brief/MatchBriefPage.test.tsx && npm.cmd run typecheck`

Expected: PASS and no model/RAPTOR/alpha controls in the DOM.

Commit: `git commit -m "feat: add visible intent and match brief flow"`

---

### Task 10: Run Polling and Recovery

**Files:**
- Create: `frontend/src/features/run/RunPage.tsx`
- Create: `frontend/src/features/run/RunPage.test.tsx`

**Interfaces:**
- Consumes: execute and status endpoints, `retry_after_ms`, `completed_stages`, and safe recovery errors.
- Produces: refresh-safe run page, terminal stop, Results navigation, and failure recovery.

- [ ] **Step 1: Write failing polling tests**

```tsx
it("uses server retry interval and stops in terminal state", () => {
  expect(runStatusRefetchInterval({ state: { data: { retry_after_ms: 1700, status: "running" } } })).toBe(1700);
  expect(runStatusRefetchInterval({ state: { data: { retry_after_ms: null, status: "completed" } } })).toBe(false);
});
```

- [ ] **Step 2: Verify failure**

Run: `npm.cmd test -- src/features/run/RunPage.test.tsx`

Expected: FAIL because run polling logic is absent.

- [ ] **Step 3: Implement execution, polling, and recovery states**

Query status by URL `runId` first. When status is `plan_ready`, execute exactly once using the returned approved plan version/hash; if another tab wins and execute returns 409, refetch status instead of reporting a fatal error. Pass response progress into the global board and stop refetching when `retry_after_ms` is null. Completed and completed-with-warnings link to Results. Failed/stale show safe error code and actions to return to Brief or create a new run. Network failure preserves the route and exposes retry.

- [ ] **Step 4: Run tests and commit**

Run: `npm.cmd test -- src/features/run/RunPage.test.tsx && npm.cmd run typecheck`

Expected: PASS.

Commit: `git commit -m "feat: add server-directed run polling"`

---

### Task 11: Results, Evidence, Examiner View, and Reaction

**Files:**
- Create: `frontend/src/features/results/ResultsPage.tsx`
- Create: `frontend/src/features/results/ResultsPage.test.tsx`
- Create: `frontend/src/features/results/EvidenceDrawer.tsx`
- Create: `frontend/src/features/results/EvidenceDrawer.test.tsx`
- Create: `frontend/src/features/evaluation/EvaluationRunPage.tsx`
- Create: `frontend/src/features/evaluation/EvaluationRunPage.test.tsx`
- Create: `frontend/src/features/feedback/ReactionForm.tsx`
- Create: `frontend/src/features/feedback/ReactionForm.test.tsx`

**Interfaces:**
- Consumes: result, explain, capabilities, and reaction endpoints.
- Produces: one recommendation list, evidence dialog, examiner trace, and safe feedback.

- [ ] **Step 1: Write failing result and accessibility tests**

```tsx
it("restores focus to the evidence trigger", async () => {
  const trigger = screen.getByRole("button", { name: "查看证据" });
  await user.click(trigger);
  await user.keyboard("{Escape}");
  expect(trigger).toHaveFocus();
});

it("never renders a hiring probability", () => {
  renderResults();
  expect(screen.queryByText(/录用概率|hiring probability|97%/i)).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Verify failure**

Run: `npm.cmd test -- src/features/results src/features/evaluation src/features/feedback`

Expected: FAIL because the result features do not exist.

- [ ] **Step 3: Implement Results and Evidence Drawer**

Render one selectable recommendation list and one detail pane. Show title, company, location, tier, concise explanation, skill gaps, JD evidence, optional resume evidence, deterministic must-have hits, resume strategy, and career path. Use native dialog behavior with Escape/backdrop/close handling, focus containment, and exact trigger restoration.

- [ ] **Step 4: Implement capability-gated examiner and reaction features**

When explain capability is enabled, show explicit/implicit/final ranks, typed anonymous case evidence, effective implicit weights, stage duration, warnings, and bounded recovery events. Otherwise show an unavailable state. Reaction posts job ID, outcome, optional reason/rating, and `crypto.randomUUID()` idempotency key; copy states that feedback is not automatically published as an anonymous case.

- [ ] **Step 5: Run tests and commit**

Run: `npm.cmd test -- src/features/results src/features/evaluation src/features/feedback && npm.cmd run build`

Expected: PASS.

Commit: `git commit -m "feat: add evidence results and examiner trace"`

---

### Task 12: Read-Only Monitoring Page

**Files:**
- Create: `frontend/src/features/monitoring/MonitoringPage.tsx`
- Create: `frontend/src/features/monitoring/MonitoringPage.test.tsx`
- Modify: `frontend/src/app/router.tsx`
- Modify: `frontend/src/app/App.tsx`

**Interfaces:**
- Consumes: monitoring capability, overview, and recent-runs endpoints.
- Produces: five-second read-only monitoring page with safe retry behavior.

- [ ] **Step 1: Write failing capability and metric tests**

```tsx
it("hides monitoring when capability is disabled", () => {
  renderMonitoring({ monitoring_enabled: false });
  expect(screen.getByText("运行监控未开启")).toBeInTheDocument();
  expect(screen.queryByText("删除运行")).not.toBeInTheDocument();
});

it("renders volume latency quality and dual-space metrics", () => {
  renderMonitoring({ monitoring_enabled: true });
  expect(screen.getByText("运行总量")).toBeInTheDocument();
  expect(screen.getByText("P95 总耗时")).toBeInTheDocument();
  expect(screen.getByText("JD 证据覆盖率")).toBeInTheDocument();
  expect(screen.getByText("双空间重排")).toBeInTheDocument();
});
```

- [ ] **Step 2: Verify failure**

Run: `npm.cmd test -- src/features/monitoring/MonitoringPage.test.tsx`

Expected: FAIL because the page does not exist.

- [ ] **Step 3: Implement the monitoring view**

Use a 24-hour default window with 1/24/168-hour choices, overview metric groups, per-stage P50/P95 table, and recent-run table. Poll every 5000 ms only while capability is enabled. Preserve the last successful payload during network errors and show a retry button plus stale timestamp. Do not include mutation controls or private-data links.

- [ ] **Step 4: Run tests and commit**

Run: `npm.cmd test -- src/features/monitoring/MonitoringPage.test.tsx && npm.cmd run build`

Expected: PASS.

Commit: `git commit -m "feat: add privacy-safe run monitoring page"`

---

### Task 13: Full-Flow Browser Gates and Live Demonstration

**Files:**
- Create: `frontend/e2e/full-flow.spec.ts`
- Create: `frontend/e2e/monitoring.spec.ts`
- Modify: `frontend/playwright.config.ts`
- Modify: `README.md`

**Interfaces:**
- Consumes: complete frontend routes and `/api/v1` contracts.
- Produces: deterministic browser coverage, responsive/a11y gates, and documented local preview commands.

- [ ] **Step 1: Write deterministic route-fixture E2E tests**

The full-flow test intercepts `/api/v1` calls and covers upload, preview, confirm, targeted and explore consultation, brief, execute, polling, Results, Evidence Drawer, examiner capability on/off, reaction, and page refresh. Monitoring fixtures cover enabled/disabled and network-retry states.

For each width in `[375, 768, 1440]`, assert:

```typescript
const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
expect(overflow).toBe(false);
```

- [ ] **Step 2: Run all deterministic frontend gates**

Run: `npm.cmd test`

Expected: all Vitest suites PASS.

Run: `npm.cmd run typecheck && npm.cmd run build`

Expected: typecheck and Vite production build PASS.

Run: `npx.cmd playwright install chromium` then `npm.cmd run e2e`

Expected: all Playwright tests PASS at the configured viewports.

- [ ] **Step 3: Run backend regression gates**

Run: `./.venv/Scripts/python.exe -m pytest -q`

Expected: all existing and new backend tests PASS; test count is greater than 171.

- [ ] **Step 4: Apply migrations and run the real local stack**

Run from repository root: `./.venv/Scripts/python.exe -m app.db.migrate`

Run backend: `./.venv/Scripts/python.exe -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000`

Run frontend in another terminal: `npm.cmd run dev -- --host 127.0.0.1` from `frontend/`.

Open the Vite URL in the in-app browser. Complete one real smoke flow when provider credentials are available; otherwise verify the deterministic browser flow and monitoring fixtures.

- [ ] **Step 5: Run privacy scan, commit, and hand off**

Run: `rg -n "user_id|normalized_base_resume|supervisor_log|system_prompt|provider_error" frontend/src app/api/v1/monitoring.py app/db/monitoring_store.py`

Expected: no private value is rendered or returned; occurrences limited to explicit test assertions or server-side deny-list checks.

Commit: `git commit -m "test: verify complete React defense workbench"`

Document the local URLs, monitoring capability flag, test commands, and the fact that the preview binds to localhost rather than the public internet.
