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

beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
  vi.spyOn(api, "me").mockRejectedValue(new ApiError(401, "unauthorized"));
});

describe("WelcomePage", () => {
  it("marks the intro as seen and continues to login from the final CTA", async () => {
    const user = userEvent.setup();
    const router = renderWelcome();
    await user.click(screen.getByRole("button", { name: "开始使用" }));
    expect(router.state.location.pathname).toBe("/login");
    expect(localStorage.getItem(INTRO_SEEN_KEY)).toBe("1");
  });

  it("offers a skip control that also exits to login", async () => {
    const user = userEvent.setup();
    const router = renderWelcome();
    await user.click(screen.getByRole("button", { name: "跳过介绍 →" }));
    expect(router.state.location.pathname).toBe("/login");
    expect(localStorage.getItem(INTRO_SEEN_KEY)).toBe("1");
  });
});
