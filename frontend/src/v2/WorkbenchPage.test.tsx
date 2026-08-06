import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import { api, type Me } from "../api/queries";
import { PERSONAS, conversationInterval, statusInterval } from "./WorkbenchPage";
import { WorkbenchPage } from "./WorkbenchPage";

const ME = {
  user_id: "user-1",
  status: "active",
  is_admin: false,
  display_name: "测试用户",
  created_at: "2026-08-06T10:00:00Z",
} satisfies Me;

function LocationProbe() {
  const location = useLocation();
  return <output aria-label="current location">{`${location.pathname}${location.search}`}</output>;
}

function mockWorkbenchApi() {
  vi.spyOn(api, "resumePreview").mockResolvedValue({
    session_id: "sess-1",
    resume_version: 1,
    confirmed: true,
    education: [],
    experience: [],
    projects: [],
    skills: ["Python"],
    resume_quality_issues: [],
    evidence: [],
  });
  vi.spyOn(api, "consultState").mockResolvedValue({
    transcript: [],
    profile_draft: {
      current_goal: ["backend engineer"],
      hard_constraints: { locations: ["Shanghai"], need_visa_sponsor: false },
      soft_preferences: {},
      avoid_roles: [],
    },
    round: 2,
    phase: "deepen",
    completeness: 1,
    can_finalize: true,
  });
  vi.spyOn(api, "consultFinalize").mockResolvedValue({
    career_goal: "backend engineer",
    hard_constraints: { locations: ["Shanghai"], need_visa_sponsor: false },
    soft_preferences: {},
    avoid_roles: [],
    result_count: 5,
  });
  vi.spyOn(api, "createMatchBrief").mockResolvedValue({
    run_id: "run-created",
    session_id: "sess-1",
    brief: {
      career_goal: "backend engineer",
      hard_constraints: { locations: ["Shanghai"], need_visa_sponsor: false },
      soft_preferences: {},
      avoid_roles: [],
      result_count: 5,
      needs_clarification: false,
      plan_version: 1,
      plan_hash: "b".repeat(64),
    },
  });
  vi.spyOn(api, "runStatus").mockResolvedValue({
    run_id: "run-created",
    session_id: "sess-1",
    status: "failed",
    stage: "retrieval",
    result_ready: false,
    plan_version: 1,
    plan_hash: "b".repeat(64),
    retry_after_ms: null,
    completed_stages: ["resume", "intent"],
    total_stages: 7,
    warning_codes: [],
    error_code: "RETRIEVAL_FAILED",
    execution_durability: "process_local",
    updated_at: "2026-08-06T10:05:00Z",
  });
  vi.spyOn(api, "runConversation").mockResolvedValue({
    run_id: "run-created",
    status: "failed",
    stage: "retrieval",
    next_poll_ms: null,
    messages: [],
  });
}

function renderWorkbench(initialEntry = "/app/sessions/sess-1") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  queryClient.setQueryData(["me"], ME);
  const router = createMemoryRouter(
    [
      {
        path: "/app/sessions/:sessionId",
        element: (
          <>
            <WorkbenchPage />
            <LocationProbe />
          </>
        ),
      },
    ],
    { initialEntries: [initialEntry] },
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
});

describe("v2 polling intervals", () => {
  it("follows server pacing while running and stops on terminal states", () => {
    expect(conversationInterval({ status: "running", next_poll_ms: 1500 })).toBe(1500);
    expect(conversationInterval({ status: "completed", next_poll_ms: null })).toBe(false);
    expect(conversationInterval({ status: "cancelled", next_poll_ms: 1500 })).toBe(false);
    expect(conversationInterval(undefined)).toBe(false);
    expect(statusInterval({ status: "running", retry_after_ms: 900 })).toBe(900);
    expect(statusInterval({ status: "failed", retry_after_ms: 900 })).toBe(false);
    expect(statusInterval({ status: "cancelled", retry_after_ms: 900 })).toBe(false);
  });
});

describe("v2 personas", () => {
  it("covers the four service personas plus the user", () => {
    expect(Object.keys(PERSONAS).sort()).toEqual([
      "intent_consultant",
      "job_scout",
      "pm",
      "strategist",
      "user",
    ]);
  });
});

describe("last run recovery", () => {
  it("persists the run as soon as Match Brief creation succeeds", async () => {
    const user = userEvent.setup();
    mockWorkbenchApi();
    renderWorkbench();

    await user.click(await screen.findByRole("button", { name: "生成确认单" }));
    await user.click(await screen.findByRole("button", { name: "确认无误，开始匹配" }));

    await waitFor(() =>
      expect(localStorage.getItem("last_run:user-1:sess-1")).toBe("run-created"),
    );
  });

  it("restores a stored run when the conversation URL has no run query", async () => {
    mockWorkbenchApi();
    localStorage.setItem("last_run:user-1:sess-1", "run-stored");
    renderWorkbench();

    await waitFor(() => expect(api.runStatus).toHaveBeenCalledWith("run-stored"));
    expect(screen.getByLabelText("current location")).toHaveTextContent("?run=run-stored");
  });

  it.each([403, 404])("removes a stored run rejected with %s and returns to consultation", async (statusCode) => {
    mockWorkbenchApi();
    vi.mocked(api.runStatus).mockRejectedValue(new ApiError(statusCode, "run unavailable"));
    localStorage.setItem("last_run:user-1:sess-1", "run-stale");
    renderWorkbench();

    await waitFor(() => {
      expect(localStorage.getItem("last_run:user-1:sess-1")).toBeNull();
      expect(screen.getByLabelText("current location")).toHaveTextContent("/app/sessions/sess-1");
      expect(screen.getByLabelText("current location")).not.toHaveTextContent("?run=");
    });
  });

  it.each(["success", "conflict"])("idempotently rewrites the run after execute %s", async (result) => {
    const user = userEvent.setup();
    mockWorkbenchApi();
    vi.mocked(api.runStatus).mockResolvedValue({
      run_id: "run-created",
      session_id: "sess-1",
      status: "plan_ready",
      stage: "plan",
      result_ready: false,
      plan_version: 1,
      plan_hash: "b".repeat(64),
      retry_after_ms: null,
      completed_stages: [],
      total_stages: 7,
      warning_codes: [],
      error_code: null,
      execution_durability: "process_local",
      updated_at: "2026-08-06T10:05:00Z",
    });
    vi.spyOn(api, "executeRun").mockImplementation(async () => {
      localStorage.removeItem("last_run:user-1:sess-1");
      if (result === "conflict") throw new ApiError(409, "already executing");
      return {
        run_id: "run-created",
        session_id: "sess-1",
        status: "running",
        stage: "resume",
        result_ready: false,
        plan_version: 1,
        plan_hash: "b".repeat(64),
        retry_after_ms: 500,
        completed_stages: [],
        total_stages: 7,
        warning_codes: [],
        error_code: null,
        execution_durability: "process_local",
        updated_at: "2026-08-06T10:05:01Z",
      };
    });
    renderWorkbench();

    await user.click(await screen.findByRole("button", { name: "生成确认单" }));
    await user.click(await screen.findByRole("button", { name: "确认无误，开始匹配" }));

    await waitFor(() => expect(api.executeRun).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(localStorage.getItem("last_run:user-1:sess-1")).toBe("run-created"),
    );
  });
});

describe("terminal run exit", () => {
  it.each(["failed", "stale", "cancelled"])("creates a fresh session after a %s run", async (runStatus) => {
    const user = userEvent.setup();
    mockWorkbenchApi();
    vi.mocked(api.runStatus).mockResolvedValue({
      run_id: "run-terminal",
      session_id: "sess-1",
      status: runStatus,
      stage: "retrieval",
      result_ready: false,
      plan_version: 1,
      plan_hash: "b".repeat(64),
      retry_after_ms: null,
      completed_stages: ["resume", "intent"],
      total_stages: 7,
      warning_codes: [],
      error_code: runStatus === "cancelled" ? null : "RUN_INTERRUPTED",
      execution_durability: "process_local",
      updated_at: "2026-08-06T10:05:00Z",
    });
    vi.spyOn(api, "createSession").mockResolvedValue({
      session_id: "sess-new",
      status: "awaiting_resume",
    });
    renderWorkbench("/app/sessions/sess-1?run=run-terminal");

    expect(await screen.findByText(/需要新建咨询后重试/)).toBeVisible();
    await user.click(screen.getByRole("button", { name: "新建咨询重试" }));
    expect(screen.getByRole("dialog", { name: "新建咨询确认" })).toHaveTextContent(
      "会消耗一次咨询额度",
    );
    await user.click(screen.getByRole("button", { name: "确认新建咨询" }));

    await waitFor(() => expect(api.createSession).toHaveBeenCalledWith({}));
    await waitFor(() =>
      expect(screen.getByLabelText("current location")).toHaveTextContent("/app/sessions/sess-new"),
    );
  });

  it("keeps the failed run visible when fresh-session creation returns 402", async () => {
    const user = userEvent.setup();
    mockWorkbenchApi();
    vi.spyOn(api, "createSession").mockRejectedValue(new ApiError(402, "quota exceeded"));
    renderWorkbench("/app/sessions/sess-1?run=run-created");

    await user.click(await screen.findByRole("button", { name: "新建咨询重试" }));
    await user.click(screen.getByRole("button", { name: "确认新建咨询" }));

    expect(await screen.findByRole("dialog", { name: "额度已用完" })).toHaveTextContent(
      "当前账户的咨询额度已用完",
    );
    expect(screen.getByLabelText("current location")).toHaveTextContent(
      "/app/sessions/sess-1?run=run-created",
    );
    expect(screen.getByText(/需要新建咨询后重试/)).toBeVisible();
  });

  it("hands off focus to the quota modal on 402 and returns it to the trigger on close", async () => {
    const user = userEvent.setup();
    mockWorkbenchApi();
    vi.spyOn(api, "createSession").mockRejectedValue(new ApiError(402, "quota exceeded"));
    renderWorkbench("/app/sessions/sess-1?run=run-created");

    const trigger = await screen.findByRole("button", { name: "新建咨询重试" });
    await user.click(trigger);
    await user.click(screen.getByRole("button", { name: "确认新建咨询" }));

    // 402 后额度弹窗容器持有焦点（同一 FocusModal 实例切换，无卸载竞态）
    const quotaDialog = await screen.findByRole("dialog", { name: "额度已用完" });
    await waitFor(() => expect(quotaDialog.querySelector(".v2-modal")).toHaveFocus());

    // Tab 被约束在额度弹窗内（唯一可聚焦元素自循环）
    await user.tab();
    expect(screen.getByRole("button", { name: "返回当前页面" })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("button", { name: "返回当前页面" })).toHaveFocus();

    // Escape 关闭后焦点回到原“新建咨询重试”触发按钮
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "额度已用完" })).not.toBeInTheDocument();
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("manages keyboard focus for the confirm modal: container focus, Escape close, focus return", async () => {
    const user = userEvent.setup();
    mockWorkbenchApi();
    renderWorkbench("/app/sessions/sess-1?run=run-created");

    const trigger = await screen.findByRole("button", { name: "新建咨询重试" });
    await user.click(trigger);

    const dialog = screen.getByRole("dialog", { name: "新建咨询确认" });
    // 初始焦点在容器而非“确认新建咨询”——防止回车误消耗额度
    expect(dialog.querySelector(".v2-modal")).toHaveFocus();

    // Tab 循环被约束在弹窗内
    await user.tab();
    expect(screen.getByRole("button", { name: "确认新建咨询" })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("button", { name: "保留当前页面" })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("button", { name: "确认新建咨询" })).toHaveFocus();

    // Escape 关闭且焦点归还触发按钮
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "新建咨询确认" })).not.toBeInTheDocument();
    await waitFor(() => expect(trigger).toHaveFocus());
  });
});

describe("run message rendering", () => {
  it("skips the duplicate PM intro while retaining later run messages", async () => {
    mockWorkbenchApi();
    vi.mocked(api.runStatus).mockResolvedValue({
      run_id: "run-created",
      session_id: "sess-1",
      status: "running",
      stage: "retrieval",
      result_ready: false,
      plan_version: 1,
      plan_hash: "b".repeat(64),
      retry_after_ms: null,
      completed_stages: ["resume", "intent"],
      total_stages: 7,
      warning_codes: [],
      error_code: null,
      execution_durability: "process_local",
      updated_at: "2026-08-06T10:05:00Z",
    });
    vi.mocked(api.runConversation).mockResolvedValue({
      run_id: "run-created",
      status: "running",
      stage: "retrieval",
      next_poll_ms: null,
      messages: [
        {
          seq: 1,
          persona: "pm",
          display_name: "项目经理·PM",
          kind: "intro",
          stage: "intent",
          text: "重复的运行期自我介绍",
        },
        {
          seq: 2,
          persona: "job_scout",
          display_name: "岗位顾问·小检",
          kind: "progress",
          stage: "retrieval",
          text: "正在筛选岗位",
        },
      ],
    });
    renderWorkbench("/app/sessions/sess-1?run=run-created");

    expect(await screen.findByText("正在筛选岗位")).toBeVisible();
    expect(screen.queryByText("重复的运行期自我介绍")).not.toBeInTheDocument();
  });
});
