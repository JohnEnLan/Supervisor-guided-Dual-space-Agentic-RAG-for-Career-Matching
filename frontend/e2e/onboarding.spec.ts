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
