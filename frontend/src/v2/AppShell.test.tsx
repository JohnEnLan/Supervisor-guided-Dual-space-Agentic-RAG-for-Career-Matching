import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiRequest } from "../api/client";
import { api } from "../api/queries";
import { AppShell } from "./AppShell";

function renderShell({
  sessionItems = [],
  hasMore = false,
}: {
  sessionItems?: { session_id: string; status: string; updated_at: string }[];
  hasMore?: boolean;
} = {}) {
  vi.spyOn(api, "me").mockResolvedValue({
    user_id: "user-1",
    status: "active",
    is_admin: false,
    display_name: "测试用户",
    created_at: "2026-08-06T10:00:00Z",
  });
  vi.spyOn(api, "meSessions").mockResolvedValue({
    sessions: sessionItems,
    page: 1,
    page_size: 30,
    has_more: hasMore,
  });
  vi.spyOn(api, "createSession").mockResolvedValue({
    session_id: "sess-created",
    status: "awaiting_resume",
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
    localStorage.setItem("title:user-1:sess-1", "数据工程师");
    localStorage.setItem("last_run:user-2:sess-2", "run-2");
    localStorage.setItem("title:user-2:sess-2", "后端工程师");
    renderShell();

    await screen.findByText("测试用户");
    await user.click(screen.getByRole("button", { name: "退出登录" }));

    await waitFor(() => expect(localStorage.getItem("last_run:user-1:sess-1")).toBeNull());
    expect(localStorage.getItem("title:user-1:sess-1")).toBeNull();
    expect(localStorage.getItem("last_run:user-2:sess-2")).toBe("run-2");
    expect(localStorage.getItem("title:user-2:sess-2")).toBe("后端工程师");
  });

  it("clears the signed-in user's stored runs at the shared 401 boundary", async () => {
    localStorage.setItem("last_run:user-1:sess-1", "run-1");
    localStorage.setItem("title:user-1:sess-1", "数据工程师");
    localStorage.setItem("last_run:user-2:sess-2", "run-2");
    localStorage.setItem("title:user-2:sess-2", "后端工程师");
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
    expect(localStorage.getItem("title:user-1:sess-1")).toBeNull();
    expect(localStorage.getItem("last_run:user-2:sess-2")).toBe("run-2");
    expect(localStorage.getItem("title:user-2:sess-2")).toBe("后端工程师");
  });
});

describe("AppShell navigation truth", () => {
  const sessions = [
    { session_id: "sess-1", status: "active", updated_at: "2026-08-05T09:05:00Z" },
    { session_id: "sess-2", status: "active", updated_at: "2026-08-04T09:05:00Z" },
  ];

  it("shows pagination-honest usage and local titles with an MM-DD fallback", async () => {
    localStorage.setItem("title:user-1:sess-1", "平台工程师");
    renderShell({ sessionItems: sessions, hasMore: true });

    expect(await screen.findByText("已创建至少 2 次咨询")).toBeVisible();
    expect(screen.getByRole("link", { name: /平台工程师/ })).toBeVisible();
    expect(screen.getByRole("link", { name: /咨询 · 08-04/ })).toBeVisible();
  });

  it("rerenders a title written in the same tab", async () => {
    renderShell({ sessionItems: sessions.slice(0, 1) });
    expect(await screen.findByRole("link", { name: /咨询 · 08-05/ })).toBeVisible();

    act(() => {
      localStorage.setItem("title:user-1:sess-1", "数据平台工程师");
      window.dispatchEvent(new Event("career-rag:session-title-updated"));
    });

    expect(await screen.findByRole("link", { name: /数据平台工程师/ })).toBeVisible();
  });

  it("uses truthful copy when a 402 response opens the quota dialog", async () => {
    const user = userEvent.setup();
    renderShell();
    vi.mocked(api.createSession).mockRejectedValue(new ApiError(402, "quota exceeded"));

    await user.click(screen.getByRole("button", { name: "新的咨询" }));

    const dialog = await screen.findByRole("dialog", { name: "额度已用完" });
    expect(dialog).toHaveTextContent("当前账户的咨询额度已用完");
    expect(dialog).not.toHaveTextContent(/3 次|¥|数字上限/);
  });
});

describe("AppShell mobile navigation", () => {
  it("opens a modal drawer, traps focus, and restores focus after Escape", async () => {
    const user = userEvent.setup();
    renderShell();

    await screen.findByText("测试用户");
    const trigger = document.querySelector<HTMLButtonElement>(".v2-mobile-nav-trigger")!;
    const hiddenCloseButton = document.querySelector<HTMLButtonElement>(".v2-sidebar-close")!;
    trigger.style.display = "block";
    hiddenCloseButton.style.display = "grid";
    expect(trigger).toHaveAccessibleName("打开导航");
    await user.click(trigger);

    const drawer = screen.getByRole("dialog", { name: "主导航" });
    const closeButton = screen.getByRole("button", { name: "关闭导航" });
    expect(drawer).toHaveAttribute("aria-modal", "true");
    expect(closeButton).toHaveFocus();
    expect(document.body.style.overflow).toBe("hidden");

    await user.tab({ shift: true });
    expect(screen.getByRole("button", { name: "退出登录" })).toHaveFocus();
    await user.tab();
    expect(closeButton).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "主导航" })).not.toBeInTheDocument();
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(document.body.style.overflow).toBe("");
  });

  it("closes from the backdrop and returns focus to the menu trigger", async () => {
    const user = userEvent.setup();
    renderShell();

    await screen.findByText("测试用户");
    const trigger = document.querySelector<HTMLButtonElement>(".v2-mobile-nav-trigger")!;
    trigger.style.display = "block";
    await user.click(trigger);
    const backdrop = document.querySelector<HTMLButtonElement>(".v2-drawer-backdrop")!;
    backdrop.style.display = "block";
    expect(backdrop).toHaveAccessibleName("关闭导航遮罩");
    await user.click(backdrop);

    expect(screen.queryByRole("dialog", { name: "主导航" })).not.toBeInTheDocument();
    await waitFor(() => expect(trigger).toHaveFocus());
  });
});
