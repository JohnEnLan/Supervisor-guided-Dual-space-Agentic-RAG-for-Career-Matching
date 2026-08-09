import { expect, test, type Page } from "@playwright/test";

import { apiFixtures } from "../src/test/apiFixtures";

const LANGUAGE_STORAGE_KEY = "career_rag_lang_v1";
const INTRO_STORAGE_KEY = "career_rag_intro_seen_v1";
const EN_TITLE = "Career RAG Workbench";
const ZH_TITLE = "Career RAG \u7b54\u8fa9\u5de5\u4f5c\u53f0";
const ZH_TOGGLE_ARIA = "\u5f53\u524d\u8bed\u8a00\uff1a\u4e2d\u6587\uff1b\u5207\u6362\u5230 English";
const EN_TOGGLE_ARIA = "Current language: English; switch to Chinese";

test.use({ viewport: { width: 375, height: 812 } });

async function installLanguageJourneyApi(page: Page, initiallyLoggedIn = false) {
  let loggedIn = initiallyLoggedIn;

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();
    const json = (body: unknown, status = 200) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

    if (path.endsWith("/capabilities")) return json(apiFixtures.capabilities());
    if (path.endsWith("/auth/otp/request")) return json(apiFixtures.otpAccepted(), 202);
    if (path.endsWith("/auth/otp/verify")) {
      loggedIn = true;
      return json(apiFixtures.me());
    }
    if (!loggedIn) return json({ detail: "unauthorized" }, 401);
    if (path.endsWith("/me")) return json(apiFixtures.me());
    if (path.endsWith("/me/sessions")) return json(apiFixtures.sessions());
    if (path.endsWith("/auth/logout") && method === "POST") return json({});
    return json({ detail: `unmocked ${method} ${path}` }, 500);
  });
}

test("English persists through the mobile login journey and Chinese restores", async ({ page }) => {
  await installLanguageJourneyApi(page);
  await page.addInitScript((introStorageKey) => {
    localStorage.setItem(introStorageKey, "1");
  }, INTRO_STORAGE_KEY);

  await page.goto("/");
  await page.getByRole("button", { name: ZH_TOGGLE_ARIA }).click();
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/login$/);

  await page.getByLabel("Email address").fill("student@example.com");
  await page.getByRole("button", { name: "Send code" }).click();
  await page.getByLabel("Verification code").fill("123456");
  await page.getByRole("button", { name: "Sign in / Register" }).click();

  await expect(page).toHaveURL(/\/app$/);
  await expect(page).toHaveTitle(EN_TITLE);
  await page.reload();
  await expect(page).toHaveURL(/\/app$/);
  await expect(page).toHaveTitle(EN_TITLE);

  const mobileNavigation = page.locator(".v2-mobile-nav");
  await expect(mobileNavigation.getByRole("button", { name: EN_TOGGLE_ARIA })).toBeVisible();
  await mobileNavigation.getByRole("button", { name: EN_TOGGLE_ARIA }).click();
  await expect(page).toHaveTitle(ZH_TITLE);
});

test("invalid stored language falls back to Chinese", async ({ page }) => {
  await installLanguageJourneyApi(page);
  await page.addInitScript(
    ({ introStorageKey, languageStorageKey }) => {
      localStorage.setItem(introStorageKey, "1");
      localStorage.setItem(languageStorageKey, "unsupported-language");
    },
    { introStorageKey: INTRO_STORAGE_KEY, languageStorageKey: LANGUAGE_STORAGE_KEY },
  );

  await page.goto("/");

  await expect(page).toHaveTitle(ZH_TITLE);
  await expect(page.locator("html")).toHaveAttribute("lang", "zh-CN");
  await expect(page.getByRole("button", { name: ZH_TOGGLE_ARIA })).toBeVisible();
});

test("desktop language toggle and English notice do not overlap", async ({ page }) => {
  await page.setViewportSize({ width: 901, height: 812 });
  await installLanguageJourneyApi(page, true);
  await page.addInitScript(
    ({ introStorageKey, languageStorageKey }) => {
      localStorage.setItem(introStorageKey, "1");
      localStorage.setItem(languageStorageKey, "en");
    },
    { introStorageKey: INTRO_STORAGE_KEY, languageStorageKey: LANGUAGE_STORAGE_KEY },
  );

  await page.goto("/app");

  const toggle = page.locator("button.v2-lang-float");
  const notice = page.getByText("Some generated or data-dependent conversation content may remain in Chinese.");
  await expect(toggle).toBeVisible();
  await expect(toggle).toHaveAccessibleName(EN_TOGGLE_ARIA);
  await expect(notice).toBeVisible();

  const [toggleBox, noticeBox] = await Promise.all([toggle.boundingBox(), notice.boundingBox()]);
  if (!toggleBox || !noticeBox) throw new Error("visible language controls must have bounding boxes");

  const intersects = !(
    toggleBox.x + toggleBox.width <= noticeBox.x ||
    noticeBox.x + noticeBox.width <= toggleBox.x ||
    toggleBox.y + toggleBox.height <= noticeBox.y ||
    noticeBox.y + noticeBox.height <= toggleBox.y
  );
  expect(intersects).toBe(false);
});
