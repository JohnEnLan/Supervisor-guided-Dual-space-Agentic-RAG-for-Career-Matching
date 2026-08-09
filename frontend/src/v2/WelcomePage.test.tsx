import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import { api } from "../api/queries";
import { INTRO_SEEN_KEY } from "./introSeen";
import { WelcomePage } from "./WelcomePage";

function renderWelcome() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(
    [
      { path: "/", element: <p>home-page</p> },
      { path: "/welcome", element: <WelcomePage /> },
      { path: "/login", element: <p>login-page</p> },
      { path: "/app", element: <p>app-page</p> },
    ],
    { initialEntries: ["/welcome"] },
  );
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

beforeEach(async () => {
  localStorage.clear();
  const { resetIntroSeenForTests } = await import("./introSeen");
  resetIntroSeenForTests();
  vi.restoreAllMocks();
  vi.spyOn(api, "me").mockRejectedValue(new ApiError(401, "unauthorized"));
});

describe("WelcomePage", () => {
  it("uses the localized brand as a real homepage exit", async () => {
    const user = userEvent.setup();
    const router = renderWelcome();

    await user.click(screen.getByRole("link", { name: "枝涯" }));

    expect(router.state.location.pathname).toBe("/");
    expect(localStorage.getItem(INTRO_SEEN_KEY)).toBe("1");
  });

  it("shows PM as the supervisor over the three business-agent handoffs", () => {
    renderWelcome();

    const advisorSystem = screen.getByRole("group", {
      name: "项目经理监督需求确认、岗位检索与策略规划",
    });
    expect(within(advisorSystem).getByText("监督层")).toBeVisible();
    expect(
      within(advisorSystem).getByText("全程规划、质量核查与有界纠偏"),
    ).toBeVisible();

    const handoffFlow = within(advisorSystem).getByRole("list", {
      name: "业务顾问交接顺序",
    });
    expect(
      within(handoffFlow)
        .getAllByRole("heading", { level: 3 })
        .map((heading) => heading.textContent),
    ).toEqual(["需求顾问", "岗位顾问", "职业规划师"]);
    expect(within(handoffFlow).getAllByRole("listitem")).toHaveLength(3);
  });

  it("marks the intro as seen and continues to the homepage from the final CTA", async () => {
    // The introduction exits to the public homepage, not directly to login.
    const user = userEvent.setup();
    const router = renderWelcome();
    await user.click(screen.getByRole("button", { name: "进入枝涯" }));
    expect(router.state.location.pathname).toBe("/");
    expect(localStorage.getItem(INTRO_SEEN_KEY)).toBe("1");
  });

  it("offers a skip control that also exits to the homepage", async () => {
    const user = userEvent.setup();
    const router = renderWelcome();
    await user.click(screen.getByRole("button", { name: "跳过介绍 →" }));
    expect(router.state.location.pathname).toBe("/");
    expect(localStorage.getItem(INTRO_SEEN_KEY)).toBe("1");
  });

  it("keeps the exit working when localStorage writes fail (memory fallback)", async () => {
    // Module memory prevents a `/`↔`/welcome` loop when storage is disabled.
    const user = userEvent.setup();
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("storage disabled");
    });
    const router = renderWelcome();
    await user.click(screen.getByRole("button", { name: "进入枝涯" }));
    const { hasSeenIntro } = await import("./introSeen");
    expect(hasSeenIntro()).toBe(true);
    expect(router.state.location.pathname).toBe("/");
  });
});

describe("WelcomePage logged-in branches", () => {
  const ME = {
    user_id: "user-1",
    status: "active",
    is_admin: false,
    display_name: "测试用户",
    created_at: "2026-08-06T10:00:00Z",
  };

  it("backfills the intro flag and redirects legacy logged-in users to /app", async () => {
    vi.mocked(api.me).mockResolvedValue(ME as never);
    const router = renderWelcome();
    await waitFor(() => expect(router.state.location.pathname).toBe("/app"));
    expect(localStorage.getItem(INTRO_SEEN_KEY)).toBe("1");
  });

  it("lets logged-in users with the flag watch the intro explicitly", async () => {
    localStorage.setItem(INTRO_SEEN_KEY, "1");
    vi.mocked(api.me).mockResolvedValue(ME as never);
    const router = renderWelcome();
    expect(
      await screen.findByRole("heading", { name: "求职不该是一个人的事" }),
    ).toBeVisible();
    expect(await screen.findByRole("button", { name: "返回首页" })).toBeVisible();
    expect(router.state.location.pathname).toBe("/welcome");
  });
});
