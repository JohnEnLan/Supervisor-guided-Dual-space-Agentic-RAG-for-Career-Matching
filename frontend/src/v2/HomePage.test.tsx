import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import { api } from "../api/queries";
import { HomePage } from "./HomePage";
import { INTRO_SEEN_KEY } from "./introSeen";

function renderHome() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter([
    { path: "/", element: <HomePage /> },
    { path: "/welcome", element: <p>welcome-page</p> },
    { path: "/login", element: <p>login-page</p> },
    { path: "/app", element: <p>app-page</p> },
  ]);
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

describe("HomePage", () => {
  it("shows the feature showcase with six capability cards", async () => {
    renderHome();
    const region = await screen.findByRole("region", { name: "功能陈列" });
    expect(within(region).getAllByRole("article")).toHaveLength(6);
  });

  it("routes first-time visitors through the welcome intro", async () => {
    const user = userEvent.setup();
    const router = renderHome();
    const [primaryCta] = await screen.findAllByRole("button", { name: "进入应用" });
    await user.click(primaryCta);
    expect(router.state.location.pathname).toBe("/welcome");
  });

  it("sends returning visitors straight to login", async () => {
    localStorage.setItem(INTRO_SEEN_KEY, "1");
    const user = userEvent.setup();
    const router = renderHome();
    const [primaryCta] = await screen.findAllByRole("button", { name: "进入应用" });
    await user.click(primaryCta);
    expect(router.state.location.pathname).toBe("/login");
  });
});
