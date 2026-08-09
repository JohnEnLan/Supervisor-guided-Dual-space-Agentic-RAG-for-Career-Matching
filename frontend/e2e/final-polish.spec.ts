import { expect, test, type Page } from "@playwright/test";

import { apiFixtures } from "../src/test/apiFixtures";

async function installUnauthorizedApi(page: Page) {
  await page.route("**/api/v1/**", (route) =>
    route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({ detail: "unauthorized" }),
    }),
  );
}

async function openWelcome(page: Page) {
  await installUnauthorizedApi(page);
  await page.goto("/welcome");
  await page.locator(".wl-advisor-system").scrollIntoViewIfNeeded();
}

async function installAuthenticatedShellApi(page: Page) {
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    const body = path.endsWith("/me/sessions")
      ? apiFixtures.sessions()
      : path.endsWith("/me")
        ? apiFixtures.me()
        : { detail: `unmocked ${path}` };
    return route.fulfill({
      status: path.endsWith("/me") || path.endsWith("/me/sessions") ? 200 : 500,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });
}

test("advisor system places the supervisor over all three business stages", async ({ page }) => {
  await openWelcome(page);

  const supervisor = page.locator(".wl-supervisor-card");
  const stages = page.locator(".wl-team-flow > li");
  const bus = page.locator(".wl-supervision-bus");
  const branches = page.locator(".wl-supervision-bus > span");
  await expect(supervisor).toBeVisible();
  await expect(stages).toHaveCount(3);
  await expect(bus).toBeVisible();
  await expect(branches).toHaveCount(3);

  const supervisorBox = await supervisor.boundingBox();
  const busBox = await bus.boundingBox();
  const stageBoxes = await stages.evaluateAll((items) =>
    items.map((item) => {
      const box = item.getBoundingClientRect();
      return { x: box.x, y: box.y, width: box.width, height: box.height };
    }),
  );
  const branchBoxes = await branches.evaluateAll((items) =>
    items.map((item) => {
      const box = item.getBoundingClientRect();
      return { x: box.x, width: box.width };
    }),
  );
  const relationshipStyles = await bus.evaluate((item) => {
    const supervisorLine = getComputedStyle(item, "::before");
    const horizontalLine = getComputedStyle(item, "::after");
    return {
      supervisorLine: {
        content: supervisorLine.content,
        left: supervisorLine.left,
        width: supervisorLine.borderLeftWidth,
        style: supervisorLine.borderLeftStyle,
      },
      horizontalLine: {
        content: horizontalLine.content,
        width: horizontalLine.borderTopWidth,
        style: horizontalLine.borderTopStyle,
      },
    };
  });
  const contrastRatios = await page.locator(".wl-advisor-system").evaluate((system) => {
    const rgb = (value: string) =>
      (value.match(/[\d.]+/g) ?? []).slice(0, 3).map((channel) => Number(channel) / 255);
    const luminance = (value: string) => {
      const linear = rgb(value).map((channel) =>
        channel <= 0.03928
          ? channel / 12.92
          : ((channel + 0.055) / 1.055) ** 2.4,
      );
      return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
    };
    const contrast = (foreground: string, background: string) => {
      const values = [luminance(foreground), luminance(background)].sort(
        (left, right) => right - left,
      );
      return (values[0] + 0.05) / (values[1] + 0.05);
    };
    const supervisorCard = system.querySelector<HTMLElement>(".wl-supervisor-card")!;
    const supervisorLabel = supervisorCard.querySelector<HTMLElement>(".wl-team-stage")!;
    const businessCard = system.querySelector<HTMLElement>(".wl-team-flow .wl-team-card")!;
    const businessLabel = businessCard.querySelector<HTMLElement>(".wl-team-stage")!;
    const busElement = system.querySelector<HTMLElement>(".wl-supervision-bus")!;
    const scene = system.closest<HTMLElement>(".wl-dark")!;
    return {
      supervisorLabel: contrast(
        getComputedStyle(supervisorLabel).color,
        getComputedStyle(supervisorCard).backgroundColor,
      ),
      businessLabel: contrast(
        getComputedStyle(businessLabel).color,
        getComputedStyle(businessCard).backgroundColor,
      ),
      relationship: contrast(
        getComputedStyle(busElement, "::before").borderLeftColor,
        getComputedStyle(scene).backgroundColor,
      ),
    };
  });
  expect(supervisorBox).not.toBeNull();
  expect(busBox).not.toBeNull();
  for (const stageBox of stageBoxes) {
    expect(supervisorBox!.y + supervisorBox!.height).toBeLessThan(stageBox.y);
  }
  expect(relationshipStyles.supervisorLine.content).not.toBe("none");
  expect(relationshipStyles.supervisorLine.width).toBe("1px");
  expect(relationshipStyles.supervisorLine.style).toBe("solid");
  expect(relationshipStyles.horizontalLine.content).not.toBe("none");
  expect(relationshipStyles.horizontalLine.width).toBe("1px");
  expect(relationshipStyles.horizontalLine.style).toBe("solid");
  expect(contrastRatios.supervisorLabel).toBeGreaterThanOrEqual(4.5);
  expect(contrastRatios.businessLabel).toBeGreaterThanOrEqual(4.5);
  expect(contrastRatios.relationship).toBeGreaterThanOrEqual(3);
  const supervisorCenter = supervisorBox!.x + supervisorBox!.width / 2;
  const supervisorLineCenter =
    busBox!.x +
    Number.parseFloat(relationshipStyles.supervisorLine.left) +
    Number.parseFloat(relationshipStyles.supervisorLine.width) / 2;
  expect(Math.abs(supervisorLineCenter - supervisorCenter)).toBeLessThanOrEqual(1.5);
  const firstCenter = stageBoxes[0].x + stageBoxes[0].width / 2;
  const lastCenter = stageBoxes[2].x + stageBoxes[2].width / 2;
  expect(busBox!.x).toBeLessThanOrEqual(firstCenter);
  expect(busBox!.x + busBox!.width).toBeGreaterThanOrEqual(lastCenter);
  for (const [index, branchBox] of branchBoxes.entries()) {
    const branchCenter = branchBox.x + branchBox.width / 2;
    const stageCenter = stageBoxes[index].x + stageBoxes[index].width / 2;
    expect(Math.abs(branchCenter - stageCenter)).toBeLessThanOrEqual(1.5);
  }
});

test("advisor system becomes a vertical, overflow-free handoff at 375px", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await openWelcome(page);

  const orderedCards = page.locator(
    ".wl-supervisor-card, .wl-team-flow > li:nth-child(1), .wl-team-flow > li:nth-child(2), .wl-team-flow > li:nth-child(3)",
  );
  await expect(orderedCards).toHaveCount(4);
  const cardBoxes = await orderedCards.evaluateAll((items) =>
    items.map((item) => {
      const box = item.getBoundingClientRect();
      return { y: box.y, height: box.height };
    }),
  );
  for (let index = 1; index < cardBoxes.length; index += 1) {
    expect(cardBoxes[index - 1].y + cardBoxes[index - 1].height).toBeLessThan(
      cardBoxes[index].y,
    );
  }
  const mobileConnectors = await page.locator(".wl-advisor-system").evaluate((system) => {
    const busStyle = getComputedStyle(system.querySelector(".wl-supervision-bus")!);
    const arrows = Array.from(system.querySelectorAll(".wl-team-flow > li")).slice(0, 2);
    return {
      bus: { width: busStyle.width, height: busStyle.height, background: busStyle.backgroundColor },
      arrows: arrows.map((item) => getComputedStyle(item, "::after").content),
    };
  });
  expect(mobileConnectors.bus.width).toBe("1px");
  expect(mobileConnectors.bus.height).toBe("30px");
  expect(mobileConnectors.bus.background).not.toBe("rgba(0, 0, 0, 0)");
  for (const arrow of mobileConnectors.arrows) expect(arrow).not.toBe("none");
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      ),
    )
    .toBe(true);
});

test("localized welcome brand returns to the homepage without an intro loop", async ({ page }) => {
  await installUnauthorizedApi(page);
  await page.goto("/welcome");

  const chineseBrand = page.getByRole("link", { name: "枝涯" });
  await expect(chineseBrand).toHaveAttribute("href", "/");
  await chineseBrand.click();

  await expect(page).toHaveURL(/\/$/);
  await expect(
    page.getByRole("heading", { name: /把求职这件事，\s*交给一支为你服务的团队/ }),
  ).toBeVisible();
  await expect
    .poll(() => page.evaluate(() => localStorage.getItem("career_rag_intro_seen_v1")))
    .toBe("1");

  await page.getByRole("button", { name: "当前语言：中文；切换到 English" }).click();
  await expect(page.getByRole("link", { name: "Career Arbor" })).toHaveAttribute("href", "/");
});

test("brand reaches home from a direct login entry with no intro flag", async ({ page }) => {
  await installUnauthorizedApi(page);
  await page.goto("/login");
  await page.evaluate(() => localStorage.removeItem("career_rag_intro_seen_v1"));
  await page.getByRole("button", { name: "当前语言：中文；切换到 English" }).click();

  await page.getByRole("link", { name: "Career Arbor" }).click();

  await expect(page).toHaveURL(/\/$/);
  await expect(
    page.getByRole("heading", {
      name: /Put your job search\s*in the hands of a team built around you/,
    }),
  ).toBeVisible();
});

test("brand reaches home from an authenticated app entry with no intro flag", async ({ page }) => {
  await page.addInitScript(() => localStorage.removeItem("career_rag_intro_seen_v1"));
  await installAuthenticatedShellApi(page);
  await page.goto("/app");

  await page.locator(".v2-sidebar").getByRole("link", { name: "枝涯" }).click();

  await expect(page).toHaveURL(/\/$/);
  await expect(
    page.getByRole("heading", { name: /把求职这件事，\s*交给一支为你服务的团队/ }),
  ).toBeVisible();
});

test("new consultation action aligns with the session rows", async ({ page }) => {
  await installAuthenticatedShellApi(page);
  await page.goto("/app");

  const newConsultation = page.getByRole("button", { name: "新的咨询", exact: true });
  const firstSession = page.locator(".v2-session-list a").first();
  await expect(newConsultation).toBeVisible();
  await expect(firstSession).toBeVisible();

  const boxes = await page.locator(".v2-sidebar").evaluate((element) => {
    const action = element.querySelector<HTMLElement>(".v2-new-chat")!.getBoundingClientRect();
    const session = element
      .querySelector<HTMLElement>(".v2-session-list a")!
      .getBoundingClientRect();
    return {
      action: { x: action.x, width: action.width },
      session: { x: session.x, width: session.width },
    };
  });
  expect(Math.abs(boxes.action.x - boxes.session.x)).toBeLessThanOrEqual(0.5);
  expect(Math.abs(boxes.action.width - boxes.session.width)).toBeLessThanOrEqual(0.5);
});

test("mobile drawer keeps the new consultation action aligned with session rows", async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await installAuthenticatedShellApi(page);
  await page.goto("/app");
  await page.getByRole("button", { name: "打开导航" }).click();

  const drawer = page.getByRole("dialog", { name: "主导航" });
  const newConsultation = drawer.getByRole("button", { name: "新的咨询", exact: true });
  const firstSession = drawer.locator(".v2-session-list a").first();
  await expect(newConsultation).toBeVisible();
  await expect(firstSession).toBeVisible();

  const boxes = await drawer.evaluate((element) => {
    const action = element.querySelector<HTMLElement>(".v2-new-chat")!.getBoundingClientRect();
    const session = element
      .querySelector<HTMLElement>(".v2-session-list a")!
      .getBoundingClientRect();
    return {
      action: { x: action.x, width: action.width },
      session: { x: session.x, width: session.width },
    };
  });
  expect(Math.abs(boxes.action.x - boxes.session.x)).toBeLessThanOrEqual(0.5);
  expect(Math.abs(boxes.action.width - boxes.session.width)).toBeLessThanOrEqual(0.5);
});
