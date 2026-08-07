# Cinematic Career Expedition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the three-screen onboarding carousel with a seven-scene, scroll-driven, silent cinematic career expedition featuring a semantic career constellation and a bounded mouse-following particle comet.

**Architecture:** The `/` route remains isolated from the query-enabled workbench and renders static chapter content, a sticky SVG constellation, semantic scene sections, chapter navigation, and a pointer-only presentation layer. `IntersectionObserver` changes React state only when the active scene changes; scroll and pointer frames update CSS styles directly without per-frame React rendering.

**Tech Stack:** React 19, TypeScript 5.9, React Router 7, CSS, semantic SVG, IntersectionObserver, requestAnimationFrame, Vitest, Testing Library, Playwright

## Global Constraints

- Keep `/workspace`, `/sessions/*`, `/runs/*`, `/monitoring`, API DTOs, Agent prompts, retrieval, and backend code unchanged.
- Render exactly seven named mission scenes and keep an always-visible `跳过远征` link plus a final `进入职业匹配工作台` link to `/workspace`.
- Do not load or call `/api/v1/**`, localStorage, sessionStorage, audio, video, bitmap backgrounds, Canvas, WebGL, or a third-party animation library on `/`.
- Use only transform, opacity, and SVG stroke properties for continuously updated motion; do not animate width or height.
- React state may change when the active chapter changes, but not for every scroll or pointer frame.
- Reuse at most 18 pointer-comet elements; do not create DOM nodes inside `pointermove`.
- Disable the pointer comet for coarse pointers and `prefers-reduced-motion: reduce`; cancel frames and listeners on unmount.
- Preserve 44 × 44 px controls, visible keyboard focus, sequential headings, and no horizontal overflow at 375, 768, and 1440 px.
- Add no runtime dependency. Keep the final JavaScript gzip size at or below the existing 118.79 kB baseline plus 15 kB, i.e. **133.79 kB**.
- Preserve unrelated untracked `.planning/`, `outputs/`, and existing 2026-07-10 documents.

---

### Task 1: Static Expedition Story and Semantic Scene

**Files:**
- Create: `frontend/src/features/onboarding/onboardingContent.ts`
- Create: `frontend/src/features/onboarding/MissionScene.tsx`
- Test: `frontend/src/features/onboarding/MissionScene.test.tsx`

**Interfaces:**
- Produces: `MissionChapter`, `ChapterKind`, `EXPEDITION_CHAPTERS` with exactly seven entries.
- Produces: `MissionScene` as `forwardRef<HTMLElement, MissionSceneProps>`.
- Consumes: optional `children` for the final workspace CTA.

- [ ] **Step 1: Write the failing story and scene tests**

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EXPEDITION_CHAPTERS } from "./onboardingContent";
import { MissionScene } from "./MissionScene";

describe("cinematic expedition content", () => {
  it("defines seven ordered chapters covering the complete evidence mission", () => {
    expect(EXPEDITION_CHAPTERS).toHaveLength(7);
    expect(EXPEDITION_CHAPTERS.map((chapter) => chapter.id)).toEqual([
      "prologue",
      "fog",
      "coordinates",
      "direction",
      "fleet",
      "navigation",
      "departure",
    ]);
    const corpus = EXPEDITION_CHAPTERS.map((chapter) =>
      `${chapter.title} ${chapter.body}`,
    ).join(" ");
    expect(corpus).toMatch(/目标岗位.*探索未知/);
    expect(corpus).toMatch(/Intent.*Matching.*Strategy.*Supervisor/);
    expect(corpus).toMatch(/显式岗位空间.*匿名案例空间/);
    expect(corpus).toMatch(/完整简历.*内部提示词.*API Key/);
  });

  it("renders one accessible mission scene with its coordinate", () => {
    render(<MissionScene chapter={EXPEDITION_CHAPTERS[2]} index={2} />);
    expect(
      screen.getByRole("heading", { name: "从已经发生的经历出发" }),
    ).toBeVisible();
    expect(screen.getByText("SKILL · PROJECT · EDUCATION · EXPERIENCE")).toBeVisible();
    expect(screen.getByRole("region")).toHaveAttribute("id", "scene-coordinates");
  });
});
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `cd frontend; npm.cmd test -- src/features/onboarding/MissionScene.test.tsx`

Expected: FAIL because `onboardingContent.ts` and `MissionScene.tsx` do not exist.

- [ ] **Step 3: Implement the exact chapter contract**

```ts
export type ChapterKind =
  | "prologue"
  | "fog"
  | "coordinates"
  | "direction"
  | "fleet"
  | "navigation"
  | "departure";

export type MissionChapter = {
  id: ChapterKind;
  number: string;
  eyebrow: string;
  title: string;
  body: string;
  coordinate: string;
};

export const EXPEDITION_CHAPTERS: readonly MissionChapter[] = [
  {
    id: "prologue",
    number: "01",
    eyebrow: "THE CAREER EXPEDITION",
    title: "职业不是一次匹配，而是一条航线",
    body: "我们不替你决定未来。我们从真实经历出发，让每一次选择都有坐标、有边界、有证据。",
    coordinate: "ORIGIN · YOUR EVIDENCE",
  },
  {
    id: "fog",
    number: "02",
    eyebrow: "BEYOND SIMILARITY",
    title: "相似，不等于适合",
    body: "关键词相近只能找到可能的道路；地点、签证、经验、岗位状态和真实证据，才决定道路是否能够抵达。",
    coordinate: "FILTER · VERIFY · THEN RANK",
  },
  {
    id: "coordinates",
    number: "03",
    eyebrow: "RESUME CONSTELLATION",
    title: "从已经发生的经历出发",
    body: "技能、项目、教育与经历被保留为可追溯的原文证据。没有真实坐标，就不生成虚构的路线。",
    coordinate: "SKILL · PROJECT · EDUCATION · EXPERIENCE",
  },
  {
    id: "direction",
    number: "04",
    eyebrow: "INTENT CALIBRATION",
    title: "有目标，就校准；没有目标，就探索",
    body: "已有目标岗位或目标公司时，Intent Agent 锁定方向；仍在探索时，它先给出不超过三个可理解的职业方向。",
    coordinate: "目标岗位 · 目标公司 · 探索未知",
  },
  {
    id: "fleet",
    number: "05",
    eyebrow: "SUPERVISOR-GUIDED FLEET",
    title: "三位 Agent，各守一段航程",
    body: "Intent 理解方向，Matching 检索证据，Strategy 规划行动；Supervisor 核查约束，并把恢复限制在有界循环内。",
    coordinate: "Intent · Matching · Strategy · Supervisor",
  },
  {
    id: "navigation",
    number: "06",
    eyebrow: "DUAL-SPACE NAVIGATION",
    title: "两种信号，共同校准一条路线",
    body: "显式岗位空间提供 JD evidence，匿名案例空间只重排已有候选；任何信号都不能穿过硬约束安全门。",
    coordinate: "显式岗位空间 · 匿名案例空间 · HARD GATE",
  },
  {
    id: "departure",
    number: "07",
    eyebrow: "EVIDENCE OATH",
    title: "未来不由模型决定，但每一步都应有证据",
    body: "公开结果不返回完整简历、内部提示词、供应商错误或 API Key。方向属于你，证据负责照亮道路。",
    coordinate: "READY FOR DEPARTURE",
  },
];
```

- [ ] **Step 4: Implement the semantic scene component**

```tsx
import { forwardRef, type ReactNode } from "react";

import type { MissionChapter } from "./onboardingContent";

type MissionSceneProps = {
  chapter: MissionChapter;
  index: number;
  children?: ReactNode;
};

export const MissionScene = forwardRef<HTMLElement, MissionSceneProps>(
  function MissionScene({ chapter, index, children }, ref) {
    return (
      <section
        ref={ref}
        id={`scene-${chapter.id}`}
        className="mission-scene"
        data-scene={chapter.id}
        data-scene-index={index}
        aria-labelledby={`scene-title-${chapter.id}`}
        role="region"
      >
        <p className="mission-number" aria-hidden="true">{chapter.number}</p>
        <p className="mission-eyebrow">{chapter.eyebrow}</p>
        <h2 id={`scene-title-${chapter.id}`}>{chapter.title}</h2>
        <p className="mission-body">{chapter.body}</p>
        <p className="mission-coordinate">{chapter.coordinate}</p>
        {children}
      </section>
    );
  },
);
```

- [ ] **Step 5: Run focused tests and verify GREEN**

Run: `cd frontend; npm.cmd test -- src/features/onboarding/MissionScene.test.tsx`

Expected: 2 tests pass.

- [ ] **Step 6: Commit the story contract**

```powershell
git add frontend/src/features/onboarding/onboardingContent.ts frontend/src/features/onboarding/MissionScene.tsx frontend/src/features/onboarding/MissionScene.test.tsx
git commit -m "feat: define cinematic expedition story"
```

### Task 2: Semantic Career Constellation

**Files:**
- Create: `frontend/src/features/onboarding/CareerConstellation.tsx`
- Test: `frontend/src/features/onboarding/CareerConstellation.test.tsx`

**Interfaces:**
- Consumes: `activeChapter: number` in the inclusive range 0–6.
- Produces: a semantic `<figure data-chapter="1..7">` with bounded SVG nodes and paths.

- [ ] **Step 1: Write the failing constellation test**

```tsx
import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import { CareerConstellation } from "./CareerConstellation";

it("activates only constellation signals reached by the current chapter", () => {
  const { rerender } = render(<CareerConstellation activeChapter={2} />);
  const figure = screen.getByRole("figure", { name: /职业证据星图/ });
  expect(figure).toHaveAttribute("data-chapter", "3");
  expect(figure.querySelectorAll("[data-activation].is-active")).toHaveLength(3);
  expect(screen.getByText("RESUME EVIDENCE")).toBeVisible();

  rerender(<CareerConstellation activeChapter={6} />);
  expect(figure.querySelectorAll("[data-activation].is-active")).toHaveLength(7);
  expect(screen.getByText("EVIDENCE OATH")).toBeVisible();
});
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `cd frontend; npm.cmd test -- src/features/onboarding/CareerConstellation.test.tsx`

Expected: FAIL because `CareerConstellation` does not exist.

- [ ] **Step 3: Implement the bounded constellation**

```tsx
type CareerConstellationProps = { activeChapter: number };

const SIGNALS = [
  { x: 92, y: 356, label: "ORIGIN" },
  { x: 188, y: 272, label: "FILTER" },
  { x: 278, y: 392, label: "RESUME EVIDENCE" },
  { x: 374, y: 238, label: "INTENT" },
  { x: 472, y: 354, label: "AGENT FLEET" },
  { x: 574, y: 246, label: "DUAL SPACE" },
  { x: 674, y: 356, label: "EVIDENCE OATH" },
] as const;

const ROUTE = "M92 356 C138 350 150 282 188 272 S246 378 278 392 S340 250 374 238 S438 326 472 354 S536 270 574 246 S632 326 674 356";

export function CareerConstellation({ activeChapter }: CareerConstellationProps) {
  return (
    <figure
      className="career-constellation"
      data-chapter={activeChapter + 1}
      aria-label="职业证据星图，随远征章节逐步完成"
      role="figure"
    >
      <svg viewBox="0 0 760 620" role="img" aria-labelledby="constellation-title constellation-desc">
        <title id="constellation-title">职业证据星图</title>
        <desc id="constellation-desc">从简历证据出发，经过目标校准、Agent 协作和双空间安全门抵达可解释结果。</desc>
        <path className="constellation-route route-ghost" d={ROUTE} pathLength="1" />
        <path className="constellation-route route-active" d={ROUTE} pathLength="1" />
        {SIGNALS.map((signal, index) => (
          <g
            key={signal.label}
            className={`constellation-signal${index <= activeChapter ? " is-active" : ""}`}
            data-activation={index + 1}
            transform={`translate(${signal.x} ${signal.y})`}
          >
            <circle r={index === activeChapter ? 11 : 7} />
            <circle className="signal-halo" r="22" />
            <text y={index % 2 === 0 ? 42 : -30} textAnchor="middle">{signal.label}</text>
          </g>
        ))}
        <g className={`supervisor-gate${activeChapter >= 5 ? " is-active" : ""}`} transform="translate(618 356)">
          <rect x="-32" y="-54" width="64" height="108" rx="32" />
          <text y="76" textAnchor="middle">SUPERVISOR GATE</text>
        </g>
      </svg>
      <figcaption>CAREER COORDINATES / EVIDENCE-GROUNDED</figcaption>
    </figure>
  );
}
```

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `cd frontend; npm.cmd test -- src/features/onboarding/CareerConstellation.test.tsx`

Expected: 1 test passes and the SVG contains 7 bounded activation groups.

- [ ] **Step 5: Commit the constellation**

```powershell
git add frontend/src/features/onboarding/CareerConstellation.tsx frontend/src/features/onboarding/CareerConstellation.test.tsx
git commit -m "feat: draw the career constellation"
```

### Task 3: Bounded Pointer Comet

**Files:**
- Create: `frontend/src/features/onboarding/PointerComet.tsx`
- Test: `frontend/src/features/onboarding/PointerComet.test.tsx`

**Interfaces:**
- Produces: `PointerComet(): JSX.Element` with exactly `POINTER_PARTICLE_COUNT = 18` reused spans.
- Consumes: browser `matchMedia`, `pointermove`, `blur`, `visibilitychange`, and requestAnimationFrame.
- Never calls React state after mount.

- [ ] **Step 1: Write failing fixed-pool and coarse-pointer tests**

```tsx
import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { PointerComet, POINTER_PARTICLE_COUNT } from "./PointerComet";

afterEach(() => vi.restoreAllMocks());

it("renders one fixed inert pool without replacing the system cursor", () => {
  vi.stubGlobal("matchMedia", vi.fn((query: string) => ({
    matches: query === "(pointer: fine)",
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })));
  const { container } = render(<PointerComet />);
  expect(screen.getByTestId("pointer-comet")).toHaveAttribute("aria-hidden", "true");
  expect(container.querySelectorAll(".pointer-comet-particle")).toHaveLength(
    POINTER_PARTICLE_COUNT,
  );
  expect(screen.getByTestId("pointer-comet")).toHaveStyle({ pointerEvents: "none" });
});

it("does not attach pointer tracking for coarse pointers", () => {
  vi.stubGlobal("matchMedia", vi.fn((query: string) => ({
    matches: query === "(pointer: coarse)",
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })));
  const add = vi.spyOn(window, "addEventListener");
  render(<PointerComet />);
  expect(add).not.toHaveBeenCalledWith("pointermove", expect.any(Function), expect.anything());
});

it("removes pointer tracking when the onboarding route unmounts", () => {
  vi.stubGlobal("matchMedia", vi.fn((query: string) => ({
    matches: query === "(pointer: fine)", media: query, onchange: null,
    addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(),
    removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
  })));
  const remove = vi.spyOn(window, "removeEventListener");
  const { unmount } = render(<PointerComet />);
  unmount();
  expect(remove).toHaveBeenCalledWith("pointermove", expect.any(Function));
});
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `cd frontend; npm.cmd test -- src/features/onboarding/PointerComet.test.tsx`

Expected: FAIL because `PointerComet` does not exist.

- [ ] **Step 3: Implement the fixed ring-buffer trail**

```tsx
import { useEffect, useRef } from "react";

export const POINTER_PARTICLE_COUNT = 18;
const TRAIL_IDLE_MS = 420;

type Point = { x: number; y: number };

export function PointerComet() {
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const finePointer = window.matchMedia("(pointer: fine)").matches;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!finePointer || reducedMotion || !rootRef.current) return;

    const particles = Array.from(
      rootRef.current.querySelectorAll<HTMLElement>(".pointer-comet-particle"),
    );
    const points: Point[] = Array.from({ length: POINTER_PARTICLE_COUNT }, () => ({ x: -40, y: -40 }));
    let target: Point = { x: -40, y: -40 };
    let lastMoveAt = 0;
    let frame: number | null = null;

    const hide = () => {
      particles.forEach((particle) => { particle.style.opacity = "0"; });
    };
    const stop = () => {
      if (frame !== null) cancelAnimationFrame(frame);
      frame = null;
      hide();
    };
    const tick = (now: number) => {
      points[0].x += (target.x - points[0].x) * 0.42;
      points[0].y += (target.y - points[0].y) * 0.42;
      for (let index = 1; index < points.length; index += 1) {
        points[index].x += (points[index - 1].x - points[index].x) * 0.34;
        points[index].y += (points[index - 1].y - points[index].y) * 0.34;
      }
      particles.forEach((particle, index) => {
        const scale = 1 - index / (POINTER_PARTICLE_COUNT * 1.25);
        particle.style.transform = `translate3d(${points[index].x}px, ${points[index].y}px, 0) scale(${scale})`;
        particle.style.opacity = String(Math.max(0, 0.72 - index * 0.035));
      });
      if (now - lastMoveAt >= TRAIL_IDLE_MS || document.hidden) {
        stop();
        return;
      }
      frame = requestAnimationFrame(tick);
    };
    const onPointerMove = (event: PointerEvent) => {
      target = { x: event.clientX, y: event.clientY };
      lastMoveAt = performance.now();
      if (frame === null) frame = requestAnimationFrame(tick);
    };

    window.addEventListener("pointermove", onPointerMove, { passive: true });
    window.addEventListener("blur", stop);
    document.addEventListener("visibilitychange", stop);
    return () => {
      stop();
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("blur", stop);
      document.removeEventListener("visibilitychange", stop);
    };
  }, []);

  return (
    <div
      ref={rootRef}
      className="pointer-comet"
      data-testid="pointer-comet"
      aria-hidden="true"
      style={{ pointerEvents: "none" }}
    >
      {Array.from({ length: POINTER_PARTICLE_COUNT }, (_, index) => (
        <span key={index} className="pointer-comet-particle" data-particle={index} />
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `cd frontend; npm.cmd test -- src/features/onboarding/PointerComet.test.tsx`

Expected: 3 tests pass without creating dynamic nodes and cleanup is observed.

- [ ] **Step 5: Commit the comet layer**

```powershell
git add frontend/src/features/onboarding/PointerComet.tsx frontend/src/features/onboarding/PointerComet.test.tsx
git commit -m "feat: add bounded pointer comet"
```

### Task 4: Scroll Orchestration, Chapter Navigation, and Route Cutover

**Files:**
- Create: `frontend/src/features/onboarding/ChapterNavigation.tsx`
- Create: `frontend/src/features/onboarding/CinematicOnboardingPage.tsx`
- Create: `frontend/src/features/onboarding/CinematicOnboardingPage.test.tsx`
- Modify: `frontend/src/app/router.tsx`
- Delete: `frontend/src/features/onboarding/OnboardingPage.tsx`
- Delete: `frontend/src/features/onboarding/OnboardingPage.test.tsx`

**Interfaces:**
- `ChapterNavigation({ activeChapter, chapters })` renders seven anchors and one `aria-current="step"`.
- `CinematicOnboardingPage` owns only `activeChapter`, scene refs, IntersectionObserver, and one scroll CSS variable.
- `PointerComet` and `CareerConstellation` remain presentation-only.

- [ ] **Step 1: Write the failing integration test**

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { expect, it, vi } from "vitest";

import { CinematicOnboardingPage } from "./CinematicOnboardingPage";

class ObserverStub {
  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();
  constructor(_callback: IntersectionObserverCallback) {}
}

it("renders seven scenes, chapter navigation, skip, and final departure", () => {
  vi.stubGlobal("IntersectionObserver", ObserverStub);
  vi.stubGlobal("matchMedia", vi.fn(() => ({
    matches: false,
    media: "",
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })));
  render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route path="/" element={<CinematicOnboardingPage />} />
        <Route path="/workspace" element={<h1>简历匹配工作台</h1>} />
      </Routes>
    </MemoryRouter>,
  );
  expect(screen.getByRole("heading", { level: 1, name: "职业远征" })).toBeVisible();
  expect(screen.getAllByRole("region")).toHaveLength(7);
  expect(screen.getByRole("navigation", { name: "远征章节" })).toBeVisible();
  expect(screen.getByRole("link", { name: "跳过远征" })).toHaveAttribute("href", "/workspace");
  expect(screen.getByRole("link", { name: "进入职业匹配工作台" })).toHaveAttribute("href", "/workspace");
  expect(screen.getByText(/未来不由模型决定/)).toBeVisible();
});
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `cd frontend; npm.cmd test -- src/features/onboarding/CinematicOnboardingPage.test.tsx`

Expected: FAIL because the page and navigation do not exist.

- [ ] **Step 3: Implement chapter navigation**

```tsx
import type { MissionChapter } from "./onboardingContent";

type ChapterNavigationProps = {
  activeChapter: number;
  chapters: readonly MissionChapter[];
};

export function ChapterNavigation({ activeChapter, chapters }: ChapterNavigationProps) {
  return (
    <nav className="chapter-navigation" aria-label="远征章节">
      <ol>
        {chapters.map((chapter, index) => (
          <li key={chapter.id}>
            <a
              href={`#scene-${chapter.id}`}
              aria-current={index === activeChapter ? "step" : undefined}
            >
              <span>{chapter.number}</span>
              <strong>{chapter.title}</strong>
            </a>
          </li>
        ))}
      </ol>
    </nav>
  );
}
```

- [ ] **Step 4: Implement the page with bounded observers and frames**

```tsx
import { ArrowRight, BriefcaseBusiness } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { CareerConstellation } from "./CareerConstellation";
import { ChapterNavigation } from "./ChapterNavigation";
import { MissionScene } from "./MissionScene";
import { EXPEDITION_CHAPTERS } from "./onboardingContent";
import { PointerComet } from "./PointerComet";

export function CinematicOnboardingPage() {
  const [activeChapter, setActiveChapter] = useState(0);
  const sceneRefs = useRef<Array<HTMLElement | null>>([]);

  useEffect(() => {
    if (!("IntersectionObserver" in window)) return;
    const observer = new IntersectionObserver(
      (entries) => {
        const current = entries
          .filter((entry) => entry.isIntersecting)
          .sort((left, right) => right.intersectionRatio - left.intersectionRatio)[0];
        const index = current ? Number((current.target as HTMLElement).dataset.sceneIndex) : NaN;
        if (Number.isInteger(index)) setActiveChapter(index);
      },
      { rootMargin: "-28% 0px -42%", threshold: [0.2, 0.45, 0.7] },
    );
    sceneRefs.current.forEach((scene) => { if (scene) observer.observe(scene); });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    let frame: number | null = null;
    const update = () => {
      const maximum = Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
      const progress = Math.min(1, Math.max(0, window.scrollY / maximum));
      document.documentElement.style.setProperty("--expedition-progress", progress.toFixed(4));
      frame = null;
    };
    const onScroll = () => { if (frame === null) frame = requestAnimationFrame(update); };
    update();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      if (frame !== null) cancelAnimationFrame(frame);
      window.removeEventListener("scroll", onScroll);
      document.documentElement.style.removeProperty("--expedition-progress");
    };
  }, []);

  return (
    <main
      className="cinematic-onboarding"
      data-active-chapter={activeChapter + 1}
      data-observer={"IntersectionObserver" in window ? "available" : "fallback"}
    >
      <PointerComet />
      <header className="expedition-header">
        <span className="expedition-brand"><BriefcaseBusiness aria-hidden="true" />Career RAG</span>
        <Link className="expedition-skip" to="/workspace">跳过远征<ArrowRight aria-hidden="true" /></Link>
      </header>
      <h1 className="expedition-document-title">职业远征</h1>
      <ChapterNavigation activeChapter={activeChapter} chapters={EXPEDITION_CHAPTERS} />
      <div className="expedition-stage">
        <div className="constellation-sticky"><CareerConstellation activeChapter={activeChapter} /></div>
        <div className="mission-track">
          {EXPEDITION_CHAPTERS.map((chapter, index) => (
            <MissionScene
              key={chapter.id}
              ref={(node) => { sceneRefs.current[index] = node; }}
              chapter={chapter}
              index={index}
            >
              {chapter.id === "departure" ? (
                <Link className="departure-cta" to="/workspace">进入职业匹配工作台<ArrowRight aria-hidden="true" /></Link>
              ) : null}
            </MissionScene>
          ))}
        </div>
      </div>
    </main>
  );
}
```

- [ ] **Step 5: Cut over the root route and remove the old carousel**

```tsx
// frontend/src/app/router.tsx
import { CinematicOnboardingPage } from "../features/onboarding/CinematicOnboardingPage";

// Keep the existing route tree; change only the root element:
{
  path: "/",
  element: <CinematicOnboardingPage />,
  errorElement: <RouteError />,
}
```

Delete `OnboardingPage.tsx` and `OnboardingPage.test.tsx` after the route import is replaced so only one onboarding implementation remains.

- [ ] **Step 6: Run unit and route tests and verify GREEN**

Run: `cd frontend; npm.cmd test -- src/features/onboarding`

Expected: all onboarding component tests pass.

- [ ] **Step 7: Commit the orchestration cutover**

```powershell
git add frontend/src/app/router.tsx frontend/src/features/onboarding
git commit -m "feat: orchestrate the cinematic expedition"
```

### Task 5: Cinematic Styling and Browser Contracts

**Files:**
- Create: `frontend/src/styles/onboarding-cinematic.css`
- Modify: `frontend/src/features/onboarding/CinematicOnboardingPage.tsx`
- Modify: `frontend/src/styles/global.css`
- Modify: `frontend/e2e/onboarding.spec.ts`

**Interfaces:**
- Consumes: every `.cinematic-*`, `.expedition-*`, `.mission-*`, `.career-constellation`, `.chapter-navigation`, and `.pointer-comet` class from Tasks 1–4.
- Produces: sticky desktop cinema, non-sticky mobile flow, SVG route motion, bounded pointer trail, and reduced-motion final states.

- [ ] **Step 1: Replace the old E2E assertions with failing cinematic contracts**

```ts
import { expect, test } from "@playwright/test";

test("keeps the seven-scene expedition isolated from business APIs", async ({ page }) => {
  let apiCalls = 0;
  await page.route("**/api/v1/**", async (route) => {
    apiCalls += 1;
    await route.fulfill({ status: 503, contentType: "application/json", body: "{}" });
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "职业远征" })).toBeVisible();
  await expect(page.getAllByRole("region")).toHaveCount(7);
  expect(apiCalls).toBe(0);
  expect(await page.evaluate(() => localStorage.length + sessionStorage.length)).toBe(0);
  await expect(page.getByRole("link", { name: "跳过远征" })).toBeVisible();
});

test("advances the constellation and chapter rail through real scrolling", async ({ page }) => {
  await page.goto("/");
  await page.locator("#scene-fleet").scrollIntoViewIfNeeded();
  await expect(page.locator('a[href="#scene-fleet"]')).toHaveAttribute("aria-current", "step");
  await expect(page.locator(".career-constellation")).toHaveAttribute("data-chapter", "5");
});

test("renders a bounded desktop comet and disables it for reduced motion", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.goto("/");
  await expect(page.locator(".pointer-comet-particle")).toHaveCount(18);
  await page.mouse.move(240, 220);
  await page.mouse.move(480, 320, { steps: 8 });
  await expect.poll(() => page.locator(".pointer-comet-particle").first().evaluate((node) => Number(getComputedStyle(node).opacity))).toBeGreaterThan(0);

  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.reload();
  await expect(page.getByTestId("pointer-comet")).toBeHidden();
  await expect(page.locator(".route-active")).toHaveCSS("stroke-dashoffset", "0px");
});

test("keeps the cinematic route responsive and preserves the workspace exit", async ({ page }) => {
  await page.goto("/");
  for (const width of [375, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.reload();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "跳过远征" })).toBeFocused();
  await page.getByRole("link", { name: "跳过远征" }).click();
  await expect(page).toHaveURL(/\/workspace$/);
  await expect(page.getByRole("heading", { name: "先从一份真实简历开始" })).toBeVisible();
});
```

- [ ] **Step 2: Run E2E and verify RED**

Run: `cd frontend; npm.cmd run e2e -- e2e/onboarding.spec.ts`

Expected: FAIL because cinematic CSS is not imported and sticky/motion/reduced-motion contracts are absent.

- [ ] **Step 3: Import the isolated stylesheet**

```tsx
// First import in CinematicOnboardingPage.tsx
import "../../styles/onboarding-cinematic.css";
```

- [ ] **Step 4: Add the cinematic CSS implementation**

```css
.cinematic-onboarding {
  min-height: 100vh;
  position: relative;
  overflow: clip;
  color: #edf4ff;
  background: #060b18;
  isolation: isolate;
}
.cinematic-onboarding::before {
  content: "";
  width: min(72vw, 980px);
  height: 1px;
  position: fixed;
  z-index: -1;
  left: 50%;
  bottom: 9vh;
  transform: translateX(-50%) scaleX(calc(.35 + var(--expedition-progress, 0) * .65));
  background: #70b7ff;
  box-shadow: 0 0 54px 16px rgb(112 183 255 / .18), 0 0 120px 28px rgb(94 234 212 / .08);
}
.expedition-header {
  min-height: 78px;
  padding: 14px clamp(20px, 4vw, 64px);
  display: flex;
  align-items: center;
  justify-content: space-between;
  position: fixed;
  z-index: 30;
  inset: 0 0 auto;
  background: rgb(6 11 24 / .88);
  border-bottom: 1px solid rgb(112 183 255 / .18);
}
.expedition-brand, .expedition-skip, .departure-cta { display: inline-flex; align-items: center; gap: 10px; }
.expedition-brand { color: #edf4ff; font-family: var(--font-display); font-weight: 760; letter-spacing: .08em; }
.expedition-skip, .departure-cta {
  min-height: 48px;
  padding: 0 18px;
  color: #edf4ff;
  border: 1px solid rgb(216 182 106 / .72);
  border-radius: 999px;
  text-decoration: none;
  font-weight: 760;
  transition: transform 180ms ease, background-color 180ms ease;
}
.expedition-skip:hover, .departure-cta:hover { transform: translateY(-2px); background: rgb(216 182 106 / .12); }
.expedition-skip:focus-visible, .departure-cta:focus-visible, .chapter-navigation a:focus-visible { outline: 3px solid #d8b66a; outline-offset: 4px; }
.expedition-document-title { width: 1px; height: 1px; position: absolute; overflow: hidden; clip: rect(0 0 0 0); }
.expedition-stage { width: min(1500px, 100%); margin: 0 auto; display: grid; grid-template-columns: minmax(420px, .95fr) minmax(0, 1.05fr); }
.constellation-sticky { min-height: 100vh; padding: 104px 0 36px clamp(24px, 5vw, 80px); display: grid; align-items: center; position: sticky; top: 0; }
.career-constellation { width: 100%; margin: 0; position: relative; }
.career-constellation svg { width: 100%; height: auto; overflow: visible; }
.career-constellation figcaption { color: #5eead4; font-family: var(--font-mono); font-size: .7rem; letter-spacing: .14em; }
.constellation-route { fill: none; stroke-width: 2; vector-effect: non-scaling-stroke; }
.route-ghost { stroke: rgb(112 183 255 / .18); }
.route-active { stroke: #70b7ff; stroke-dasharray: 1; stroke-dashoffset: calc(1 - var(--expedition-progress, 0)); }
.constellation-signal { color: #53647e; opacity: .3; transition: opacity 700ms ease, color 700ms ease; }
.constellation-signal circle:first-child { fill: currentColor; }
.constellation-signal .signal-halo { fill: none; stroke: currentColor; stroke-width: 1; opacity: .32; transform-box: fill-box; transform-origin: center; }
.constellation-signal text, .supervisor-gate text { fill: currentColor; font-family: var(--font-mono); font-size: 12px; letter-spacing: .08em; }
.constellation-signal.is-active { color: #5eead4; opacity: 1; }
.constellation-signal.is-active .signal-halo { animation: constellation-breathe 2.8s ease-in-out infinite; }
.supervisor-gate { color: #d8b66a; opacity: .18; transition: opacity 700ms ease; }
.supervisor-gate rect { fill: rgb(216 182 106 / .06); stroke: currentColor; stroke-width: 2; }
.supervisor-gate.is-active { opacity: 1; }
.mission-track { min-width: 0; }
.mission-scene {
  min-height: 100vh;
  padding: 18vh clamp(28px, 7vw, 108px) 12vh;
  display: flex;
  flex-direction: column;
  justify-content: center;
  opacity: .35;
  transform: translateY(34px);
  transition: opacity 700ms cubic-bezier(.2,.75,.25,1), transform 700ms cubic-bezier(.2,.75,.25,1);
  scroll-margin-top: 90px;
}
.cinematic-onboarding[data-active-chapter="1"] [data-scene-index="0"],
.cinematic-onboarding[data-active-chapter="2"] [data-scene-index="1"],
.cinematic-onboarding[data-active-chapter="3"] [data-scene-index="2"],
.cinematic-onboarding[data-active-chapter="4"] [data-scene-index="3"],
.cinematic-onboarding[data-active-chapter="5"] [data-scene-index="4"],
.cinematic-onboarding[data-active-chapter="6"] [data-scene-index="5"],
.cinematic-onboarding[data-active-chapter="7"] [data-scene-index="6"] { opacity: 1; transform: translateY(0); }
.cinematic-onboarding[data-observer="fallback"] .mission-scene { opacity: 1; transform: none; }
.mission-number, .mission-eyebrow, .mission-coordinate { font-family: var(--font-mono); letter-spacing: .14em; }
.mission-number { margin-bottom: clamp(44px, 8vh, 96px); color: #d8b66a; font-size: .76rem; }
.mission-eyebrow { margin-bottom: 14px; color: #70b7ff; font-size: .72rem; }
.mission-scene h2 { max-width: 780px; margin: 0 0 24px; color: #edf4ff; font-family: var(--font-display); font-size: clamp(3rem, 6vw, 7.2rem); font-weight: 720; line-height: .94; letter-spacing: -.045em; text-wrap: balance; }
.mission-body { max-width: 680px; color: #afbdd0; font-size: clamp(1rem, 1.55vw, 1.2rem); line-height: 1.85; }
.mission-coordinate { margin-top: 28px; color: #5eead4; font-size: .68rem; line-height: 1.7; }
.departure-cta { width: fit-content; margin-top: 42px; color: #060b18; background: #d8b66a; }
.chapter-navigation { position: fixed; z-index: 22; top: 50%; right: 18px; transform: translateY(-50%); }
.chapter-navigation ol { margin: 0; padding: 0; display: grid; gap: 7px; list-style: none; }
.chapter-navigation a { min-width: 48px; min-height: 44px; padding: 8px 10px; display: grid; justify-items: end; color: #71809a; text-decoration: none; }
.chapter-navigation strong { max-width: 0; overflow: hidden; opacity: 0; white-space: nowrap; transition: max-width 220ms ease, opacity 220ms ease; }
.chapter-navigation a:hover strong, .chapter-navigation a[aria-current="step"] strong { max-width: 210px; opacity: 1; }
.chapter-navigation a[aria-current="step"] { color: #d8b66a; }
.pointer-comet { position: fixed; z-index: 50; inset: 0; pointer-events: none; overflow: hidden; }
.pointer-comet-particle { width: 8px; height: 8px; position: absolute; top: -4px; left: -4px; opacity: 0; background: #70b7ff; border-radius: 50%; box-shadow: 0 0 15px rgb(112 183 255 / .7); will-change: transform, opacity; }
.pointer-comet-particle:nth-child(3n) { width: 5px; height: 5px; background: #5eead4; }
.pointer-comet-particle:nth-child(5n) { background: #d8b66a; }
@keyframes constellation-breathe { 0%,100% { transform: scale(.82); opacity: .2; } 50% { transform: scale(1.18); opacity: .5; } }
@media (max-width: 900px) {
  .expedition-stage { grid-template-columns: 1fr; }
  .constellation-sticky { min-height: 52vh; padding: 96px 22px 0; top: 0; z-index: 4; background: #060b18; }
  .career-constellation { width: min(720px, 100%); margin-inline: auto; }
  .mission-scene { min-height: 82vh; padding: 14vh clamp(24px, 7vw, 64px) 10vh; }
  .chapter-navigation { display: none; }
}
@media (max-width: 600px) {
  .expedition-header { min-height: 70px; padding: 10px 14px; }
  .expedition-skip { min-height: 46px; padding-inline: 13px; }
  .constellation-sticky { min-height: auto; padding: 92px 8px 10px; position: static; }
  .mission-scene { min-height: 88vh; padding: 12vh 22px 8vh; opacity: 1; transform: none; }
  .mission-scene h2 { font-size: clamp(2.7rem, 13vw, 4.4rem); }
  .pointer-comet { display: none; }
}
@media (pointer: coarse) { .pointer-comet { display: none; } }
@media (prefers-reduced-motion: reduce) {
  .cinematic-onboarding *, .cinematic-onboarding *::before, .cinematic-onboarding *::after { animation: none !important; transition: none !important; scroll-behavior: auto !important; }
  .mission-scene, .constellation-signal, .supervisor-gate { opacity: 1; transform: none; }
  .route-active { stroke-dashoffset: 0; }
  .pointer-comet { display: none; }
}
```

- [ ] **Step 5: Remove dead carousel CSS from `global.css`**

Delete the complete selector block beginning at `.onboarding-shell` and ending after `@keyframes orbit-breathe`. In both existing responsive media blocks, delete only rules whose selectors begin with `.onboarding-`, `.intro-visual`, `.evidence-relay`, `.relay-`, `.agent-node`, `.supervisor-node`, `.intent-node`, `.matching-node`, `.strategy-node`, `.space-card`, `.trust-gate`, or `.trust-output`. Keep workbench, monitoring, progress-board, and global reduced-motion rules unchanged.

- [ ] **Step 6: Run focused unit and browser tests and verify GREEN**

Run: `cd frontend; npm.cmd test -- src/features/onboarding`

Run: `cd frontend; npm.cmd run e2e -- e2e/onboarding.spec.ts`

Expected: onboarding unit tests pass; 4 cinematic E2E tests pass.

- [ ] **Step 7: Commit cinematic styling**

```powershell
git add frontend/src/styles/global.css frontend/src/styles/onboarding-cinematic.css frontend/src/features/onboarding/CinematicOnboardingPage.tsx frontend/e2e/onboarding.spec.ts
git commit -m "feat: stage the cinematic career expedition"
```

### Task 6: Performance, Accessibility, Regression, and Publication Gate

**Files:**
- Modify only when a failing test proves a regression.
- Review: all files changed by Tasks 1–5.

**Interfaces:**
- Consumes: the complete cinematic route.
- Produces: verified build evidence and a review-ready branch without touching backend code or unrelated files.

- [ ] **Step 1: Run the complete frontend static and unit gate**

```powershell
cd frontend
npm.cmd run api:check
npm.cmd test
npm.cmd run typecheck
npm.cmd run build
```

Expected: all commands exit 0; Vitest includes the new onboarding suites; Vite reports one JavaScript asset with gzip size at or below 133.79 kB.

- [ ] **Step 2: Run the complete browser suite**

Run: `cd frontend; npm.cmd run e2e`

Expected: cinematic onboarding, full business flow, recovery, evaluation capability, and monitoring tests all pass.

- [ ] **Step 3: Run the backend regression because the branch is publishable**

Run: `.\.venv\Scripts\python.exe -m pytest -q`

Expected: at least the existing 211 backend tests pass with no new warning category.

- [ ] **Step 4: Inspect the real page and performance behavior**

Open `http://127.0.0.1:4173/` and verify:

```text
- all seven scenes are readable in order;
- constellation route grows as chapters advance;
- 18 pooled particles follow a precise pointer briefly and settle after inactivity;
- no particles appear under reduced motion or a 375px mobile viewport;
- scrolling stays native and controls remain clickable;
- browser console has no warning or error;
- network shows no /api/v1 request before entering /workspace.
```

- [ ] **Step 5: Run repository and secret-scope checks**

```powershell
git diff --check
git status -sb
git ls-files .env .env.*
git check-ignore -v .env
git grep --cached -l -I -E "sk-[A-Za-z0-9_-]{16,}|AKIA[0-9A-Z]{16}|BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY" -- ":!*.lock" ":!package-lock.json"
```

Expected: no whitespace error; only `.env.example` is tracked; `.env` is ignored; no staged secret-signature path is returned; unrelated untracked files remain uncommitted.

- [ ] **Step 6: Request independent code review**

Give the reviewer the design specification, this plan, the implementation base commit, and current HEAD. Require findings to cite file and line, and fix every Critical or Important item before publication.

- [ ] **Step 7: Commit only test-proven review fixes**

```powershell
git add frontend/src/app/router.tsx frontend/src/features/onboarding frontend/src/styles/global.css frontend/src/styles/onboarding-cinematic.css frontend/e2e/onboarding.spec.ts
git diff --cached --check
git commit -m "fix: harden cinematic expedition"
```

If review produces no code change, do not create an empty commit.

- [ ] **Step 8: Push and verify both remotes after user-approved publication**

```powershell
git push origin codex/week3-reoptimization
git push gitlab codex/week3-reoptimization
git ls-remote origin refs/heads/codex/week3-reoptimization
git ls-remote gitlab refs/heads/codex/week3-reoptimization
git rev-parse HEAD
```

Expected: GitHub hash, GitLab hash, and local HEAD are identical.
