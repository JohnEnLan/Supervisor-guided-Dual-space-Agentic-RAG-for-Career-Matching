import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiRequest } from "../api/client";
import { api } from "../api/queries";
import { AppShell } from "./AppShell";

function renderShell() {
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
  // 真实契约是 204 无响应体，apiRequest 对 204 返回 undefined
  vi.spyOn(api, "logout").mockResolvedValue(undefined);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const router = createMemoryRouter(
    [
      {
        path: "/app",
        element: <AppShell />,
        children: [{ index: true, element: <p>工作台首页</p> }],
      },
      { path: "/", element: <p>登录页</p> },
    ],
    { initialEntries: ["/app"] },
  );
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("AppShell local run privacy", () => {
  it("clears the signed-in user's stored runs on logout", async () => {
    const user = userEvent.setup();
    localStorage.setItem("last_run:user-1:sess-1", "run-1");
    localStorage.setItem("last_run:user-2:sess-2", "run-2");
    renderShell();

    await screen.findByText("测试用户");
    await user.click(screen.getByRole("button", { name: "退出登录" }));

    await waitFor(() => expect(localStorage.getItem("last_run:user-1:sess-1")).toBeNull());
    expect(localStorage.getItem("last_run:user-2:sess-2")).toBe("run-2");
  });

  it("clears the signed-in user's stored runs at the shared 401 boundary", async () => {
    localStorage.setItem("last_run:user-1:sess-1", "run-1");
    localStorage.setItem("last_run:user-2:sess-2", "run-2");
    renderShell();
    await screen.findByText("测试用户");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "expired" }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(apiRequest("/expired")).rejects.toMatchObject({ status: 401 });

    await waitFor(() => expect(localStorage.getItem("last_run:user-1:sess-1")).toBeNull());
    expect(localStorage.getItem("last_run:user-2:sess-2")).toBe("run-2");
  });
});
