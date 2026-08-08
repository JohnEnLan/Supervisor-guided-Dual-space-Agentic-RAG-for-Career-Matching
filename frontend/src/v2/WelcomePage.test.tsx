import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
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
  it("marks the intro as seen and continues to the homepage from the final CTA", async () => {
    // B1 R7：介绍页出口 → 首页（P1），不再直达登录
    const user = userEvent.setup();
    const router = renderWelcome();
    await user.click(screen.getByRole("button", { name: "进入 Career RAG" }));
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
    // B1 R7：写失败浏览器由内存旗标兜底，绝不陷入 `/`↔`/welcome` 循环
    const user = userEvent.setup();
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("storage disabled");
    });
    const router = renderWelcome();
    await user.click(screen.getByRole("button", { name: "进入 Career RAG" }));
    const { hasSeenIntro } = await import("./introSeen");
    expect(hasSeenIntro()).toBe(true);
    expect(router.state.location.pathname).toBe("/");
  });
});
