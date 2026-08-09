import { readFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

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
