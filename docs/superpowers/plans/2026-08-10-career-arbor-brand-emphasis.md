# Career Arbor Brand Emphasis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Strengthen the bilingual Career Arbor brand hierarchy and interaction while preventing localized P3 tier badges from entering the job-title column.

**Architecture:** Keep the existing React component structure and warm editorial token system. Implement three sequential frontend slices: global wordmark interaction in `theme.css`, a HomePage-only semantic brand lockup, and display-only tier localization plus badge containment. Use Vitest for translation/semantic contracts and Playwright for computed-style, focus, motion, collision, and geometry behavior.

**Tech Stack:** React 19, TypeScript 5.9, Vite 8, Vitest 4, Testing Library, Playwright 1.61, plain CSS.

## Global Constraints

- Preserve `BrandHomeLink` routing, intro marking, accessible name, and native link semantics.
- Keep the existing warm paper/editorial palette and current font tokens; do not add assets, fonts, dependencies, glassmorphism, glow pills, or unrelated redesign.
- The branch-growth line and leaf node are the single signature effect; animation uses only `transform` and `opacity`, approximately 220ms, and never changes layout bounds.
- Every brand link has a minimum 44px target and a distinct `:focus-visible` outline; normal text contrast is at least 4.5:1 and the focus indicator is at least 3:1 against adjacent colors.
- `prefers-reduced-motion: reduce` removes brand transitions plus dynamic scaling and translation while retaining an immediate focus outline, full static branch line, and the leaf's fixed illustrative rotation.
- HomePage keeps exactly one `h1`; computed type hierarchy must satisfy `tagline < brand name < h1`, with screenshot review deciding final optical balance.
- Home lockup is verified at 320, 375, 650, and 1280px in both languages. The real mobile app bar is verified at 320, 375, and 650px in both languages; the real desktop sidebar wordmark is verified at 1280px in both languages.
- Translate only the P3 display labels to `Now Fit`, `Stretch Fit`, and `Bridge Role`; do not change `now_fit`, `stretch_fit`, `bridge_role`, API values, fixtures, database values, or backend files.
- Tier badges must stay within their own `td` at 320, 375, 650, and 1280px; only `.v2-result-table-wrap` may scroll horizontally on narrow screens.
- Use TDD for every behavior change: add a test, run it and observe the expected failure, then write the minimum production code.
- Do not stage or modify `app.tar.gz` or `frontend-dist.tar.gz`.
- Do not move or delete any file during implementation. Cleanup is a later dry-run and explicit approval gate; tracked test sources remain in the repository.
- Run every `npm.cmd` and `npx.cmd` command with `frontend` as the working directory. Git commands run from the repository root.

## Execution Preflight

Before Task 1, after the implementation-plan commit and after the worktree decision:

1. In the final selected working tree, create `.planning/career_arbor_brand_polish` before any process-file read or write. If an isolated worktree is selected, initialize fresh `task_plan.md`, `findings.md`, `progress.md`, and `.planning/.active_plan` there from this approved plan; do not read or write the parent checkout's `.planning` paths.
2. Generate a run ID in the form `career-arbor-YYYYMMDD-HHmmssfff`. Verify `frontend/test-results/<run-id>` does not exist, then record the value in `.planning/career_arbor_brand_polish/run_id.txt`. Every Playwright command uses a different, previously nonexistent child of that run root through `--output`; no command targets or cleans an existing default output directory. The shown paths end in `-01`; any retry increments the suffix to `-02`, `-03`, and so on after confirming that child does not exist.
3. Record the exact implementation base with `git rev-parse HEAD` in `.planning/career_arbor_brand_polish/base_sha.txt`. Every task review and the final review uses this recorded SHA, never `HEAD~1`.
4. Before any test/build command, recursively inventory the fixed generated-artifact candidates that already exist: `frontend/test-results`, `frontend/playwright-report`, and `frontend/*.tsbuildinfo`. Playwright screenshots are written below the unique run root through `testInfo.outputPath`. Record path, length, modification time, and SHA256 in `.planning/career_arbor_brand_polish/generated-baseline.csv`.
5. Keep `.planning/` untracked as process state. The formal plan document is committed separately before production work. Task commits and review-fix commits contain only the source/test files named in Tasks 1–3.
6. Generate the baseline CSV mechanically from the repository root with:

```powershell
$candidateFiles = @()
foreach ($candidateRoot in @("frontend\test-results", "frontend\playwright-report")) {
  if (Test-Path -LiteralPath $candidateRoot) {
    $candidateFiles += Get-ChildItem -LiteralPath $candidateRoot -Recurse -File
  }
}
$candidateFiles += Get-ChildItem -LiteralPath "frontend" -Filter "*.tsbuildinfo" -File
$candidateFiles |
  Sort-Object FullName -Unique |
  ForEach-Object {
    [pscustomobject]@{
      Path = $_.FullName
      Length = $_.Length
      LastWriteTimeUtc = $_.LastWriteTimeUtc.ToString("o")
      SHA256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
    }
  } |
  Export-Csv -LiteralPath ".planning\career_arbor_brand_polish\generated-baseline.csv" -NoTypeInformation -Encoding UTF8
```

7. Verify the complete frontend baseline from the `frontend` working directory. If any command fails for a product reason, stop and report; do not hide a pre-existing failure:

```powershell
$runId = (Get-Content -LiteralPath "..\.planning\career_arbor_brand_polish\run_id.txt" -Raw).Trim()
npm.cmd test -- --configLoader native
npm.cmd run typecheck
npm.cmd run build
npx.cmd playwright test --output "test-results\$runId\baseline-01"
```

---

### Task 1: Enlarge the Global Wordmark and Add Branch-Growth Feedback

**Files:**
- Modify: `frontend/e2e/final-polish.spec.ts`
- Modify: `frontend/src/v2/theme.css:3-32,90-121,344-356`

**Interfaces:**
- Consumes: existing `.v2-wordmark` links emitted by `BrandHomeLink`; existing authenticated and unauthorized route helpers in `final-polish.spec.ts`.
- Produces: a shared `.v2-wordmark` contract with a 44px target, responsive type scale, branch/leaf pseudo-elements, focus feedback, and reduced-motion behavior used by HomePage, WelcomePage, LandingPage, desktop sidebar, and mobile app bar.

- [ ] **Step 1: Add a failing desktop interaction test**

Append a Playwright test that uses the real `/welcome` navigation and checks target size, hover branch expansion, and keyboard focus:

```ts
test("brand wordmark has a 44px target and branch feedback", async ({ page }) => {
  await installUnauthorizedApi(page);
  await page.goto("/welcome");

  const brand = page.getByRole("link", { name: "枝涯" });
  const target = await brand.boundingBox();
  expect(target).not.toBeNull();
  expect(target!.height).toBeGreaterThanOrEqual(44);

  const idle = await brand.evaluate((element) => ({
    line: getComputedStyle(element, "::after").transform,
    leaf: getComputedStyle(element, "::before").opacity,
  }));
  await brand.hover();
  await expect
    .poll(() =>
      brand.evaluate((element) => ({
        line: getComputedStyle(element, "::after").transform,
        leaf: getComputedStyle(element, "::before").opacity,
      })),
    )
    .not.toEqual(idle);

  const layoutBeforePress = await brand.evaluate((element) => {
    const nav = element.closest("nav")!.getBoundingClientRect();
    const actions = element.closest("nav")!.querySelector<HTMLElement>(
      ".wl-topbar-actions",
    )!.getBoundingClientRect();
    return { navWidth: nav.width, navHeight: nav.height, actionsLeft: actions.left };
  });
  await page.mouse.down();
  expect(await brand.evaluate((element) => getComputedStyle(element).transform)).not.toBe("none");
  const layoutDuringPress = await brand.evaluate((element) => {
    const nav = element.closest("nav")!.getBoundingClientRect();
    const actions = element.closest("nav")!.querySelector<HTMLElement>(
      ".wl-topbar-actions",
    )!.getBoundingClientRect();
    return { navWidth: nav.width, navHeight: nav.height, actionsLeft: actions.left };
  });
  expect(layoutDuringPress).toEqual(layoutBeforePress);
  await page.mouse.move(0, 0);
  await page.mouse.up();
  await brand.evaluate((element) => (element as HTMLElement).blur());
  await expect(page).toHaveURL(/\/welcome$/);
  await expect
    .poll(() => page.evaluate(() => document.activeElement === document.body))
    .toBe(true);
  await expect
    .poll(() =>
      brand.evaluate((element) => ({
        line: getComputedStyle(element, "::after").transform,
        leaf: getComputedStyle(element, "::before").opacity,
      })),
    )
    .toEqual(idle);
  await page.keyboard.press("Tab");
  await expect(brand).toBeFocused();
  const focus = await brand.evaluate((element) => ({
    outlineStyle: getComputedStyle(element).outlineStyle,
    outlineWidth: Number.parseFloat(getComputedStyle(element).outlineWidth),
    outlineColor: getComputedStyle(element).outlineColor,
    color: getComputedStyle(element).color,
    backgroundColor: getComputedStyle(element.closest(".wl-page")!).backgroundColor,
    line: getComputedStyle(element, "::after").transform,
  }));
  expect(focus.outlineStyle).toBe("solid");
  expect(focus.outlineWidth).toBeGreaterThanOrEqual(2);
  await expect
    .poll(() => brand.evaluate((element) => getComputedStyle(element, "::after").transform))
    .not.toBe(idle.line);
});
```

Use the existing WCAG sRGB helper pattern in this repository to calculate contrast from the returned colors. Assert at least `3` for the focus outline against its adjacent background and at least `4.5` for wordmark text against that background.

- [ ] **Step 2: Add failing mobile collision and reduced-motion tests**

Add one test per mobile width that verifies both languages in the real authenticated app bar:

```ts
for (const width of [320, 375, 650]) {
  test(`mobile wordmark remains tappable and separated at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 812 });
    await installAuthenticatedShellApi(page);
    await page.goto("/app");

    const nav = page.locator(".v2-mobile-nav");
    const assertSeparated = async (brandName: string) => {
      await expect(nav.getByRole("link", { name: brandName })).toBeVisible();
      const boxes = await nav.evaluate((element) => {
        const box = (selector: string) => {
          const value = element.querySelector<HTMLElement>(selector)!.getBoundingClientRect();
          return { left: value.left, right: value.right, top: value.top, bottom: value.bottom };
        };
        return {
          menu: box(".v2-mobile-nav-trigger"),
          brand: box(".v2-wordmark"),
          language: box(".v2-language-toggle"),
        };
      });
      expect(boxes.brand.bottom - boxes.brand.top).toBeGreaterThanOrEqual(44);
      expect(boxes.menu.right).toBeLessThanOrEqual(boxes.brand.left);
      expect(boxes.brand.right).toBeLessThanOrEqual(boxes.language.left);
      expect(boxes.language.right).toBeLessThanOrEqual(width);
    };

    await assertSeparated("枝涯");
    await page.getByRole("button", { name: "当前语言：中文；切换到 English" }).click();
    await assertSeparated("Career Arbor");
    if (width === 375) {
      await page.screenshot({
        path: testInfo.outputPath("mobile-app-bar-en-375.png"),
        fullPage: true,
      });
    }
  });
}
```

Add a 1280px authenticated test scoped to `.v2-sidebar`. Verify both `枝涯` and `Career Arbor` are visible after the real language toggle, each wordmark is at least 44px high, and its rectangle stays inside the sidebar rectangle.

Add a reduced-motion test that calls `page.emulateMedia({ reducedMotion: "reduce" })`, loads `/welcome`, focuses the brand with `Tab`, and asserts the link and both pseudo-elements have only zero-second transition durations. Assert the outline is visible, the full branch line has `transform: none`, and the leaf has no scale or translation component.

- [ ] **Step 3: Run Task 1 tests and verify RED**

Run with `frontend` as the working directory:

```powershell
$runId = (Get-Content -LiteralPath "..\.planning\career_arbor_brand_polish\run_id.txt" -Raw).Trim()
npx.cmd playwright test e2e/final-polish.spec.ts --project=chromium --output "test-results\$runId\task1-red-01"
```

Expected: the new target-size test fails because `.v2-wordmark` has no 44px minimum; branch pseudo-element and reduced-motion assertions also fail because those rules do not exist.

- [ ] **Step 4: Implement the minimum wordmark CSS**

Replace the compact `.v2-wordmark` rules with a shared motion token and a positioned inline-flex link. Use the following contract, adjusting only the narrow-screen clamp if the 320px geometry test proves it necessary:

```css
:root {
  --v2-brand-motion: 220ms;
}

.v2-wordmark {
  position: relative;
  min-width: 44px;
  min-height: 44px;
  display: inline-flex;
  align-items: center;
  color: inherit;
  font-family: var(--v2-serif);
  font-size: clamp(1.45rem, 1.25rem + 0.7vw, 1.8rem);
  font-weight: 680;
  line-height: 1.05;
  letter-spacing: 0.005em;
  text-decoration: none;
  isolation: isolate;
  transition: color var(--v2-brand-motion) ease-out,
    transform var(--v2-brand-motion) ease-out;
}
.v2-wordmark::after {
  content: "";
  position: absolute;
  right: 0;
  bottom: 4px;
  left: 0;
  height: 1px;
  pointer-events: none;
  background: var(--v2-accent);
  opacity: 0.42;
  transform: scaleX(0.28);
  transform-origin: left center;
  transition: opacity var(--v2-brand-motion) ease-out,
    transform var(--v2-brand-motion) ease-out;
}
.v2-wordmark::before {
  content: "";
  position: absolute;
  right: -1px;
  bottom: 5px;
  width: 8px;
  height: 5px;
  pointer-events: none;
  border-radius: 100% 0 100% 0;
  background: var(--v2-accent);
  opacity: 0;
  transform: rotate(-30deg) scale(0.55);
  transform-origin: left bottom;
  transition: opacity var(--v2-brand-motion) ease-out,
    transform var(--v2-brand-motion) ease-out;
}
.v2-wordmark:hover,
.v2-wordmark:focus-visible { color: var(--v2-accent-hover); }
.v2-wordmark:hover::after,
.v2-wordmark:focus-visible::after { opacity: 1; transform: scaleX(1); }
.v2-wordmark:hover::before,
.v2-wordmark:focus-visible::before { opacity: 1; transform: rotate(-30deg) scale(1); }
.v2-wordmark:active { transform: translateY(1px); }
.v2-wordmark:focus-visible {
  border-radius: 4px;
  outline: 2px solid var(--v2-accent);
  outline-offset: 4px;
}
```

Extend the existing reduced-motion query:

```css
.v2-wordmark,
.v2-wordmark::before,
.v2-wordmark::after { transition: none; }
.v2-wordmark:active { transform: none; }
.v2-wordmark:focus-visible::after { opacity: 1; transform: none; }
.v2-wordmark:focus-visible::before { opacity: 1; transform: rotate(-30deg); }
```

If the 320px test fails, add one scoped `@media (max-width: 360px)` rule that lowers only `.v2-mobile-nav .v2-wordmark` to `1.32rem`; do not reduce the 44px target or hide controls.

- [ ] **Step 5: Run Task 1 tests and verify GREEN**

Run from `frontend`:

```powershell
$runId = (Get-Content -LiteralPath "..\.planning\career_arbor_brand_polish\run_id.txt" -Raw).Trim()
npx.cmd playwright test e2e/final-polish.spec.ts --project=chromium --output "test-results\$runId\task1-green-01"
```

Expected: all tests in `final-polish.spec.ts` pass, including existing homepage routing and sidebar alignment tests.

- [ ] **Step 6: Self-review and commit Task 1**

Confirm pseudo-elements have empty content and `pointer-events:none`, the link accessible name is unchanged, and every changed line traces to the wordmark request. Commit only the two Task 1 files:

```powershell
git add -- frontend/e2e/final-polish.spec.ts frontend/src/v2/theme.css
git commit -m "feat(v2): emphasize the Career Arbor wordmark"
```

---

### Task 2: Promote the HomePage Brand Lockup

**Files:**
- Modify: `frontend/src/i18n/i18n.test.tsx:394-433`
- Modify: `frontend/src/v2/HomePage.tsx:72-79`
- Modify: `frontend/src/i18n/en.ts:1-12`
- Modify: `frontend/src/v2/marketing.css:3-10,97-103`
- Modify: `frontend/e2e/final-polish.spec.ts`

**Interfaces:**
- Consumes: the Task 1 wordmark contract and existing `useLanguage().t` translator.
- Produces: `.mk-brand-lockup`, `.mk-brand-name`, `.mk-brand-branch`, and `.mk-brand-slogan`; separate translation keys for the name and tagline; no changes to WelcomePage eyebrow behavior.

- [ ] **Step 1: Add failing semantic and translation tests**

Update the Chinese and English HomePage assertions in `i18n.test.tsx` to require separate elements and exactly one primary heading:

```ts
expect(screen.getByText("枝涯 Career Arbor", { selector: ".mk-brand-name" })).toBeVisible();
expect(screen.getByText("循枝见路，向远而生", { selector: ".mk-brand-slogan" })).toBeVisible();
expect(document.querySelectorAll("h1")).toHaveLength(1);
```

After language switching:

```ts
expect(screen.getByText("Career Arbor", { selector: ".mk-brand-name" })).toBeVisible();
expect(
  screen.getByText("Follow the branches, find your path.", {
    selector: ".mk-brand-slogan",
  }),
).toBeVisible();
expect(document.querySelectorAll("h1")).toHaveLength(1);
```

- [ ] **Step 2: Add a failing browser hierarchy test**

Add a test that marks the intro as seen, opens `/`, and loops over widths 320, 375, 650, and 1280. At the start of every width iteration, set `career_rag_lang_v1` to `zh` and reload so the sequence is deterministic. For Chinese and then English, read computed font sizes for `.mk-brand-slogan`, `.mk-brand-name`, and `.mk-hero h1`; assert `slogan < name < h1`, `document.querySelectorAll("h1").length === 1`, `documentElement.scrollWidth <= clientWidth`, and the lockup box remains inside the viewport. Use the real language toggle between assertions. Accept `testInfo` in the callback and save `home-${width}-zh.png` before switching languages and `home-${width}-en.png` after switching via `testInfo.outputPath(...)` for all four widths.

- [ ] **Step 3: Run Task 2 tests and verify RED**

Run both commands with `frontend` as the working directory:

```powershell
npm.cmd test -- src/i18n/i18n.test.tsx --configLoader native
$runId = (Get-Content -LiteralPath "..\.planning\career_arbor_brand_polish\run_id.txt" -Raw).Trim()
npx.cmd playwright test e2e/final-polish.spec.ts --project=chromium --output "test-results\$runId\task2-red-01"
```

Expected: Vitest cannot find `.mk-brand-name` and `.mk-brand-slogan`; Playwright reports the existing `0.78rem` lockup does not satisfy the desired hierarchy.

- [ ] **Step 4: Split the HomePage markup and translations**

Replace the single eyebrow paragraph with:

```tsx
<p className="mk-brand-lockup">
  <strong className="mk-brand-name">{t("枝涯 Career Arbor")}</strong>
  <span className="mk-brand-branch" aria-hidden="true" />
  <span className="mk-brand-slogan">{t("循枝见路，向远而生")}</span>
</p>
```

Replace the old combined English entry with:

```ts
"枝涯 Career Arbor": "Career Arbor",
"循枝见路，向远而生": "Follow the branches, find your path.",
```

Keep the combined key only if `rg` proves another production caller remains; otherwise remove the newly orphaned entry.

- [ ] **Step 5: Add the HomePage-only lockup styles**

Leave `.mk-eyebrow` unchanged and add:

```css
.mk-brand-lockup {
  min-width: 0;
  margin: 0 0 24px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 10px 14px;
}
.mk-brand-name {
  color: var(--v2-ink);
  font: 680 clamp(1.65rem, 3.1vw, 2.25rem)/1.05 var(--v2-serif);
  letter-spacing: -0.015em;
}
.mk-brand-slogan {
  color: var(--v2-accent-hover);
  font: 620 clamp(0.95rem, 1.2vw, 1.1rem)/1.4 var(--v2-sans);
  letter-spacing: 0.035em;
}
.mk-brand-branch {
  position: relative;
  flex: 0 0 clamp(34px, 5vw, 58px);
  height: 1px;
  background: var(--v2-accent);
}
.mk-brand-branch::after {
  content: "";
  position: absolute;
  top: -3px;
  right: 0;
  width: 7px;
  height: 4px;
  border-radius: 100% 0 100% 0;
  background: var(--v2-accent);
  transform: rotate(-30deg);
}
@media (max-width: 520px) {
  .mk-brand-lockup { flex-direction: column; gap: 8px; }
  .mk-brand-branch { width: 48px; flex-basis: 1px; }
}
```

Do not animate the homepage divider; Task 1 already owns the single signature motion.

- [ ] **Step 6: Run Task 2 tests and verify GREEN**

Run both targeted commands again from `frontend`:

```powershell
npm.cmd test -- src/i18n/i18n.test.tsx --configLoader native
$runId = (Get-Content -LiteralPath "..\.planning\career_arbor_brand_polish\run_id.txt" -Raw).Trim()
npx.cmd playwright test e2e/final-polish.spec.ts --project=chromium --output "test-results\$runId\task2-green-01"
```

Expected: semantic, translation, hierarchy, and narrow-screen overflow tests pass; existing WelcomePage tests remain unchanged.

- [ ] **Step 7: Self-review and commit Task 2**

Verify there is one H1, the combined translation key has no orphaned caller, and the shared eyebrow has not changed. Commit only Task 2 files:

```powershell
git add -- frontend/src/i18n/i18n.test.tsx frontend/src/v2/HomePage.tsx frontend/src/i18n/en.ts frontend/src/v2/marketing.css frontend/e2e/final-polish.spec.ts
git commit -m "feat(v2): promote the homepage brand lockup"
```

---

### Task 3: Standardize English Tier Labels and Contain Every Badge

**Files:**
- Modify: `frontend/src/i18n/i18n.test.tsx:138-147,329-348`
- Modify: `frontend/src/i18n/en.ts:251-256`
- Modify: `frontend/src/v2/theme.css:254-287`
- Modify: `frontend/e2e/result-layout.spec.ts`

**Interfaces:**
- Consumes: `translate(lang, key)`, existing `tierLabel` mapping in WorkbenchPage, and the fixed-layout result table.
- Produces: display-only English taxonomy and a reusable `.v2-tier` containment contract. Internal tier keys and WorkbenchPage logic remain unchanged.

- [ ] **Step 1: Add failing translation tests**

Extend `translation primitives`:

```ts
it("uses the canonical three-tier taxonomy in English result badges", () => {
  expect(translate("en", "现在就投")).toBe("Now Fit");
  expect(translate("en", "值得冲刺")).toBe("Stretch Fit");
  expect(translate("en", "跳板岗位")).toBe("Bridge Role");
});
```

- [ ] **Step 2: Add failing result-table geometry tests**

In `result-layout.spec.ts`, add a fixture containing six `.v2-tier` badges—three Chinese and three English—inside their real second-column cells. Its helper must use the requested width as the real viewport width, not the existing `width + 40` long-title helper:

```ts
const CANONICAL_TIERS = [
  ["now_fit", "现在就投"],
  ["stretch_fit", "值得冲刺"],
  ["bridge_role", "跳板岗位"],
  ["now_fit", "Now Fit"],
  ["stretch_fit", "Stretch Fit"],
  ["bridge_role", "Bridge Role"],
] as const;

async function installTierTable(
  page: Page,
  viewportWidth: number,
  tiers: ReadonlyArray<readonly [string, string]> = CANONICAL_TIERS,
) {
  const rows = tiers
    .map(
      ([tier, label], index) => `
        <tr class="v2-result-row">
          <td>${index + 1}</td>
          <td data-testid="tier-cell"><span class="v2-tier ${tier}" data-testid="tier-badge">${label}</span></td>
          <td data-testid="job-cell"><button class="v2-result-row-trigger">Role ${index + 1}</button></td>
          <td>Example · Birmingham</td>
          <td>Demo</td>
        </tr>`,
    )
    .join("");
  await page.setViewportSize({ width: viewportWidth, height: 900 });
  await page.setContent(`
    <style>${globalSource}\n${themeSource}</style>
    <main style="width: 100%; min-width: 0">
      <div class="v2-result-table-wrap" data-testid="tier-wrapper">
        <table class="v2-result-table" aria-label="Localized tiers">
          <thead><tr><th>#</th><th>Tier</th><th>Role</th><th>Company</th><th>Corpus</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </main>
  `);
}
```

Generate tests for real viewport widths 320, 375, 650, and 1280. Accept `testInfo`, save `result-tiers-${width}.png` for every width, and for every badge assert:

```ts
expect(badge.left).toBeGreaterThanOrEqual(cell.left - 0.5);
expect(badge.right).toBeLessThanOrEqual(cell.right + 0.5);
expect(cell.right).toBeLessThanOrEqual(jobCell.left + 0.5);
```

Also assert `document.documentElement.scrollWidth <= clientWidth`; below 650px assert `tier-wrapper.scrollWidth > tier-wrapper.clientWidth`, while the document itself never owns that overflow.

Add a separate RED geometry test with an intentionally unbroken localization sentinel. This is not user-facing copy and is not included in the screenshots:

```ts
test("an unbroken localized tier remains inside its cell", async ({ page }) => {
  await installTierTable(page, 650, [
    ["stretch_fit", "LocalizedTierLabelWithoutBreakOpportunity".repeat(3)] as const,
  ]);
  const [badge, cell, jobCell] = await Promise.all([
    page.getByTestId("tier-badge").boundingBox(),
    page.getByTestId("tier-cell").boundingBox(),
    page.getByTestId("job-cell").boundingBox(),
  ]);
  expect(badge).not.toBeNull();
  expect(cell).not.toBeNull();
  expect(jobCell).not.toBeNull();
  expect(badge!.x).toBeGreaterThanOrEqual(cell!.x - 0.5);
  expect(badge!.x + badge!.width).toBeLessThanOrEqual(cell!.x + cell!.width + 0.5);
  expect(badge!.x + badge!.width).toBeLessThanOrEqual(jobCell!.x + 0.5);
});
```

- [ ] **Step 3: Run Task 3 tests and verify RED**

Run both commands with `frontend` as the working directory:

```powershell
npm.cmd test -- src/i18n/i18n.test.tsx --configLoader native
$runId = (Get-Content -LiteralPath "..\.planning\career_arbor_brand_polish\run_id.txt" -Raw).Trim()
npx.cmd playwright test e2e/result-layout.spec.ts --project=chromium --output "test-results\$runId\task3-red-01"
```

Expected: translation assertions receive `Ready to apply`, `Worth stretching for`, and `Bridge role`; canonical short-label geometry may already pass, but the unbroken localization sentinel extends outside its 104px cell and proves the CSS boundary behavior is missing.

- [ ] **Step 4: Apply display-only translations**

Change only these three values in `en.ts`:

```ts
"现在就投": "Now Fit",
"值得冲刺": "Stretch Fit",
"跳板岗位": "Bridge Role",
```

Run `rg` for the old display strings and inspect every result. Do not change backend enums, fixture keys, run summaries, or persisted data.

- [ ] **Step 5: Harden the tier badge boundary**

Replace the single-line `.v2-tier` declaration with:

```css
.v2-result-table td:nth-child(2) { min-width: 0; }
.v2-tier {
  max-width: 100%;
  min-width: 0;
  padding: 3px 9px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  border: 1px solid transparent;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 650;
  line-height: 1.2;
  text-align: center;
  white-space: normal;
  overflow-wrap: anywhere;
}
```

Do not add `overflow:hidden`, ellipsis, or a wider tier column unless the geometry test still fails after this rule and the canonical copy are both in place.

- [ ] **Step 6: Run Task 3 tests and verify GREEN**

Run both targeted commands again from `frontend`:

```powershell
npm.cmd test -- src/i18n/i18n.test.tsx --configLoader native
$runId = (Get-Content -LiteralPath "..\.planning\career_arbor_brand_polish\run_id.txt" -Raw).Trim()
npx.cmd playwright test e2e/result-layout.spec.ts --project=chromium --output "test-results\$runId\task3-green-01"
```

Expected: canonical translations and all four real viewport widths pass, including the existing long-title tests.

- [ ] **Step 7: Self-review and commit Task 3**

Confirm `WorkbenchPage.tsx`, backend files, API snapshots, and internal keys are untouched. Commit only Task 3 files:

```powershell
git add -- frontend/src/i18n/i18n.test.tsx frontend/src/i18n/en.ts frontend/src/v2/theme.css frontend/e2e/result-layout.spec.ts
git commit -m "fix(v2): contain localized result tiers"
```

---

### Task 4: Integrate, Inspect Visually, Review, and Produce Cleanup Dry Run

**Files:**
- Modify if directly required by verified behavior: files already listed in Tasks 1–3 only
- Create temporarily under Playwright output: visual evidence screenshots
- Update: `.planning/career_arbor_brand_polish/task_plan.md`
- Update: `.planning/career_arbor_brand_polish/progress.md`
- Create after all gates: a dry-run manifest inside `.planning/career_arbor_brand_polish/`

**Interfaces:**
- Consumes: all three reviewed task commits.
- Produces: final gate evidence, bilingual screenshots, broad review findings/fixes, and a non-mutating cleanup candidate manifest.

- [ ] **Step 1: Run the complete frontend verification gate**

Run from `frontend`:

```powershell
npm.cmd test -- --configLoader native
npm.cmd run typecheck
npm.cmd run build
$runId = (Get-Content -LiteralPath "..\.planning\career_arbor_brand_polish\run_id.txt" -Raw).Trim()
npx.cmd playwright test --output "test-results\$runId\final-01"
```

After the four commands pass, record `final-01` in `.planning/career_arbor_brand_polish/final_output.txt` using `apply_patch`. Every later successful final attempt replaces that value with its own child name.

Then run from the repository root:

```powershell
$baseSha = (Get-Content -LiteralPath ".planning\career_arbor_brand_polish\base_sha.txt" -Raw).Trim()
git diff --check
git diff --check "$baseSha..HEAD"
git status --short
```

Expected: all commands exit 0; there are no uncommitted source/test changes. `git status` may show only the explicitly untracked `.planning/` process state and the two pre-existing tarballs.

- [ ] **Step 2: Capture and inspect bilingual visual evidence**

Read `.planning/career_arbor_brand_polish/final_output.txt` and use only the screenshots emitted by that latest passing Playwright child: HomePage in Chinese and English at 320, 375, 650, and 1280px; the English mobile app bar at 375px; and the six-label P3 result table at 320, 375, 650, and 1280px. Inspect:

- brand name is memorable but remains optically below H1;
- tagline is legible and wraps without awkward orphaning;
- branch motion is the only animated signature (proved by the Task 1 before/after computed-style assertions; static screenshots are not motion evidence);
- mobile controls retain clear spacing;
- P3 English badges stay in the tier column.

If a visual issue appears, add a failing browser assertion before changing production CSS.

- [ ] **Step 3: Run main-agent self-review**

Review the full task range against the approved spec. Check scope, accessible semantics, contrast, motion, 320/375/650/1280 behavior, translation consistency, and test quality. Record findings in `progress.md`; fix verified defects test-first. If self-review changes source or tests, run the covering tests and create one scoped commit containing only the affected Task 1–3 files before generating the independent review package; never include `.planning/` or deployment tarballs.

- [ ] **Step 4: Run independent broad code review and repair loop**

Generate a review package from the SHA recorded in `.planning/career_arbor_brand_polish/base_sha.txt` to current HEAD. Dispatch independent reviewers for correctness, test quality, maintainability, UI/accessibility, and repository hygiene. Consolidate Critical/Important findings into one fix task, re-run covering tests, and re-review until both spec compliance and code quality are approved. Commit accepted review fixes separately with only the affected Task 1–3 source/test files; never include `.planning/` or the deployment tarballs.

- [ ] **Step 5: Re-run the final gate after every accepted review fix**

Repeat Step 1 on the final code state. Use the next previously nonexistent `final-NN` output child rather than reusing `final-01`, and record the latest passing child name in `.planning/career_arbor_brand_polish/final_output.txt`. If a fix affects UI, repeat Step 2 against that latest child. Never cite an earlier passing run or its screenshots after a later code change.

- [ ] **Step 6: Generate a non-mutating cleanup dry-run manifest**

Read the run ID and compare the final artifact inventory with `.planning/career_arbor_brand_polish/generated-baseline.csv`. The fixed allowlist may contain only the new `frontend/test-results/<run-id>` tree, files under `frontend/playwright-report` or `frontend/*.tsbuildinfo` whose SHA256 changed from baseline, plus this task's `.planning/career_arbor_brand_polish` process records and `.planning/.active_plan`. Recursively record absolute source path, baseline SHA256 if present, final size, modification time, final SHA256, candidate destination, file count, and total bytes. Verify every candidate is untracked with `git ls-files --error-unmatch` failing for that file.

Write the approval record to `.planning/career_arbor_brand_polish/cleanup-dry-run.csv`. That manifest file is deliberately excluded from its own candidate rows and SHA256 list; it remains in place as the stable approval record until the user decides the cleanup gate.

Use this proposed archive root exactly:

```text
C:\Users\WIN11\Desktop\毕业论文_birmingham\项目过程档案\2026-08-10_career-arbor-brand-polish
```

Map each candidate to a relative path below that root. If the archive root already exists, mark the dry run `STOP: target exists`; do not merge, overwrite, copy, move, or delete anything.

Explicitly list as retained:

- `frontend/dist`
- `app.tar.gz`
- `frontend-dist.tar.gz`
- `.env`, `.venv`, `frontend/node_modules`
- all tracked source, tests, docs, data, and configuration

Do not copy, move, or delete anything. Present the dry-run manifest to the user for item-by-item approval as the separate cleanup gate.

- [ ] **Step 7: Update the durable ledgers and hand off**

Mark all implementation and verification phases complete. Keep cleanup pending until the user approves the exact manifest. Report commits, latest test counts, review result, screenshot paths, and retained deployment artifacts.
