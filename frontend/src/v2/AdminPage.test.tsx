import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import { api } from "../api/queries";
import { apiFixtures } from "../test/apiFixtures";
import { AdminPage } from "./AdminPage";

function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

function renderAdmin({
  initialEntry = "/admin",
  queryClient = createTestQueryClient(),
}: {
  initialEntry?: string;
  queryClient?: QueryClient;
} = {}) {
  const router = createMemoryRouter(
    [
      { path: "/admin", element: <AdminPage /> },
      { path: "/app", element: <p>用户工作台</p> },
      { path: "/login", element: <p>登录页</p> },
    ],
    { initialEntries: [initialEntry] },
  );
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { queryClient, router };
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function requestPath(input: RequestInfo | URL): string {
  return typeof input === "string" ? input : input instanceof URL ? input.pathname : input.url;
}

beforeEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("AdminPage authorization gate", () => {
  it("renders only the auth loading state and makes zero admin requests while me is pending", () => {
    vi.spyOn(api, "me").mockReturnValue(new Promise(() => undefined));
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    renderAdmin();

    expect(screen.getByRole("status", { name: "正在验证管理权限" })).toBeVisible();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.queryByText("管理控制台")).not.toBeInTheDocument();
  });

  it("revalidates a cached admin identity before rendering cached admin content", () => {
    const queryClient = createTestQueryClient();
    queryClient.setQueryData(["me"], apiFixtures.me(true));
    queryClient.setQueryData(["admin", "overview"], apiFixtures.adminOverview());
    vi.spyOn(api, "me").mockReturnValue(new Promise(() => undefined));
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    renderAdmin({ queryClient });

    expect(screen.getByRole("status", { name: "正在验证管理权限" })).toBeVisible();
    expect(screen.queryByText("管理控制台")).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("evicts cached admin data before mounting a freshly confirmed admin workspace", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: 10_000 } },
    });
    queryClient.setQueryData(["me"], apiFixtures.me(true));
    queryClient.setQueryData(["admin", "overview"], apiFixtures.adminOverview({ users_total: 9_999 }));
    let confirmAdmin!: (value: ReturnType<typeof apiFixtures.me>) => void;
    vi.spyOn(api, "me").mockReturnValue(new Promise((resolve) => { confirmAdmin = resolve; }));
    const fetchMock = vi.fn().mockReturnValue(new Promise(() => undefined));
    vi.stubGlobal("fetch", fetchMock);

    renderAdmin({ queryClient });
    confirmAdmin(apiFixtures.me(true));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/admin/overview",
      expect.any(Object),
    ));
    expect(queryClient.getQueryData(["admin", "overview"])).toBeUndefined();
    expect(screen.queryByText("9,999")).not.toBeInTheDocument();
  });

  it("redirects a regular user to the app without making admin requests", async () => {
    vi.spyOn(api, "me").mockResolvedValue(apiFixtures.me(false));
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const { router } = renderAdmin();

    await waitFor(() => expect(router.state.location.pathname).toBe("/app"));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("redirects an unauthenticated visitor to login without making admin requests", async () => {
    vi.spyOn(api, "me").mockRejectedValue(new ApiError(401, "not authenticated"));
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const { router } = renderAdmin();

    await waitFor(() => expect(router.state.location.pathname).toBe("/login"));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("mounts the dashboard and starts admin data loading only after admin confirmation", async () => {
    vi.spyOn(api, "me").mockResolvedValue(apiFixtures.me(true));
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(apiFixtures.adminOverview()));
    vi.stubGlobal("fetch", fetchMock);

    renderAdmin();

    expect(await screen.findByRole("heading", { name: "管理控制台" })).toBeVisible();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/admin/overview");
  });
});

describe("AdminPage dashboard", () => {
  it("renders split-token, nullable, total-only reranker, and unknown-model cost branches", async () => {
    vi.spyOn(api, "me").mockResolvedValue(apiFixtures.me(true));
    const overview = apiFixtures.adminOverview({
      tokens_by_model: [
        {
          model: "deepseek-v4-flash",
          prompt_tokens: 1_000_000,
          completion_tokens: 1_000_000,
          total_tokens: 2_000_000,
        },
        {
          model: "deepseek-v4-pro",
          prompt_tokens: null,
          completion_tokens: 100,
          total_tokens: 100,
        },
        {
          model: "gte-rerank-v2",
          prompt_tokens: null,
          completion_tokens: null,
          total_tokens: 1_000_000,
        },
        {
          model: "text-embedding-v4",
          prompt_tokens: 1_000_000,
          completion_tokens: null,
          total_tokens: 1_000_000,
        },
        {
          model: "future-model",
          prompt_tokens: 200,
          completion_tokens: 100,
          total_tokens: 300,
        },
      ],
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(overview)));

    renderAdmin();

    expect(await screen.findByText("估算·价格版本 2026-08")).toBeVisible();
    const splitRow = screen.getByRole("row", { name: /deepseek-v4-flash/ });
    expect(splitRow).toHaveTextContent("1,000,000");
    expect(splitRow).toHaveTextContent("$0.420000");

    const nullableRow = screen.getByRole("row", { name: /deepseek-v4-pro/ });
    expect(nullableRow).toHaveTextContent("—");
    expect(nullableRow).toHaveTextContent("无法估算");

    const rerankerRow = screen.getByRole("row", { name: /gte-rerank-v2/ });
    expect(rerankerRow).toHaveTextContent("仅 total");
    expect(rerankerRow).toHaveTextContent("¥0.800000");

    const embeddingRow = screen.getByRole("row", { name: /text-embedding-v4/ });
    expect(embeddingRow).toHaveTextContent("仅 prompt");
    expect(embeddingRow).toHaveTextContent("¥0.500000");

    const unknownRow = screen.getByRole("row", { name: /future-model/ });
    expect(unknownRow).toHaveTextContent("无法估算");
    expect(unknownRow).not.toHaveTextContent(/[¥$]0(?:\.0+)?/);
  });
});

describe("AdminPage users", () => {
  it("uses the fixed 20-row DTO page, renders null resume fields truthfully, and expands raw resume JSON", async () => {
    vi.spyOn(api, "me").mockResolvedValue(apiFixtures.me(true));
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const path = requestPath(input);
      if (path === "/api/v1/admin/users?page=1") {
        return Promise.resolve(jsonResponse(apiFixtures.adminUsers()));
      }
      if (path === "/api/v1/admin/users/user-e2e-0001/resume") {
        return Promise.resolve(jsonResponse(apiFixtures.adminUserResume()));
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderAdmin({ initialEntry: "/admin?tab=users" });

    expect(await screen.findByText("每页 20 条")).toBeVisible();
    expect(await screen.findByRole("cell", { name: "未上传" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "查看简历" }));

    expect(await screen.findByText("13800000000")).toBeVisible();
    expect(screen.getByRole("button", { name: "收起简历" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getAllByText("student@example.com")).toHaveLength(2);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/admin/users/user-e2e-0001/resume",
      expect.any(Object),
    );
  });

  it("confirms, resolves the user's session, posts reset, and shows the response", async () => {
    vi.spyOn(api, "me").mockResolvedValue(apiFixtures.me(true));
    const confirmMock = vi.spyOn(window, "confirm").mockReturnValue(true);
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const path = requestPath(input);
      if (path === "/api/v1/admin/users?page=1") {
        return Promise.resolve(jsonResponse(apiFixtures.adminUsers()));
      }
      if (path === "/api/v1/admin/users/user-e2e-0001/resume") {
        // session_id（简历展示源）与 reset_session_id（重置靶）刻意不同：
        // 回退用旧字段会 POST 到 sess-display-1 → Unexpected request 红。
        return Promise.resolve(
          jsonResponse(apiFixtures.adminUserResume({ session_id: "sess-display-1" })),
        );
      }
      if (path === "/api/v1/admin/sessions/sess-e2e-1/reset-parse-count") {
        expect(init?.method).toBe("POST");
        return Promise.resolve(jsonResponse(apiFixtures.adminResetParseCount()));
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: 10_000 }, mutations: { retry: false } },
    });
    queryClient.setQueryData(
      ["admin", "user-resume", "user-e2e-0001"],
      apiFixtures.adminUserResume({ session_id: "sess-stale", reset_session_id: "sess-stale" }),
    );

    renderAdmin({ initialEntry: "/admin?tab=users", queryClient });
    await user.click(await screen.findByRole("button", { name: "重置解析额度" }));

    expect(confirmMock).toHaveBeenCalledTimes(1);
    expect(await screen.findByRole("status", { name: "解析额度重置结果" })).toHaveTextContent(
      "sess-e2e-1 · resume_uploaded · 0 次",
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/admin/sessions/sess-e2e-1/reset-parse-count",
      expect.objectContaining({ method: "POST" }),
    );
  });
});

describe("AdminPage operations", () => {
  it("uses the cross-user admin explain endpoint without a capability request", async () => {
    vi.spyOn(api, "me").mockResolvedValue(apiFixtures.me(true));
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const path = requestPath(input);
      if (path === "/api/v1/admin/runs/run-e2e-1/explain") {
        return Promise.resolve(jsonResponse(apiFixtures.adminRunExplain()));
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderAdmin({ initialEntry: "/admin?tab=evaluation&runId=run-e2e-1" });

    expect(await screen.findByText("job-e2e-1")).toBeVisible();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls.some(([input]) => requestPath(input).includes("capabilities"))).toBe(false);
  });

  it("keeps runId in the URL and follows browser query navigation", async () => {
    vi.spyOn(api, "me").mockResolvedValue(apiFixtures.me(true));
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const path = requestPath(input);
      if (path === "/api/v1/admin/runs/run-one/explain") {
        return Promise.resolve(jsonResponse(apiFixtures.adminRunExplain("run-one")));
      }
      if (path === "/api/v1/admin/runs/run-two/explain") {
        return Promise.resolve(jsonResponse(apiFixtures.adminRunExplain("run-two")));
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    const { router } = renderAdmin({ initialEntry: "/admin?tab=evaluation&runId=run-one" });

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/admin/runs/run-one/explain",
      expect.any(Object),
    ));
    await user.click(screen.getByRole("button", { name: "评估与监控" }));
    expect(new URLSearchParams(router.state.location.search).get("runId")).toBe("run-one");

    await router.navigate("/admin?tab=evaluation&runId=run-two");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/admin/runs/run-two/explain",
      expect.any(Object),
    ));
  });

  it("loads monitoring only from the already admin-protected monitoring endpoints", async () => {
    vi.spyOn(api, "me").mockResolvedValue(apiFixtures.me(true));
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const path = requestPath(input);
      if (path === "/api/v1/monitoring/overview?window_hours=24") {
        return Promise.resolve(jsonResponse(apiFixtures.monitoringOverview()));
      }
      if (path === "/api/v1/monitoring/runs?window_hours=24&limit=20") {
        return Promise.resolve(jsonResponse(apiFixtures.recentRuns()));
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderAdmin({ initialEntry: "/admin?tab=monitoring" });

    expect(await screen.findByText("运行总量")).toBeVisible();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls.some(([input]) => requestPath(input).includes("capabilities"))).toBe(false);
  });
});

describe("AdminPage revoked-admin boundary", () => {
  it("clears the admin query cache and redirects to the app on an admin data 403", async () => {
    vi.spyOn(api, "me").mockResolvedValue(apiFixtures.me(true));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "forbidden" }, 403)));
    const queryClient = createTestQueryClient();
    queryClient.setQueryData(["admin", "stale-user"], { email: "stale@example.com" });

    const { router } = renderAdmin({ queryClient });

    await waitFor(() => expect(router.state.location.pathname).toBe("/app"));
    expect(queryClient.getQueryData(["admin", "stale-user"])).toBeUndefined();
  });

  it("clears cached identity and admin data then redirects to login on an admin data 401", async () => {
    vi.spyOn(api, "me").mockResolvedValue(apiFixtures.me(true));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "expired" }, 401)));
    const queryClient = createTestQueryClient();
    queryClient.setQueryData(["admin", "stale-user"], { email: "stale@example.com" });

    const { router } = renderAdmin({ queryClient });

    await waitFor(() => expect(router.state.location.pathname).toBe("/login"));
    expect(queryClient.getQueryData(["admin", "stale-user"])).toBeUndefined();
    expect(queryClient.getQueryData(["me"])).toBeUndefined();
  });
});
