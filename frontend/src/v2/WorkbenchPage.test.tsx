import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import { api, type Me } from "../api/queries";
import { apiFixtures, RUN_STAGES } from "../test/apiFixtures";
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
  const view = render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { queryClient, ...view };
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

describe("PM service progress announcement", () => {
  function mockRun(statusValue: string, stage: string | null, completedStages: readonly string[] = []) {
    mockWorkbenchApi();
    vi.mocked(api.runStatus).mockResolvedValue(
      apiFixtures.runStatus({
        status: statusValue,
        stage,
        completedStages,
        resultReady: statusValue === "completed" || statusValue === "completed_with_warnings",
        retryAfterMs: null,
      }),
    );
    vi.mocked(api.runConversation).mockResolvedValue(apiFixtures.runConversation(statusValue, null));
  }

  it("renders one sticky PM announcement with four persona sections and no invented duration", async () => {
    mockRun("running", "retrieval", ["resume", "intent"]);
    renderWorkbench("/app/sessions/sess-1?run=run-created");

    const card = await screen.findByRole("region", { name: "服务进度" });
    expect(card.closest(".v2-msg")).toHaveAttribute("data-sticky", "true");
    expect(screen.getAllByRole("region", { name: "服务进度" })).toHaveLength(1);
    expect(within(card).getAllByRole("listitem")).toHaveLength(4);
    for (const label of [
      "小意 · 需求确认",
      "小检 · 岗位筛选",
      "小策 · 规划建议",
      "PM · 核查发布",
    ]) {
      expect(within(card).getByText(label)).toBeVisible();
    }
    expect(card).not.toHaveTextContent(/耗时|秒|分钟/);
  });

  it.each([
    ["resume", "小意 · 需求确认", "资料已就绪·系统处理", "system", false],
    ["intent", "小意 · 需求确认", "PM 正在复核小意已确认的需求", "pm", true],
    ["retrieval", "小检 · 岗位筛选", "小检正在筛选岗位", "job_scout", true],
    ["strategy", "小策 · 规划建议", "小策正在整理规划建议", "strategist", true],
    ["verification", "PM · 核查发布", "PM 正在核查匹配结果", "pm", true],
    ["finalization", "PM · 核查发布", "系统正在整理发布材料", "system", false],
    ["result", "PM · 核查发布", "PM 正在发布结果", "pm", true],
  ])("maps exact stage %s to %s with honest actor copy", async (stage, section, detail, actor, pulsing) => {
    const stageIndex = RUN_STAGES.indexOf(stage as (typeof RUN_STAGES)[number]);
    mockRun("running", stage, RUN_STAGES.slice(0, Math.max(stageIndex, 0)));
    renderWorkbench("/app/sessions/sess-1?run=run-created");

    const card = await screen.findByRole("region", { name: "服务进度" });
    expect((await within(card).findAllByText(detail)).at(-1)).toBeVisible();
    const currentItem = within(card).getByText(section).closest("li");
    expect(currentItem).toHaveAttribute("data-state", "current");
    expect(currentItem).toHaveAttribute("data-actor", actor);
    expect(currentItem).toHaveAttribute("data-pulsing", String(pulsing));
    if (stage === "resume") expect(card).not.toHaveTextContent("小意正在");
  });

  it.each([
    ["completed", "finalization", "已发布"],
    ["completed_with_warnings", "finalization", "已发布"],
    ["plan_ready", "plan", "确认单已锁定，准备执行"],
    ["draft", "plan", "确认单已锁定，准备执行"],
    ["queued", null, "已进入执行队列"],
    ["running", null, "正在启动"],
    ["unexpected", "unexpected", "处理中"],
  ])("prioritizes status %s over stage %s", async (statusValue, stage, label) => {
    mockRun(statusValue, stage);
    renderWorkbench("/app/sessions/sess-1?run=run-created");

    const statusIndicator = await screen.findByRole("status", { name: "服务运行状态" });
    await waitFor(() => expect(statusIndicator).toHaveTextContent(label));
    if (statusValue.startsWith("completed")) {
      const card = screen.getByRole("region", { name: "服务进度" });
      expect(within(card).getAllByRole("listitem").every((item) => item.dataset.state === "complete")).toBe(true);
    }
  });

  it.each(["failed", "stale", "cancelled"])(
    "stops pulsing and marks the reached section when status is %s",
    async (statusValue) => {
      mockRun(statusValue, "retrieval", ["resume", "intent"]);
      renderWorkbench("/app/sessions/sess-1?run=run-created");

      const card = await screen.findByRole("region", { name: "服务进度" });
      await waitFor(() =>
        expect(within(card).getByText("小检 · 岗位筛选").closest("li")).toHaveAttribute(
          "data-state",
          "interrupted",
        ),
      );
      expect(card.querySelector('[data-state="current"]')).not.toBeInTheDocument();
    },
  );

  it.each([null, "plan"])("shows a card-level pre-execution interruption at stage %s", async (stage) => {
    mockRun("failed", stage);
    renderWorkbench("/app/sessions/sess-1?run=run-created");

    const statusIndicator = await screen.findByRole("status", { name: "服务运行状态" });
    await waitFor(() => expect(statusIndicator).toHaveTextContent("执行前中断"));
    expect(document.querySelector('[data-state="interrupted"]')).not.toBeInTheDocument();
  });

  it("marks controlled recovery on the PM section from a recovery conversation message", async () => {
    mockRun("running", "verification", ["resume", "intent", "retrieval", "strategy"]);
    vi.mocked(api.runConversation).mockResolvedValue({
      ...apiFixtures.runConversation("running", null),
      messages: [
        {
          seq: 4,
          persona: "pm",
          display_name: "项目经理·PM",
          kind: "recovery",
          stage: "verification",
          text: "正在执行一次受控重检。",
        },
      ],
    });
    renderWorkbench("/app/sessions/sess-1?run=run-created");

    const card = await screen.findByRole("region", { name: "服务进度" });
    expect(await within(card).findByText("↻ 质量把关：受控重检")).toBeVisible();
  });
});

describe("truthful consultation typing state", () => {
  it("shows a Xiaoyi typing bubble only while a real consult turn is pending", async () => {
    const user = userEvent.setup();
    mockWorkbenchApi();
    vi.spyOn(api, "consultTurn").mockImplementation(() => new Promise(() => undefined));
    renderWorkbench();

    const input = await screen.findByPlaceholderText(/告诉小意你的想法/);
    await user.type(input, "我想找后端岗位");
    await user.click(screen.getByRole("button", { name: "发送" }));

    expect(await screen.findByText("小意正在回复…")).toBeVisible();
    expect(screen.queryByText("团队正在处理下一阶段…")).not.toBeInTheDocument();
  });
});

describe("protected timeline scrolling", () => {
  function setTimelineMetrics(
    timeline: HTMLElement,
    { scrollHeight, clientHeight, scrollTop }: { scrollHeight: number; clientHeight: number; scrollTop: number },
  ) {
    Object.defineProperties(timeline, {
      scrollHeight: { configurable: true, value: scrollHeight },
      clientHeight: { configurable: true, value: clientHeight },
    });
    timeline.scrollTop = scrollTop;
    fireEvent.scroll(timeline);
  }

  it("protects a reader 121px from the bottom but resumes following at the 120px boundary", async () => {
    const user = userEvent.setup();
    mockWorkbenchApi();
    vi.mocked(api.runStatus).mockResolvedValue(
      apiFixtures.runStatus({
        status: "running",
        stage: "retrieval",
        completedStages: ["resume", "intent"],
        resultReady: false,
        retryAfterMs: null,
      }),
    );
    const firstConversation = apiFixtures.runConversation("running", null);
    vi.mocked(api.runConversation).mockResolvedValue(firstConversation);
    const { queryClient } = renderWorkbench("/app/sessions/sess-1?run=run-created");
    await screen.findByText("硬过滤与双路召回完成。");

    const timeline = document.querySelector<HTMLOListElement>(".v2-timeline");
    expect(timeline).not.toBeNull();
    setTimelineMetrics(timeline!, { scrollHeight: 1000, clientHeight: 400, scrollTop: 479 });
    const secondMessage = {
      seq: 4,
      persona: "strategist" as const,
      display_name: "规划师·小策",
      kind: "progress",
      stage: "strategy",
      text: "规划建议已更新。",
    };
    act(() => {
      queryClient.setQueryData(["v2-run-conv", "run-created"], {
        ...firstConversation,
        messages: [...firstConversation.messages, secondMessage],
      });
    });

    const newMessageButton = await screen.findByRole("button", { name: "↓ 有新消息" });
    expect(timeline!.scrollTop).toBe(479);
    await user.click(newMessageButton);
    expect(timeline!.scrollTop).toBe(1000);
    expect(screen.queryByRole("button", { name: "↓ 有新消息" })).not.toBeInTheDocument();

    setTimelineMetrics(timeline!, { scrollHeight: 1000, clientHeight: 400, scrollTop: 480 });
    act(() => {
      queryClient.setQueryData(["v2-run-conv", "run-created"], {
        ...firstConversation,
        messages: [
          ...firstConversation.messages,
          secondMessage,
          {
            seq: 5,
            persona: "pm",
            display_name: "项目经理·PM",
            kind: "checkpoint",
            stage: "strategy",
            text: "规划建议已进入核查。",
          },
        ],
      });
    });
    await screen.findByText("规划建议已进入核查。");
    await waitFor(() => expect(timeline!.scrollTop).toBe(1000));
    expect(screen.queryByRole("button", { name: "↓ 有新消息" })).not.toBeInTheDocument();
  });

  it("uses the result-ready marker and scrolls to a briefly highlighted result anchor only on click", async () => {
    const user = userEvent.setup();
    mockWorkbenchApi();
    const runningStatus = apiFixtures.runStatus({
      status: "running",
      stage: "finalization",
      completedStages: ["resume", "intent", "retrieval", "strategy", "verification"],
      resultReady: false,
      retryAfterMs: null,
    });
    vi.mocked(api.runStatus).mockResolvedValue(runningStatus);
    vi.mocked(api.runConversation).mockResolvedValue(apiFixtures.runConversation("running", null));
    vi.spyOn(api, "runResult").mockResolvedValue(apiFixtures.runResult());
    const { queryClient } = renderWorkbench("/app/sessions/sess-1?run=run-created");
    await screen.findAllByText("系统正在整理发布材料");

    const timeline = document.querySelector<HTMLOListElement>(".v2-timeline");
    expect(timeline).not.toBeNull();
    setTimelineMetrics(timeline!, { scrollHeight: 1000, clientHeight: 400, scrollTop: 200 });
    act(() => {
      queryClient.setQueryData(
        ["v2-run-status", "run-created"],
        apiFixtures.runStatus({
          status: "completed",
          stage: "finalization",
          completedStages: RUN_STAGES,
          resultReady: true,
          retryAfterMs: null,
        }),
      );
    });

    const resultButton = await screen.findByRole("button", { name: "结果已生成 ↓" });
    expect(timeline!.scrollTop).toBe(200);
    const resultAnchor = await screen.findByRole("region", { name: "匹配结果" });
    const firstResultCard = resultAnchor.querySelector<HTMLElement>(".v2-job-card");
    expect(firstResultCard).not.toBeNull();
    const regionScrollIntoView = vi.fn();
    const cardScrollIntoView = vi.fn();
    Object.defineProperty(resultAnchor, "scrollIntoView", {
      configurable: true,
      value: regionScrollIntoView,
    });
    Object.defineProperty(firstResultCard!, "scrollIntoView", {
      configurable: true,
      value: cardScrollIntoView,
    });
    await user.click(resultButton);

    expect(cardScrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "start" });
    expect(regionScrollIntoView).not.toHaveBeenCalled();
    expect(firstResultCard).toHaveClass("is-highlighted");
    expect(screen.queryByRole("button", { name: "结果已生成 ↓" })).not.toBeInTheDocument();
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
