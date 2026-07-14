import { expect, test } from "@playwright/test";

test("keeps onboarding isolated from business APIs and skips to the workspace", async ({
  page,
}) => {
  let apiCalls = 0;
  await page.route("**/api/v1/**", async (route) => {
    apiCalls += 1;
    await route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "business API is unavailable in onboarding" }),
    });
  });

  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: /有证据的职业决策/ }),
  ).toBeVisible();
  expect(apiCalls).toBe(0);

  await page.getByRole("link", { name: "跳过介绍" }).click();
  await expect(page).toHaveURL(/\/workspace$/);
  await expect(
    page.getByRole("heading", { name: "先从一份真实简历开始" }),
  ).toBeVisible();
});

test("orchestrates one responsive motion and restarts on refresh", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.goto("/");

  const visual = page.locator(".intro-visual");
  await expect(visual).toBeVisible();
  expect(
    await visual.evaluate((element) => getComputedStyle(element).animationName),
  ).not.toBe("none");
  const firstAnimationStartedAt = await visual.evaluate(
    (element) => element.getAnimations()[0]?.startTime ?? -1,
  );

  await page.getByRole("button", { name: "了解它如何工作" }).click();
  await expect(
    page.getByRole("heading", { name: /Agent 协作/ }),
  ).toBeFocused();
  await expect
    .poll(() =>
      visual.evaluate((element) => element.getAnimations()[0]?.startTime ?? -1),
    )
    .toBeGreaterThan(firstAnimationStartedAt);
  await page.reload();
  await expect(
    page.getByRole("heading", { name: /有证据的职业决策/ }),
  ).toBeVisible();

  for (const width of [375, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
      ),
    ).toBe(false);
  }

  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.reload();
  expect(
    await visual.evaluate((element) => getComputedStyle(element).animationDuration),
  ).toBe("0s");
});
