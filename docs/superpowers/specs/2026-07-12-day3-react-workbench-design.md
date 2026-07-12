# Day 3 React Defense Workbench Design

**Date:** 2026-07-12

**Status:** Approved in conversation; awaiting written-spec review

**Scope:** P0 React workbench plus the minimum backend contract needed for visible Intent Agent consultation and server-directed polling

## 1. Objective and Scope

Build a single-purpose defense workbench that completes the P0 career-matching flow:

```text
Create session and upload resume
-> review and confirm normalized resume
-> consult Intent Agent
-> approve Match Brief
-> execute and recover a run
-> inspect one evidence-grounded result
-> optionally inspect examiner-only dual-space trace
-> submit a lightweight reaction
```

The workbench is not a marketing site. It will not include pricing, account settings, model settings, RAPTOR controls, alpha/beta controls, or provider configuration.

## 2. Product Principles

1. **The Intent Agent is visible and correctable.** It must help the user form or validate a career direction before Match Brief approval.
2. **The server is authoritative.** URL identifiers and public API responses restore the experience after refresh; business results are not stored in browser globals or local storage.
3. **Evidence precedes confidence.** The UI shows JD evidence, resume evidence, gaps, and provenance. It never displays hiring probabilities or guaranteed outcomes.
4. **Research detail is progressive.** Normal users see one coherent result. Examiner-only trace data lives on a capability-gated route.
5. **P0 stays bounded.** One workbench, one primary flow, one bounded clarification, and deterministic tests.

## 3. Visual System

The selected direction is a bright professional research workbench optimized for projection.

- Background: warm ivory and white surfaces.
- Primary: deep navy for navigation and primary actions.
- Evidence: teal for grounded evidence and successful completion.
- Warning/recovery: amber; destructive/failure states use restrained red.
- Typography: system stack led by `Aptos`, `Segoe UI`, and `Noto Sans SC`; no network font dependency.
- Layout: compact application shell, clear step navigation, generous reading width, and limited elevation.
- Motion: short state transitions only; respect `prefers-reduced-motion`.
- Prohibited patterns: marketing hero sections, decorative gradients, fake progress percentages, excessive card grids, and unlabelled icon-only controls.

## 4. Application Architecture

Use Vite, React, TypeScript strict mode, React Router, TanStack Query, Vitest, Testing Library, and Playwright.

```text
frontend/src/
  app/          shell, router, providers
  api/          generated OpenAPI types, fetch client, query options
  features/     session, brief, run, results, evaluation, feedback
  styles/       tokens and global responsive rules
```

Routes:

```text
/                            Create session and upload
/sessions/:sessionId/resume  Resume Review
/sessions/:sessionId/brief   Intent consultation and Match Brief
/runs/:runId                 Run status and recovery
/runs/:runId/results         Product result and evidence
/runs/:runId/evaluation      Examiner trace
```

The URL is the recovery locator. TanStack Query refetches the relevant server resource on page load. A refresh on a Run, Results, or Evaluation route must not depend on in-memory navigation state.

## 5. Meaningful Intent Agent Interaction

### 5.1 Entry question

After resume confirmation, ask:

> Do you already have a target career or target company?

The user chooses `targeted` or `explore`.

### 5.2 Targeted branch

The user may provide target roles, target companies, and free-text context.

The Intent Agent:

- normalizes target titles into role families;
- separates hard constraints from soft preferences;
- treats target companies as soft preferences by default;
- uses company-exclusive matching only when explicitly requested;
- summarizes resume-backed strengths and important gaps;
- asks at most one clarification question when location, visa, or bridge-role tolerance is necessary.

### 5.3 Explore branch

The Intent Agent uses only the confirmed resume structure and evidence to return no more than three directions. Each direction includes:

- role family and display title;
- evidence-grounded rationale;
- resume evidence span IDs;
- primary gap;
- suitable entry role.

The user selects one direction locally. This selection does not trigger another LLM call. If all directions are unsuitable, the user may switch to the targeted branch.

### 5.4 Bounded clarification and execution

The server records whether the single clarification allowance was used. The public response exposes only the safe question and structured interpretation. It never exposes prompts, raw state, provider errors, or full resume text.

When a run snapshot contains a completed Intent consultation, execution skips the existing hidden execute-time Intent Agent call. Legacy clients that create a Match Brief without consultation retain the existing Intent Agent fallback, preserving Day 2 compatibility.

## 6. Public API Increments

### 6.1 Intent consultation

Add:

```text
GET  /api/v1/sessions/{session_id}/intent-consult
POST /api/v1/sessions/{session_id}/intent-consult
```

`GET` restores the latest safe consultation projection after refresh. It returns 404 when no consultation exists. `POST` runs or continues the bounded consultation.

Request fields:

```text
mode: "targeted" | "explore"
goal_text?: string
target_roles: string[]
target_companies: string[]
company_exclusive: boolean
clarification_answer?: string
```

Response fields:

```text
session_id: string
mode: "targeted" | "explore"
assistant_message: string
current_goal: string[]
long_term_goal: string[]
hard_constraints: typed public object
soft_preferences: typed public object
avoid_roles: string[]
directions: CareerDirection[]
needs_clarification: boolean
clarification_question?: string
clarification_used: 0 | 1
```

`CareerDirection` contains role family, title, rationale, resume evidence IDs, primary gap, and entry role. Core request and response models forbid extra fields.

The server validates every direction's resume evidence IDs against the confirmed resume evidence set and drops unsupported IDs.

The consulted state is stored inside the existing session `SharedState` JSON. No database migration is required for these private career-state additions.

Extend the Intent Agent allow-lists with `companies` as a hard constraint and `preferred_companies` as a soft preference. Company-exclusive mode maps to a case-insensitive SQL metadata filter over `jobs.company`; the default targeted-company mode maps only to `preferred_companies`. Company-only matching is never used as anonymous-case evidence matching.

### 6.2 Match Brief snapshot correctness

Before `create_run` captures its state snapshot, the Match Brief route writes the user-approved goal, hard constraints, soft preferences, and avoided roles into session career state. The immutable Match Brief remains the execution authority.

### 6.3 Server-directed polling

Add `retry_after_ms: int | null` to `RunStatusResponse`:

- `queued` and `running`: positive polling interval;
- terminal states: `null`.

TanStack Query uses this value as `refetchInterval`. It does not hard-code a fake progress duration.

### 6.4 Examiner case evidence

Extend the allow-listed Explain DTO with typed case evidence containing case ID, highest stage, and confidence when present. Do not expose anonymous resume payloads, prompts, raw logs, or provider errors.

Refresh `tests/snapshots/openapi_v1.json` in the same change, then regenerate `frontend/src/api/generated.ts` from that snapshot.

## 7. Page and Interaction Design

### 7.1 New Session

- Explain the three-step workbench flow in a compact side panel.
- Provide a standard file input plus drag-and-drop target.
- Accept PDF, DOCX, and TXT.
- Create a session, upload the file, and navigate to Resume Review.
- Generate an opaque per-session visitor ID with `crypto.randomUUID()` for the existing session-create request; do not collect a name or email and do not persist this identifier in browser storage.
- Use clear validation and upload states; do not simulate parsing percentages.

### 7.2 Resume Review

Display Skills, Experience, Education, Projects, Quality Warnings, and Evidence. The page has one primary call to action: **Confirm resume**. Secondary actions may return to upload but must not compete visually.

### 7.3 Intent Consultation and Match Brief

The page begins with the targeted/explore question and the appropriate Intent Agent interaction. After interpretation or direction selection, reveal only:

- career goal;
- locations;
- visa sponsorship requirement;
- role families;
- avoided roles;
- target companies and company-exclusive choice when supplied;
- result count.

Show the canonical brief and a shortened plan-hash fingerprint before execute. Do not expose model names, latent-space controls, RAPTOR, or fusion parameters.

### 7.4 Run

Show the real stages: Intent consultation complete, Retrieval, Strategy, Verification, and Finalization. The Run page polls according to `retry_after_ms`, stops on terminal states, and restores from the server after refresh.

- `completed` and `completed_with_warnings`: navigate or link to Results.
- `failed` and `stale`: show the safe error code and actions to return to the brief or create a new run.
- network interruption: retain the current route and offer retry.
- non-terminal result 409: follow the public recovery payload back to Run status.

### 7.5 Results and Evidence Drawer

Present one recommendation list. Selecting a recommendation updates the detail pane without creating a second competing list.

The detail pane includes title, company, location, tier, concise explanation, skill gaps, and a button opening the Evidence Drawer. The drawer presents:

- JD evidence;
- resume evidence when supplied;
- deterministic must-have hits derived from required-skill evidence fields;
- related skill gaps.

Closing through Escape, backdrop, or close button returns focus to the exact trigger. The interface never shows a hiring probability or guaranteed outcome.

### 7.6 Examiner View

The navigation entry exists only when `/capabilities` returns `explain_enabled: true`. Direct navigation while disabled shows an unavailable state with a Results link.

When enabled, display explicit, implicit, and final rank; anonymous case evidence; effective implicit weight; stage durations; warnings; and bounded recovery events. This view is visually marked as examiner-only and remains separate from the normal recommendation detail.

### 7.7 Reaction

Each recommendation provides a lightweight usefulness reaction. Explain that the reaction is recorded for the current session and does not automatically publish a public anonymous case.

## 8. Accessibility and Responsive Behavior

- All primary flow controls are reachable and operable by keyboard.
- Use native inputs, buttons, headings, lists, and dialog semantics before ARIA additions.
- Every input has a persistent label and error association.
- Visible focus rings meet contrast requirements.
- Text meets WCAG AA contrast; evidence/warning meaning is not color-only.
- Evidence Drawer traps focus while open and restores focus on close.
- At 375 px and 768 px, layouts become single-column without horizontal scrolling.
- At 1440 px, Results uses a bounded list/detail split and readable line lengths.
- Automated viewport checks assert `scrollWidth <= clientWidth` at 375, 768, and 1440 px.

## 9. Error and Privacy Boundaries

The fetch client parses public validation and recovery payloads into a typed `ApiError`. It may display safe `detail`, `error_code`, and recovery actions. It must never render provider payloads, SQL errors, prompt text, full `SharedState`, `user_id`, or normalized full resume text.

The frontend logs no resume content. Development diagnostics may log route names, HTTP status, session ID, and run ID only.

## 10. Testing Strategy

### 10.1 Type and contract gates

- Generate types with `openapi-typescript` from `tests/snapshots/openapi_v1.json`.
- `api:check` regenerates to a temporary location and fails on drift.
- TypeScript strict build passes.
- Core API request and response code contains no explicit `any`.

### 10.2 Component and feature tests

Use Vitest and Testing Library beside each page or feature. Cover:

- upload validation and navigation;
- resume sections and single primary confirmation action;
- targeted and explore Intent branches;
- one clarification maximum;
- Match Brief field visibility and prohibited control absence;
- polling interval and terminal stop behavior;
- refresh restoration from route identifiers;
- failed/stale recovery actions;
- unified result selection;
- Evidence Drawer focus restoration;
- capability-gated examiner route;
- reaction success and safe error handling.

### 10.3 Playwright

Use deterministic route fixtures for CI to cover the full flow and capability on/off behavior. Test 375, 768, and 1440 px widths for horizontal overflow. The deterministic suite must not depend on live providers.

Keep a separate optional live-backend smoke workflow for demonstrations. Provider or network instability must not make the standard frontend test suite flaky.

## 11. Acceptance Criteria

Day 3 is complete when:

1. The frontend consumes only `/api/v1` and generated public types.
2. A keyboard user can complete upload through Results.
3. The Intent Agent visibly handles both targeted and explore branches.
4. A consulted run does not repeat the Intent Agent call during execute.
5. Refresh restores Resume Review, Run, Results, and Examiner pages from the server.
6. Polling obeys `retry_after_ms` and stops at terminal state.
7. Results provide traceable evidence and never present hiring probability.
8. Examiner content is capability-gated and contains no private state.
9. Drawer focus restoration and 375/768/1440 overflow tests pass.
10. Backend regression tests, frontend unit tests, type checks, build, and Playwright all pass.

## 12. Explicit Non-Goals

- Marketing pages, authentication UI, billing, account settings, and admin consoles.
- User-selectable model/provider configuration.
- RAPTOR, cross-encoder, alpha/beta, or latent-space controls in the normal UI.
- Public deployment, production worker leasing, or queue infrastructure.
- Automatic publication of reactions into the anonymous case base.
