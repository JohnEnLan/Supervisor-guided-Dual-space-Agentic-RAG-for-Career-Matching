import { expect, test } from "@playwright/test";

test("keeps the seven-scene expedition isolated from business APIs", async ({
  page,
}) => {
  let apiCalls = 0;
  await page.route("**/api/v1/**", async (route) => {
    apiCalls += 1;
    await route.fulfill({
      status: 503,
      contentType: "application/json",
      body: "{}",
    });
  });

  await page.goto("/");
  await expect(
    page.getByRole("heading", { level: 1, name: "职业远征" }),
  ).toBeVisible();
  await expect(page.getByRole("region")).toHaveCount(7);
  expect(apiCalls).toBe(0);
  expect(
    await page.evaluate(() => localStorage.length + sessionStorage.length),
  ).toBe(0);
  await expect(page.getByRole("link", { name: "跳过远征" })).toBeVisible();
});

test("advances the constellation and chapter rail through real scrolling", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await page.locator("#scene-fleet").scrollIntoViewIfNeeded();

  await expect(page.locator('a[href="#scene-fleet"]')).toHaveAttribute(
    "aria-current",
    "step",
  );
  await expect(page.locator(".career-constellation")).toHaveAttribute(
    "data-chapter",
    "5",
  );
  const constellationPosition = await page
    .locator(".career-constellation")
    .evaluate((node) => {
      const rect = node.getBoundingClientRect();
      return { top: rect.top, bottom: rect.bottom };
    });
  expect(constellationPosition.top).toBeGreaterThanOrEqual(0);
  expect(constellationPosition.bottom).toBeLessThanOrEqual(900);
});

test("renders a bounded desktop comet and disables it for reduced motion", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.goto("/");
  await expect(page.locator(".pointer-comet-particle")).toHaveCount(18);

  for (let index = 0; index < 80; index += 1) {
    await page.mouse.move(180 + index * 6, 180 + (index % 12) * 8);
  }

  await expect
    .poll(() =>
      page
        .locator(".pointer-comet-particle")
        .first()
        .evaluate((node) => Number(getComputedStyle(node).opacity)),
    )
    .toBeGreaterThan(0);
  await expect(page.locator(".pointer-comet-particle")).toHaveCount(18);

  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.reload();
  await expect(page.getByTestId("pointer-comet")).toBeHidden();
  await expect(page.locator(".route-active")).toHaveCSS(
    "stroke-dashoffset",
    "0px",
  );
});

test("keeps the cinematic route responsive and preserves the workspace exit", async ({
  page,
}) => {
  await page.goto("/");

  for (const width of [375, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(
        () =>
          document.documentElement.scrollWidth <=
          document.documentElement.clientWidth,
      ),
    ).toBe(true);
  }

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.reload();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "跳过远征" })).toBeFocused();
  await page.getByRole("link", { name: "跳过远征" }).click();
  await expect(page).toHaveURL(/\/workspace$/);
  await expect(
    page.getByRole("heading", { name: "先从一份真实简历开始" }),
  ).toBeVisible();
});
