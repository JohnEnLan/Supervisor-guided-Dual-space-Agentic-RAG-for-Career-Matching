# Career RAG Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a three-screen, accessible introduction at `/` on every visit, with an always-visible skip action and the existing upload workbench moved to `/workspace`.

**Architecture:** `OnboardingPage` is a standalone route that owns only an in-memory step index and never mounts the query-enabled workbench layout. Existing session, run, evaluation, and monitoring routes remain under `App`; only the upload entry route moves to `/workspace`.

**Tech Stack:** React 19, TypeScript, React Router, Lucide React, CSS, Vitest, Testing Library, Playwright

## Global Constraints

- Do not add a third-party animation library, Canvas, video, or gradients.
- Every visit and refresh of `/` starts at introduction screen one; do not use localStorage or sessionStorage.
- Every screen exposes a visible `跳过介绍` link to `/workspace`.
- The introduction route must not call `/api/v1/capabilities` or any other business API.
- Preserve `/sessions/*`, `/runs/*`, and `/monitoring` URLs.
- Respect `prefers-reduced-motion: reduce`, 44px controls, keyboard operation, and 375/768/1440px layouts.

---

### Task 1: Standalone Onboarding Component

**Files:**
- Create: `frontend/src/features/onboarding/OnboardingPage.tsx`
- Test: `frontend/src/features/onboarding/OnboardingPage.test.tsx`

**Interfaces:**
- Consumes: React state and `Link` from React Router.
- Produces: `OnboardingPage(): JSX.Element`; all exit actions navigate to `/workspace`.

- [ ] **Step 1: Write failing component tests**

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { OnboardingPage } from "./OnboardingPage";

function renderOnboarding() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route path="/" element={<OnboardingPage />} />
        <Route path="/workspace" element={<h1>简历匹配工作台</h1>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("OnboardingPage", () => {
  it("moves through all three screens and enters the workspace", async () => {
    const user = userEvent.setup();
    renderOnboarding();
    expect(screen.getByRole("heading", { name: /有证据的职业决策/ })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "了解它如何工作" }));
    expect(screen.getByRole("heading", { name: /Agent 协作/ })).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "继续了解" }));
    expect(screen.getByRole("heading", { name: /可信与可解释/ })).toHaveFocus();
    await user.click(screen.getByRole("link", { name: "进入职业匹配工作台" }));
    expect(screen.getByRole("heading", { name: "简历匹配工作台" })).toBeVisible();
  });

  it("can go back and can skip from every screen", async () => {
    const user = userEvent.setup();
    renderOnboarding();
    expect(screen.getByRole("link", { name: "跳过介绍" })).toHaveAttribute("href", "/workspace");
    await user.click(screen.getByRole("button", { name: "了解它如何工作" }));
    await user.click(screen.getByRole("button", { name: "上一页" }));
    expect(screen.getByRole("heading", { name: /有证据的职业决策/ })).toBeVisible();
    await user.click(screen.getByRole("link", { name: "跳过介绍" }));
    expect(screen.getByRole("heading", { name: "简历匹配工作台" })).toBeVisible();
  });
});
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `cd frontend; npm.cmd test -- src/features/onboarding/OnboardingPage.test.tsx`

Expected: FAIL because `OnboardingPage.tsx` does not exist.

- [ ] **Step 3: Implement the component**

Implement a `SCREENS` constant with exactly three entries and render one entry at a time. Use a heading ref for focus after `step` changes.

```tsx
import { ArrowLeft, ArrowRight, BriefcaseBusiness, Database, FileCheck2, Search, ShieldCheck, Sparkles, Target, Users } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

const SCREENS = [
  {
    eyebrow: "Career RAG",
    title: "让职业匹配成为有证据的职业决策",
    description: "从真实简历经历出发，对照岗位原文，并给出可核查的推荐、能力缺口和职业路径。",
    kind: "evidence",
  },
  {
    eyebrow: "Agentic Workflow",
    title: "三位 Agent 协作，Supervisor 守住边界",
    description: "先理解目标，再完成混合检索与策略生成；Supervisor 只允许有界澄清、重检索和修复。",
    kind: "agents",
  },
  {
    eyebrow: "Trust by Design",
    title: "每一条推荐都可信、可解释",
    description: "显式岗位证据与匿名案例证据分开呈现，不输出完整简历、内部提示词或供应商错误。",
    kind: "trust",
  },
] as const;

export function OnboardingPage() {
  const [step, setStep] = useState(0);
  const titleRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    titleRef.current?.focus();
  }, [step]);

  const screen = SCREENS[step];
  return (
    <main className="onboarding-shell">
      <header className="onboarding-header">
        <span className="onboarding-brand"><BriefcaseBusiness aria-hidden="true" /> Career RAG</span>
        <Link className="button onboarding-skip" to="/workspace">跳过介绍</Link>
      </header>
      <section className="onboarding-stage" data-step={step + 1}>
        <div className="onboarding-copy">
          <p className="eyebrow">{screen.eyebrow}</p>
          <h1 ref={titleRef} tabIndex={-1}>{screen.title}</h1>
          <p className="onboarding-lead">{screen.description}</p>
          <div className="onboarding-actions">
            {step > 0 ? <button className="secondary" onClick={() => setStep((value) => value - 1)}><ArrowLeft />上一页</button> : null}
            {step < 2 ? (
              <button className="primary" onClick={() => setStep((value) => value + 1)}>{step === 0 ? "了解它如何工作" : "继续了解"}<ArrowRight /></button>
            ) : (
              <Link className="button primary" to="/workspace">进入职业匹配工作台<ArrowRight /></Link>
            )}
          </div>
        </div>
        <OnboardingVisual kind={screen.kind} />
      </section>
      <footer className="onboarding-footer">
        <ol aria-label="介绍进度">{SCREENS.map((item, index) => <li key={item.kind} aria-current={index === step ? "step" : undefined}><span>{index + 1}</span>{item.eyebrow}</li>)}</ol>
        <p className="sr-only" aria-live="polite">第 {step + 1} 页，共 3 页</p>
      </footer>
    </main>
  );
}

function OnboardingVisual({ kind }: { kind: (typeof SCREENS)[number]["kind"] }) {
  if (kind === "evidence") return <div className="intro-visual evidence-flow" aria-label="简历证据连接岗位证据和推荐结果"><FileCheck2 /><span /><Search /><span /><Sparkles /></div>;
  if (kind === "agents") return <div className="intro-visual agent-flow" aria-label="三位 Agent 由 Supervisor 监督"><Target /><Users /><Search /><Database /><ShieldCheck className="supervisor-node" /></div>;
  return <div className="intro-visual trust-flow" aria-label="证据、隐私和可解释性保障"><FileCheck2 /><ShieldCheck /><Database /></div>;
}
```

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run: `cd frontend; npm.cmd test -- src/features/onboarding/OnboardingPage.test.tsx`

Expected: 2 tests pass.

- [ ] **Step 5: Commit the component**

```powershell
git add frontend/src/features/onboarding/OnboardingPage.tsx frontend/src/features/onboarding/OnboardingPage.test.tsx
git commit -m "feat: add accessible onboarding screens"
```

### Task 2: Route Isolation and Workspace Entry

**Files:**
- Modify: `frontend/src/app/router.tsx`
- Modify: `frontend/src/app/App.tsx`
- Modify: `frontend/e2e/full-flow.spec.ts`
- Create: `frontend/e2e/onboarding.spec.ts`

**Interfaces:**
- Consumes: `OnboardingPage` from Task 1.
- Produces: `/` introduction route and `/workspace` upload route without changing other public browser URLs.

- [ ] **Step 1: Write a failing route E2E test**

```ts
import { expect, test } from "@playwright/test";

test("keeps onboarding isolated from business APIs and skips to the workspace", async ({ page }) => {
  let apiCalls = 0;
  await page.route("**/api/v1/**", async (route) => {
    apiCalls += 1;
    await route.fulfill({ status: 500, contentType: "application/json", body: "{}" });
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /有证据的职业决策/ })).toBeVisible();
  expect(apiCalls).toBe(0);
  await page.getByRole("link", { name: "跳过介绍" }).click();
  await expect(page).toHaveURL(/\/workspace$/);
  await expect(page.getByRole("heading", { name: "先从一份真实简历开始" })).toBeVisible();
});
```

- [ ] **Step 2: Run the E2E test and verify RED**

Run: `cd frontend; npm.cmd run e2e -- e2e/onboarding.spec.ts`

Expected: FAIL because `/` still renders `NewSessionPage` and `/workspace` does not exist.

- [ ] **Step 3: Split the routes**

Change `router.tsx` to this route shape:

```tsx
export const router = createBrowserRouter([
  { path: "/", element: <OnboardingPage />, errorElement: <RouteError /> },
  {
    element: <App />,
    errorElement: <RouteError />,
    children: [
      { path: "workspace", element: <NewSessionPage /> },
      { path: "sessions/:sessionId/resume", element: <ResumeReviewPage /> },
      { path: "sessions/:sessionId/brief", element: <MatchBriefPage /> },
      { path: "runs/:runId", element: <RunPage /> },
      { path: "runs/:runId/results", element: <ResultsPage /> },
      { path: "runs/:runId/evaluation", element: <EvaluationRunPage /> },
      { path: "runs/:runId/explain", element: <Navigate replace to="../evaluation" /> },
      { path: "monitoring", element: <MonitoringPage /> },
    ],
  },
]);
```

In `App.tsx`, keep the brand link at `/` and change the “开始匹配” navigation link to `/workspace`. Update the main E2E happy path from `page.goto("/")` to `page.goto("/workspace")`.

- [ ] **Step 4: Run route tests and verify GREEN**

Run: `cd frontend; npm.cmd run e2e -- e2e/onboarding.spec.ts e2e/full-flow.spec.ts`

Expected: onboarding and the existing full business flow pass.

- [ ] **Step 5: Commit route isolation**

```powershell
git add frontend/src/app/router.tsx frontend/src/app/App.tsx frontend/e2e/full-flow.spec.ts frontend/e2e/onboarding.spec.ts
git commit -m "feat: route onboarding before the workbench"
```

### Task 3: Motion, Responsive Layout, and Reduced Motion

**Files:**
- Modify: `frontend/src/styles/global.css`
- Modify: `frontend/e2e/onboarding.spec.ts`

**Interfaces:**
- Consumes: `.onboarding-*` and `.intro-visual` classes from Task 1.
- Produces: lightweight CSS-only entry motion and responsive layouts.

- [ ] **Step 1: Add failing visual contract tests**

Add Playwright cases that loop over 375, 768, and 1440 widths and assert `scrollWidth <= clientWidth`. Add a reduced-motion context with `page.emulateMedia({ reducedMotion: "reduce" })` and assert the computed `animationDuration` of `.intro-visual` is `0s`.

- [ ] **Step 2: Run the tests and verify RED**

Run: `cd frontend; npm.cmd run e2e -- e2e/onboarding.spec.ts`

Expected: FAIL because the onboarding motion and reduced-motion rules do not exist.

- [ ] **Step 3: Add focused CSS**

Add an isolated full-height layout, a two-column desktop stage, a stacked mobile stage, and these motion contracts:

```css
.onboarding-shell { min-height: 100vh; display: grid; grid-template-rows: auto 1fr auto; background: var(--canvas); overflow: hidden; }
.onboarding-header, .onboarding-footer { padding: 20px clamp(20px, 5vw, 72px); display: flex; align-items: center; justify-content: space-between; }
.onboarding-stage { width: min(1240px, 100%); margin: auto; padding: 36px clamp(20px, 5vw, 72px); display: grid; grid-template-columns: minmax(0, 1fr) minmax(340px, .9fr); align-items: center; gap: clamp(36px, 7vw, 96px); animation: intro-copy-in 420ms ease-out both; }
.onboarding-brand { display: inline-flex; align-items: center; gap: 10px; color: var(--navy); font-weight: 800; }
.onboarding-skip { color: var(--navy); background: white; border-color: var(--line); font-weight: 750; }
.onboarding-lead { max-width: 680px; color: var(--muted); font-size: clamp(1rem, 2vw, 1.2rem); }
.onboarding-actions { display: flex; flex-wrap: wrap; gap: 12px; }
.onboarding-actions button { padding: 0 18px; display: inline-flex; align-items: center; gap: 8px; }
.intro-visual { min-height: 380px; display: grid; place-items: center; color: var(--navy); background: var(--surface); border: 1px solid var(--line); border-radius: 28px; box-shadow: var(--shadow); animation: intro-visual-in 560ms 80ms ease-out both; }
.onboarding-footer ol { margin: 0; padding: 0; display: flex; gap: 18px; list-style: none; }
.onboarding-footer li { display: flex; align-items: center; gap: 7px; color: var(--muted); }
.onboarding-footer li[aria-current="step"] { color: var(--navy); font-weight: 800; }
@keyframes intro-copy-in { from { opacity: 0; transform: translateY(18px); } to { opacity: 1; transform: translateY(0); } }
@keyframes intro-visual-in { from { opacity: 0; transform: translateX(28px) scale(.98); } to { opacity: 1; transform: translateX(0) scale(1); } }
@media (max-width: 760px) { .onboarding-stage { grid-template-columns: 1fr; padding-top: 14px; } .intro-visual { min-height: 250px; } .onboarding-footer li { font-size: .75rem; } }
@media (prefers-reduced-motion: reduce) { .onboarding-stage, .intro-visual, .intro-visual * { animation-duration: 0s !important; animation-delay: 0s !important; transition-duration: 0s !important; } }
```

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `cd frontend; npm.cmd test -- src/features/onboarding/OnboardingPage.test.tsx`

Run: `cd frontend; npm.cmd run e2e -- e2e/onboarding.spec.ts`

Expected: all focused unit and browser tests pass.

- [ ] **Step 5: Commit motion and responsive behavior**

```powershell
git add frontend/src/styles/global.css frontend/e2e/onboarding.spec.ts
git commit -m "feat: animate the onboarding journey"
```

### Task 4: Frontend Regression Gate

**Files:**
- Modify only if a regression is reproduced by a failing test.

**Interfaces:**
- Consumes: all onboarding tasks.
- Produces: a verified production frontend build.

- [ ] **Step 1: Run API contract, unit, type, and build checks**

```powershell
cd frontend
npm.cmd run api:check
npm.cmd test
npm.cmd run typecheck
npm.cmd run build
```

Expected: every command exits 0.

- [ ] **Step 2: Run the complete browser suite**

Run: `cd frontend; npm.cmd run e2e`

Expected: onboarding, full-flow, and monitoring projects pass in Chromium.

- [ ] **Step 3: Inspect the real browser**

Open `http://127.0.0.1:5173/`, verify all three screens, skip, final entry, focus movement, and console errors. Leave the browser on `/` for user review.

- [ ] **Step 4: Commit only test-proven regression fixes**

```powershell
git add frontend
git commit -m "test: lock onboarding regressions"
```
