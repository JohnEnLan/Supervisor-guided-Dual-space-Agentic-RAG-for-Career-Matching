import { expect, test, type Locator, type Page } from "@playwright/test";

import { apiFixtures } from "../src/test/apiFixtures";
import { opaqueRgbContrastRatio } from "./color-contrast";

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

async function wordmarkFeedback(brand: Locator) {
  return brand.evaluate((element) => {
    const branch = getComputedStyle(element, "::after");
    const leaf = getComputedStyle(element, "::before");
    const branchTransform = branch.transform;
    return {
      branchScaleX: branchTransform === "none" ? null : new DOMMatrixReadOnly(branchTransform).a,
      leafOpacity: Number.parseFloat(leaf.opacity),
      branchTransition: {
        duration: branch.transitionDuration,
        properties: branch.transitionProperty.split(",").map((property) => property.trim()).sort(),
      },
      leafTransition: {
        duration: leaf.transitionDuration,
        properties: leaf.transitionProperty.split(",").map((property) => property.trim()).sort(),
      },
    };
  });
}

function expectBrandFeedbackTransition(feedback: Awaited<ReturnType<typeof wordmarkFeedback>>) {
  expect(feedback.branchTransition.duration).toBe("0.22s, 0.22s");
  expect(feedback.leafTransition.duration).toBe("0.22s, 0.22s");
  expect(feedback.branchTransition.properties).toEqual(["opacity", "transform"]);
  expect(feedback.leafTransition.properties).toEqual(["opacity", "transform"]);
}

type Rect = { left: number; right: number; top: number; bottom: number; width: number; height: number };
type BrandMeasurements = {
  slogan: number;
  name: number;
  heading: number;
  headingCount: number;
  scrollWidth: number;
  clientWidth: number;
  lockup: Pick<Rect, "left" | "right" | "top" | "bottom">;
  nav: Rect;
  wordmark: Rect;
  actions: Rect;
  horizontalSeparation: number;
  verticalSeparation: number;
  viewport: { width: number; height: number };
};

async function measureHomepageBrand(page: Page): Promise<BrandMeasurements> {
  return page.evaluate(() => {
    const lockup = document.querySelector<HTMLElement>(".mk-brand-lockup")!;
    const slogan = document.querySelector<HTMLElement>(".mk-brand-slogan")!;
    const name = document.querySelector<HTMLElement>(".mk-brand-name")!;
    const heading = document.querySelector<HTMLElement>(".mk-hero h1")!;
    const nav = document.querySelector<HTMLElement>(".v2-topnav")!;
    const wordmark = nav.querySelector<HTMLElement>(".v2-wordmark")!;
    const actions = nav.querySelector<HTMLElement>(".v2-topnav-actions")!;
    const lockupBox = lockup.getBoundingClientRect();
    const toRect = (element: HTMLElement) => {
      const rect = element.getBoundingClientRect();
      return { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom, width: rect.width, height: rect.height };
    };
    const navBox = toRect(nav);
    const wordmarkBox = toRect(wordmark);
    const actionsBox = toRect(actions);
    return {
      slogan: Number.parseFloat(getComputedStyle(slogan).fontSize),
      name: Number.parseFloat(getComputedStyle(name).fontSize),
      heading: Number.parseFloat(getComputedStyle(heading).fontSize),
      headingCount: document.querySelectorAll("h1").length,
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
      lockup: { left: lockupBox.left, right: lockupBox.right, top: lockupBox.top, bottom: lockupBox.bottom },
      nav: navBox,
      wordmark: wordmarkBox,
      actions: actionsBox,
      horizontalSeparation: Math.max(wordmarkBox.left - actionsBox.right, actionsBox.left - wordmarkBox.right),
      verticalSeparation: Math.max(wordmarkBox.top - actionsBox.bottom, actionsBox.top - wordmarkBox.bottom),
      viewport: { width: window.innerWidth, height: window.innerHeight },
    };
  });
}

function rectangleIsInside(outer: Pick<Rect, "left" | "right" | "top" | "bottom">, inner: Pick<Rect, "left" | "right" | "top" | "bottom">) {
  return inner.left >= outer.left && inner.right <= outer.right && inner.top >= outer.top && inner.bottom <= outer.bottom;
}

function assertHomepageBrandHierarchy(measurements: BrandMeasurements) {
  const insideViewport = (box: Pick<Rect, "left" | "right" | "top" | "bottom">) =>
    box.left >= 0 && box.right <= measurements.viewport.width && box.top >= 0 && box.bottom <= measurements.viewport.height;
  expect(measurements.slogan).toBeLessThan(measurements.name);
  expect(measurements.name).toBeLessThan(measurements.heading);
  expect(measurements.headingCount).toBe(1);
  expect(measurements.scrollWidth).toBeLessThanOrEqual(measurements.clientWidth);
  expect(rectangleIsInside({ left: 0, right: measurements.viewport.width, top: 0, bottom: measurements.viewport.height }, measurements.lockup)).toBe(true);
  return {
    separated: measurements.horizontalSeparation >= 4 || measurements.verticalSeparation >= 4,
    insideNav: [measurements.wordmark, measurements.actions].every((item) => rectangleIsInside(measurements.nav, item)),
    insideViewport: [measurements.wordmark, measurements.actions].every(insideViewport),
  };
}

function expectPureFixedLeafRotation(transform: string) {
  const values = transform.match(/^matrix\(([^)]+)\)$/)?.[1].split(",").map(Number);
  expect(values).toHaveLength(6);
  const [cosine, sine, negativeSine, cosineAgain, translateX, translateY] = values!;
  const angle = (-30 * Math.PI) / 180;
  expect(cosine).toBeCloseTo(Math.cos(angle), 5);
  expect(sine).toBeCloseTo(Math.sin(angle), 5);
  expect(negativeSine).toBeCloseTo(-Math.sin(angle), 5);
  expect(cosineAgain).toBeCloseTo(Math.cos(angle), 5);
  expect(translateX).toBeCloseTo(0, 5);
  expect(translateY).toBeCloseTo(0, 5);
}

async function wordmarkFontSizeInRem(brand: Locator) {
  return brand.evaluate((element) => {
    const rootFontSize = Number.parseFloat(getComputedStyle(document.documentElement).fontSize);
    return Number.parseFloat(getComputedStyle(element).fontSize) / rootFontSize;
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
  const contrastColors = await page.locator(".wl-advisor-system").evaluate((system) => {
    const supervisorCard = system.querySelector<HTMLElement>(".wl-supervisor-card")!;
    const supervisorLabel = supervisorCard.querySelector<HTMLElement>(".wl-team-stage")!;
    const businessCard = system.querySelector<HTMLElement>(".wl-team-flow .wl-team-card")!;
    const businessLabel = businessCard.querySelector<HTMLElement>(".wl-team-stage")!;
    const busElement = system.querySelector<HTMLElement>(".wl-supervision-bus")!;
    const scene = system.closest<HTMLElement>(".wl-dark")!;
    return {
      supervisorLabel: [getComputedStyle(supervisorLabel).color, getComputedStyle(supervisorCard).backgroundColor],
      businessLabel: [getComputedStyle(businessLabel).color, getComputedStyle(businessCard).backgroundColor],
      relationship: [getComputedStyle(busElement, "::before").borderLeftColor, getComputedStyle(scene).backgroundColor],
    };
  });
  const contrastRatios = {
    supervisorLabel: opaqueRgbContrastRatio(
      contrastColors.supervisorLabel[0],
      contrastColors.supervisorLabel[1],
    ),
    businessLabel: opaqueRgbContrastRatio(
      contrastColors.businessLabel[0],
      contrastColors.businessLabel[1],
    ),
    relationship: opaqueRgbContrastRatio(
      contrastColors.relationship[0],
      contrastColors.relationship[1],
    ),
  };
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

test("homepage brand lockup keeps its hierarchy and bounds in both languages", async ({
  page,
}, testInfo) => {
  await page.addInitScript(() => {
    localStorage.setItem("career_rag_intro_seen_v1", "1");
  });
  await installUnauthorizedApi(page);
  await page.goto("/");

  const navViolations: Array<{ width: number; language: "zh" | "en"; details: unknown }> = [];

  for (const width of [320, 375, 650, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await page.evaluate(() => localStorage.setItem("career_rag_lang_v1", "zh"));
    await page.reload();

    await expect(page.locator(".mk-hero h1")).toBeVisible();
    const chineseMeasurements = await measureHomepageBrand(page);
    const chineseNav = assertHomepageBrandHierarchy(chineseMeasurements);
    if (!chineseNav.separated || !chineseNav.insideNav || !chineseNav.insideViewport) {
      navViolations.push({ width, language: "zh", details: chineseNav });
    }
    await page.screenshot({
      path: testInfo.outputPath(`home-${width}-zh.png`),
      fullPage: true,
    });

    await page.locator(".v2-language-toggle").click();
    await expect(page.locator("html")).toHaveAttribute("lang", "en");
    const englishMeasurements = await measureHomepageBrand(page);
    const englishNav = assertHomepageBrandHierarchy(englishMeasurements);
    if (!englishNav.separated || !englishNav.insideNav || !englishNav.insideViewport) {
      navViolations.push({ width, language: "en", details: englishNav });
    }
    await page.screenshot({
      path: testInfo.outputPath(`home-${width}-en.png`),
      fullPage: true,
    });
  }

  expect(navViolations, JSON.stringify(navViolations)).toEqual([]);
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

test("brand wordmark keeps its responsive type and 44px target", async ({ page }) => {
  await installUnauthorizedApi(page);
  await page.setViewportSize({ width: 320, height: 812 });
  await page.goto("/welcome");

  const brand = page.getByRole("link", { name: "枝涯" });
  const narrowFontSize = await wordmarkFontSizeInRem(brand);
  expect(narrowFontSize).toBeGreaterThanOrEqual(1.45);
  expect(narrowFontSize).toBeLessThanOrEqual(1.8);

  await page.setViewportSize({ width: 1280, height: 900 });
  const desktopFontSize = await wordmarkFontSizeInRem(brand);
  expect(desktopFontSize).toBeGreaterThanOrEqual(1.45);
  expect(desktopFontSize).toBeLessThanOrEqual(1.8);
  expect(desktopFontSize).toBeGreaterThan(narrowFontSize);

  const target = await brand.boundingBox();
  expect(target).not.toBeNull();
  expect(target!.height).toBeGreaterThanOrEqual(44);

});

test("brand wordmark pointer feedback grows without moving navigation layout", async ({ page }) => {
  await installUnauthorizedApi(page);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/welcome");
  const brand = page.locator(".wl-page .v2-wordmark");

  const idle = await wordmarkFeedback(brand);
  expect(idle.branchScaleX).not.toBeNull();
  expect(idle.branchScaleX!).toBeLessThanOrEqual(0.35);
  expect(idle.leafOpacity).toBe(0);
  expectBrandFeedbackTransition(idle);
  await brand.hover();
  await expect.poll(() => wordmarkFeedback(brand).then(({ branchScaleX }) => branchScaleX)).toBe(1);
  await expect.poll(() => wordmarkFeedback(brand).then(({ leafOpacity }) => leafOpacity)).toBe(1);
  const hover = await wordmarkFeedback(brand);
  expect(hover.branchScaleX).toBe(1);
  expect(hover.leafOpacity).toBe(1);
  expect(hover.branchScaleX! - idle.branchScaleX!).toBeGreaterThanOrEqual(0.6);
  expectBrandFeedbackTransition(hover);

  const layoutBeforePress = await brand.evaluate((element) => {
    const nav = element.closest("nav")!.getBoundingClientRect();
    const actions = element.closest("nav")!.querySelector<HTMLElement>(".wl-topbar-actions")!
      .getBoundingClientRect();
    return {
      nav: { left: nav.left, top: nav.top, width: nav.width, height: nav.height },
      actions: { left: actions.left, top: actions.top, width: actions.width, height: actions.height },
    };
  });
  const transformBeforePress = await brand.evaluate((element) => getComputedStyle(element).transform);
  await page.mouse.down();
  const transformDuringPress = await brand.evaluate((element) => getComputedStyle(element).transform);
  expect(transformDuringPress).not.toBe(transformBeforePress);
  const layoutDuringPress = await brand.evaluate((element) => {
    const nav = element.closest("nav")!.getBoundingClientRect();
    const actions = element.closest("nav")!.querySelector<HTMLElement>(".wl-topbar-actions")!
      .getBoundingClientRect();
    return {
      nav: { left: nav.left, top: nav.top, width: nav.width, height: nav.height },
      actions: { left: actions.left, top: actions.top, width: actions.width, height: actions.height },
    };
  });
  expect(layoutDuringPress).toEqual(layoutBeforePress);
  await page.mouse.move(0, 0);
  await page.mouse.up();

});

test("brand wordmark keyboard focus preserves contrast and full feedback", async ({ page }) => {
  await installUnauthorizedApi(page);
  await page.goto("/welcome");
  const brand = page.locator(".wl-page .v2-wordmark");
  const idle = await wordmarkFeedback(brand);
  await brand.evaluate((element) => (element as HTMLElement).blur());
  await expect(page).toHaveURL(/\/welcome$/);
  await expect.poll(() => page.evaluate(() => document.activeElement === document.body)).toBe(true);
  await expect.poll(() => wordmarkFeedback(brand)).toEqual(idle);
  await page.reload();
  await page.keyboard.press("Tab");
  await expect(brand).toBeFocused();

  const focusColor = await brand.evaluate((element) => {
    const expected = getComputedStyle(document.documentElement)
      .getPropertyValue("--v2-accent-hover")
      .trim();
    const probe = document.createElement("span");
    probe.style.color = expected;
    document.body.append(probe);
    const resolved = getComputedStyle(probe).color;
    probe.remove();
    return resolved;
  });
  await expect
    .poll(() => brand.evaluate((element) => getComputedStyle(element).color))
    .toBe(focusColor);

  const focus = await brand.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      outlineStyle: style.outlineStyle,
      outlineWidth: Number.parseFloat(style.outlineWidth),
      outlineColor: style.outlineColor,
      wordmarkColor: style.color,
      backgroundColor: getComputedStyle(element.closest(".wl-page")!).backgroundColor,
    };
  });
  expect(focus.outlineStyle).toBe("solid");
  expect(focus.outlineWidth).toBeGreaterThanOrEqual(2);
  await expect.poll(() => wordmarkFeedback(brand).then(({ branchScaleX }) => branchScaleX)).toBe(1);
  await expect.poll(() => wordmarkFeedback(brand).then(({ leafOpacity }) => leafOpacity)).toBe(1);
  const focused = await wordmarkFeedback(brand);
  expect(focused.branchScaleX).toBe(1);
  expect(focused.leafOpacity).toBe(1);
  expect(opaqueRgbContrastRatio(focus.outlineColor, focus.backgroundColor)).toBeGreaterThanOrEqual(3);
  expect(opaqueRgbContrastRatio(focus.wordmarkColor, focus.backgroundColor)).toBeGreaterThanOrEqual(4.5);
});

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
      expect(boxes.brand.left - boxes.menu.right).toBeGreaterThanOrEqual(4);
      expect(boxes.language.left - boxes.brand.right).toBeGreaterThanOrEqual(4);
      expect(boxes.language.right).toBeLessThanOrEqual(width);
    };

    await assertSeparated("枝涯");
    await nav.locator(".v2-language-toggle").click();
    await assertSeparated("Career Arbor");
    if (width === 375) {
      await page.screenshot({
        path: testInfo.outputPath("mobile-app-bar-en-375.png"),
        fullPage: true,
      });
    }
  });
}

test("desktop sidebar wordmark remains inside its bounds in both languages", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await installAuthenticatedShellApi(page);
  await page.goto("/app");

  const sidebar = page.locator(".v2-sidebar");
  const assertInsideSidebar = async (brandName: string) => {
    const brand = sidebar.getByRole("link", { name: brandName });
    await expect(brand).toBeVisible();
    const [brandBox, sidebarBox] = await Promise.all([brand.boundingBox(), sidebar.boundingBox()]);
    expect(brandBox).not.toBeNull();
    expect(sidebarBox).not.toBeNull();
    expect(brandBox!.height).toBeGreaterThanOrEqual(44);
    expect(brandBox!.x).toBeGreaterThanOrEqual(sidebarBox!.x);
    expect(brandBox!.y).toBeGreaterThanOrEqual(sidebarBox!.y);
    expect(brandBox!.x + brandBox!.width).toBeLessThanOrEqual(sidebarBox!.x + sidebarBox!.width);
    expect(brandBox!.y + brandBox!.height).toBeLessThanOrEqual(sidebarBox!.y + sidebarBox!.height);
  };

  await assertInsideSidebar("枝涯");
  await page.locator(".v2-lang-float.v2-language-toggle").click();
  await assertInsideSidebar("Career Arbor");
});

test("reduced motion keeps idle, hover, and focus wordmark feedback static and visible", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await installUnauthorizedApi(page);
  await page.goto("/welcome");
  const brand = page.locator(".wl-page .v2-wordmark");
  const assertStaticFeedback = async () => {
    const styles = await brand.evaluate((element) => ({
      linkTransition: getComputedStyle(element).transitionDuration,
      branchTransition: getComputedStyle(element, "::after").transitionDuration,
      leafTransition: getComputedStyle(element, "::before").transitionDuration,
      branchOpacity: Number.parseFloat(getComputedStyle(element, "::after").opacity),
      leafOpacity: Number.parseFloat(getComputedStyle(element, "::before").opacity),
      branchTransform: getComputedStyle(element, "::after").transform,
      leafTransform: getComputedStyle(element, "::before").transform,
    }));
    expect(styles.linkTransition).toBe("0s");
    expect(styles.branchTransition).toBe("0s");
    expect(styles.leafTransition).toBe("0s");
    expect(styles.branchOpacity).toBe(1);
    expect(styles.leafOpacity).toBe(1);
    expect(styles.branchTransform).toBe("none");
    expectPureFixedLeafRotation(styles.leafTransform);
  };

  await assertStaticFeedback();
  await brand.hover();
  await assertStaticFeedback();
  await page.mouse.move(0, 0);
  await expect.poll(() => brand.evaluate((element) => element.matches(":hover"))).toBe(false);
  await page.keyboard.press("Tab");
  await expect(brand).toBeFocused();
  await assertStaticFeedback();
  expect(await brand.evaluate((element) => getComputedStyle(element).outlineStyle)).toBe("solid");
  await page.mouse.down();
  expect(await brand.evaluate((element) => getComputedStyle(element).transform)).toBe("none");
  await page.mouse.up();
});
