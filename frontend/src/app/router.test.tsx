import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RouterProvider } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/queries";
import { router } from "./router";

beforeEach(async () => {
  localStorage.clear();
  vi.restoreAllMocks();
  vi.spyOn(api, "me").mockResolvedValue({
    user_id: "user-1",
    status: "active",
    is_admin: false,
    display_name: "测试用户",
    created_at: "2026-08-06T10:00:00Z",
  });
  vi.spyOn(api, "meSessions").mockResolvedValue({
    sessions: [],
    page: 1,
    page_size: 30,
    has_more: false,
  });
  vi.spyOn(api, "createSession").mockResolvedValue({
    session_id: "sess-empty-start",
    status: "awaiting_resume",
  });
  await router.navigate("/app");
});

describe("home gate (B1 R7)", () => {
  it("redirects first-time visitors from / to /welcome", async () => {
    const { resetIntroSeenForTests } = await import("../v2/introSeen");
    resetIntroSeenForTests();
    localStorage.clear();
    await router.navigate("/");
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(router.state.location.pathname).toBe("/welcome"));
  });

  it("keeps returning visitors on the homepage", async () => {
    const { INTRO_SEEN_KEY, resetIntroSeenForTests } = await import("../v2/introSeen");
    resetIntroSeenForTests();
    localStorage.setItem(INTRO_SEEN_KEY, "1");
    await router.navigate("/");
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(router.state.location.pathname).toBe("/"));
    expect(await screen.findByRole("region", { name: "功能陈列" })).toBeVisible();
  });
});

describe("empty workbench", () => {
  it("offers three onboarding steps and a primary create-session action", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );

    const guide = await screen.findByRole("region", { name: "开始咨询" });
    expect(within(guide).getAllByRole("listitem")).toHaveLength(3);
    await user.click(within(guide).getByRole("button", { name: "开始新的咨询" }));

    await waitFor(() => expect(api.createSession).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(router.state.location.pathname).toBe("/app/sessions/sess-empty-start"));
  });
});
