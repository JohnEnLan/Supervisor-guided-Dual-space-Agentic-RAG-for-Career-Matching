import { readFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

import { opaqueRgbContrastRatio } from "./color-contrast";

const globalSource = readFileSync(
  new URL("../src/styles/global.css", import.meta.url),
  "utf8",
);
const themeSource = readFileSync(
  new URL("../src/v2/theme.css", import.meta.url),
  "utf8",
);
const LONG_TITLE =
  "PrincipalInternationalMachineLearningPlatformReliabilityAndGovernanceEngineeringLead".repeat(4);
const LONG_EXPLANATION =
  "EvidenceGroundedRecommendationWithAnIntentionallyUnbrokenEnglishSegment".repeat(6);
const CANONICAL_TIERS = [
  ["now_fit", "现在就投"],
  ["stretch_fit", "值得冲刺"],
  ["bridge_role", "跳板岗位"],
  ["now_fit", "Now Fit"],
  ["stretch_fit", "Stretch Fit"],
  ["bridge_role", "Bridge Role"],
] as const;

test("opaque rgb contrast helper preserves the WCAG black-on-white ratio", () => {
  expect(opaqueRgbContrastRatio("rgb(0, 0, 0)", "rgb(255, 255, 255)")).toBe(21);
});

async function installResultTable(page: Page, width: number) {
  await page.setViewportSize({ width: width + 40, height: 900 });
  await page.setContent(`
    <style>${globalSource}\n${themeSource}</style>
    <main style="width: ${width}px">
      <div class="v2-result-table-wrap">
        <table class="v2-result-table" aria-label="Job recommendations">
          <thead>
            <tr><th>#</th><th>Tier</th><th>Role</th><th>Company · Location</th><th>Corpus</th></tr>
          </thead>
          <tbody>
            <tr class="v2-result-row">
              <td>①</td><td>Now Fit</td>
              <td>
                <button class="v2-result-row-trigger"><h3 data-testid="row-title">${LONG_TITLE}</h3></button>
              </td>
              <td data-testid="company-cell">Example Company · Birmingham</td><td>Demo</td>
            </tr>
            <tr class="v2-result-detail-row">
              <td colspan="5">
                <article class="v2-job-card" data-testid="detail-card">
                  <header><h3 data-testid="detail-title">${LONG_TITLE}</h3></header>
                  <p class="v2-job-why" data-testid="detail-explanation">${LONG_EXPLANATION}</p>
                </article>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </main>
  `);
}

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

for (const width of [650, 1280, 1966]) {
  test(`long result content stays within the ${width}px table`, async ({ page }) => {
    await installResultTable(page, width);

    for (const testId of ["row-title", "detail-title", "detail-explanation", "detail-card"]) {
      const geometry = await page.getByTestId(testId).evaluate((element) => ({
        clientWidth: element.clientWidth,
        scrollWidth: element.scrollWidth,
      }));
      expect(geometry.scrollWidth, `${testId} overflowed at ${width}px`).toBeLessThanOrEqual(
        geometry.clientWidth,
      );
    }

    const [titleBox, companyBox] = await Promise.all([
      page.getByTestId("row-title").boundingBox(),
      page.getByTestId("company-cell").boundingBox(),
    ]);
    expect(titleBox).not.toBeNull();
    expect(companyBox).not.toBeNull();
    expect(titleBox!.x + titleBox!.width).toBeLessThanOrEqual(companyBox!.x);
  });
}

for (const width of [320, 375, 650, 1280]) {
  test(`localized result tiers stay inside cells at ${width}px`, async ({ page }, testInfo) => {
    await installTierTable(page, width);
    await page.screenshot({ path: testInfo.outputPath(`result-tiers-${width}.png`), fullPage: true });

    const badgeCount = await page.getByTestId("tier-badge").count();
    expect(badgeCount).toBe(CANONICAL_TIERS.length);
    for (let index = 0; index < badgeCount; index += 1) {
      const [badge, cell, jobCell] = await Promise.all([
        page.getByTestId("tier-badge").nth(index).evaluate((element) => element.getBoundingClientRect().toJSON()),
        page.getByTestId("tier-cell").nth(index).evaluate((element) => element.getBoundingClientRect().toJSON()),
        page.getByTestId("job-cell").nth(index).evaluate((element) => element.getBoundingClientRect().toJSON()),
      ]);
      expect(badge.left).toBeGreaterThanOrEqual(cell.left - 0.5);
      expect(badge.right).toBeLessThanOrEqual(cell.right + 0.5);
      expect(cell.right).toBeLessThanOrEqual(jobCell.left + 0.5);
      const computedColors = await page.getByTestId("tier-badge").nth(index).evaluate((element) => {
        const style = getComputedStyle(element);
        return { foreground: style.color, background: style.backgroundColor };
      });
      expect.soft(
        opaqueRgbContrastRatio(computedColors.foreground, computedColors.background),
        `${CANONICAL_TIERS[index][1]} badge contrast`,
      ).toBeGreaterThanOrEqual(4.5);
    }

    const documentWidth = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(documentWidth.scrollWidth).toBeLessThanOrEqual(documentWidth.clientWidth);
    if (width < 650) {
      const wrapperWidth = await page.getByTestId("tier-wrapper").evaluate((element) => ({
        scrollWidth: element.scrollWidth,
        clientWidth: element.clientWidth,
      }));
      expect(wrapperWidth.scrollWidth).toBeGreaterThan(wrapperWidth.clientWidth);
    }
  });
}

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
  const badgeWidth = await page.getByTestId("tier-badge").evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
  }));
  expect(badgeWidth.scrollWidth).toBeLessThanOrEqual(badgeWidth.clientWidth);
});

test("desktop sidebar wordmark shares the session-label left grid", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.setContent(`
    <style>${globalSource}\n${themeSource}</style>
    <aside class="v2-sidebar" style="width: 268px; height: 600px">
      <span class="v2-wordmark"><span data-testid="wordmark-text">Career Arbor</span></span>
      <button class="v2-btn primary v2-new-chat" type="button">New consultation</button>
      <ul class="v2-session-list"><li><a href="#"><span data-testid="session-text">Consultation</span></a></li></ul>
    </aside>
  `);

  const [wordmarkBox, sessionBox] = await Promise.all([
    page.getByTestId("wordmark-text").boundingBox(),
    page.getByTestId("session-text").boundingBox(),
  ]);
  expect(wordmarkBox).not.toBeNull();
  expect(sessionBox).not.toBeNull();
  expect(wordmarkBox!.x).toBe(sessionBox!.x);
});
