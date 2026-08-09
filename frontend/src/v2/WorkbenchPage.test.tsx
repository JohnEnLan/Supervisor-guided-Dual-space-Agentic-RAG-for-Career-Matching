import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import { api, type Me } from "../api/queries";
import { apiFixtures, RUN_STAGES } from "../test/apiFixtures";
import {
  PERSONAS,
  buildProfileSummaryLines,
  conversationInterval,
  resumePreviewInterval,
  resumeProgressInterval,
  statusInterval,
  useStaggeredReveal,
} from "./WorkbenchPage";
import { WorkbenchPage } from "./WorkbenchPage";
import workbenchSource from "./WorkbenchPage.tsx?raw";

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
  vi.spyOn(api, "capabilities").mockResolvedValue(
    apiFixtures.capabilities({ resume_image_upload_enabled: false }),
  );
  // B2：默认无待解析上传（404）——确认解析卡只在显式 mock 时出现
  vi.spyOn(api, "pendingResumeUpload").mockRejectedValue(
    new ApiError(404, "no pending resume upload"),
  );
  // B3：默认空闲进度（done=true 即停轮询）——叙事只在显式 mock 时出现
  vi.spyOn(api, "resumeProgress").mockResolvedValue({
    generation: null,
    status: "pending",
    events: [],
    done: true,
  });
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
  return { queryClient, router, ...view };
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

describe("plan-ready execution effect", () => {
  it("depends on the stable mutate callback instead of the mutation observer object", () => {
    expect(workbenchSource).toMatch(/\[status\.data, runId, execute\.mutate\]/);
    expect(workbenchSource).not.toMatch(/\[status\.data, runId, execute\]/);
  });

  it("renders the mode guidance before a full-width attachment, input, and send row", () => {
    const modeRow = workbenchSource.indexOf('className="v2-mode-toggle v2-composer-mode"');
    const inputRow = workbenchSource.indexOf('className="v2-composer-row"');

    expect(modeRow).toBeGreaterThan(-1);
    expect(inputRow).toBeGreaterThan(modeRow);
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

describe("session-scoped workbench state", () => {
  it("clears an unconfirmed Match Brief draft when the route switches sessions", async () => {
    const user = userEvent.setup();
    mockWorkbenchApi();
    const { router } = renderWorkbench();

    await user.click(await screen.findByRole("button", { name: "生成确认单" }));
    expect(await screen.findByText("需求摘要（Match Brief）")).toBeVisible();

    await act(() => router.navigate("/app/sessions/sess-2"));

    await waitFor(() =>
      expect(screen.queryByText("需求摘要（Match Brief）")).not.toBeInTheDocument(),
    );
  });

  it("closes a retry modal when the route switches sessions", async () => {
    const user = userEvent.setup();
    mockWorkbenchApi();
    const { router } = renderWorkbench("/app/sessions/sess-1?run=run-created");

    await user.click(await screen.findByRole("button", { name: "新建咨询重试" }));
    expect(screen.getByRole("dialog", { name: "新建咨询确认" })).toBeVisible();

    await act(() => router.navigate("/app/sessions/sess-2"));

    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "新建咨询确认" })).not.toBeInTheDocument(),
    );
  });
});

describe("natural-language Match Brief summary", () => {
  it("shows mapped Chinese phrases without JSON literals", async () => {
    const user = userEvent.setup();
    mockWorkbenchApi();
    vi.mocked(api.consultFinalize).mockResolvedValue({
      career_goal: "backend engineer",
      hard_constraints: {
        locations: ["Shanghai"],
        need_visa_sponsor: false,
        unknown_key: "保留值",
      },
      soft_preferences: {
        preferred_locations: ["深圳"],
        preferred_role_clusters: ["市场营销"],
        title_keywords: ["用户运营"],
      },
      avoid_roles: ["销售"],
      result_count: 5,
    });
    renderWorkbench();

    await user.click(await screen.findByRole("button", { name: "生成确认单" }));

    const summary = screen.getByText("需求摘要（Match Brief）").closest(".v2-brief")!;
    expect(summary).toHaveTextContent("目标backend engineer");
    expect(summary).toHaveTextContent("硬条件地点 Shanghai、不需要签证担保、unknown_key 保留值");
    expect(summary).toHaveTextContent(
      "排序偏好偏好地点 深圳、岗位簇 市场营销、关键词 用户运营",
    );
    expect(summary).toHaveTextContent("暂不考虑销售");
    expect(summary).toHaveTextContent("结果数量5");
    expect(summary).toHaveTextContent(
      "检索将基于你的完整简历档案 + 以上确认条件（硬条件数据库过滤，偏好参与排序）。",
    );
    expect(summary).not.toHaveTextContent('{"');
    expect(summary).not.toHaveTextContent('":');
  });
});

describe("consultation required-slot presentation", () => {
  it("renders three chips and a completeness bar, then focuses and safely prefills missing slots", async () => {
    const user = userEvent.setup();
    mockWorkbenchApi();
    vi.mocked(api.consultState).mockResolvedValue({
      transcript: [],
      profile_draft: {
        current_goal: ["Backend engineer"],
        hard_constraints: {},
        soft_preferences: {},
        avoid_roles: [],
      },
      round: 1,
      phase: "template",
      completeness: 0.4,
      can_finalize: false,
    });
    renderWorkbench();

    const input = await screen.findByPlaceholderText(/告诉小意你的想法/);
    expect(screen.getAllByRole("button", { name: /^(目标|地点|签证)：/ })).toHaveLength(3);
    expect(screen.getByRole("progressbar", { name: "咨询信息完成度" })).toHaveAttribute(
      "aria-valuenow",
      "40",
    );

    await user.click(screen.getByRole("button", { name: "地点：待补充" }));
    expect(input).toHaveFocus();
    expect(input).toHaveValue("我希望工作的地点是：");

    await user.clear(input);
    await user.type(input, "已有草稿");
    await user.click(screen.getByRole("button", { name: "签证：待补充" }));
    expect(input).toHaveFocus();
    expect(input).toHaveValue("已有草稿");
  });
});

describe("consultation supervisor notes and finalization", () => {
  it("renders each PM note directly after that round's Xiaoyi bubble", async () => {
    mockWorkbenchApi();
    const note = apiFixtures.supervisorNote({ text: "请补充你选择岗位时最看重的依据。" });
    vi.mocked(api.consultState).mockResolvedValue(
      apiFixtures.consultState(1, { supervisor_notes: [note] }),
    );

    renderWorkbench();

    const assistantBubble = (await screen.findByText(/明白了（第 1 轮）/)).closest(".v2-msg");
    const noteBubble = screen.getByText(note.text).closest(".v2-msg");
    expect(assistantBubble?.nextElementSibling).toBe(noteBubble);
    expect(noteBubble).toHaveAttribute("data-persona", "pm");
    expect(within(noteBubble as HTMLElement).getByText("第 1 轮")).toHaveAttribute(
      "data-meta-kind",
      "round",
    );
  });

  it("keeps old transcript entries without supervisor_notes compatible and adds no PM node", async () => {
    mockWorkbenchApi();
    vi.mocked(api.consultState).mockResolvedValue(apiFixtures.consultState(1));

    renderWorkbench();

    await screen.findByText(/明白了（第 1 轮）/);
    expect(document.querySelectorAll('.v2-msg[data-persona="pm"]')).toHaveLength(1);
    expect(screen.queryByText(/方向已经明确/)).not.toBeInTheDocument();
  });

  it("mounts the only finalization CTA under a finalizable PM note and keeps its accessible name", async () => {
    mockWorkbenchApi();
    const note = apiFixtures.supervisorNote({
      trigger: "finalizable",
      text: "关键信息与简历补充已经齐全，可以生成确认单。",
    });
    vi.mocked(api.consultState).mockResolvedValue(
      apiFixtures.consultState(2, { supervisor_notes: [note] }),
    );

    renderWorkbench();

    const noteBubble = (await screen.findByText(note.text)).closest(".v2-msg");
    const action = within(noteBubble as HTMLElement).getByRole("button", { name: "生成确认单" });
    expect(action).toBeEnabled();
    expect(action.closest(".v2-finalize-action")).not.toBeNull();
    expect(screen.getAllByRole("button", { name: "生成确认单" })).toHaveLength(1);
    expect(screen.queryByText(/小意已把必填信息收集齐/)).not.toBeInTheDocument();
  });

  it("falls back to the complete deterministic PM card and keeps the generated-brief interjection", async () => {
    const user = userEvent.setup();
    mockWorkbenchApi();
    vi.mocked(api.consultState).mockResolvedValue(apiFixtures.consultState(2));

    renderWorkbench();

    expect(
      await screen.findByText(
        "小意已把必填信息收集齐：目标 backend engineer、地点 Shanghai、签证不需担保。你可以继续补充偏好，也可以让我安排匹配。",
      ),
    ).toBeVisible();
    const finalizeButton = screen.getByRole("button", { name: "生成确认单" });
    expect(finalizeButton).toBeEnabled();
    await user.click(finalizeButton);
    expect(
      await screen.findByText(
        "检索将基于你的完整简历档案 + 以上确认条件（硬条件数据库过滤，偏好参与排序）。",
      ),
    ).toBeVisible();
  });

  it("disables finalization while a consult turn is pending", async () => {
    const user = userEvent.setup();
    mockWorkbenchApi();
    vi.mocked(api.consultState).mockResolvedValue(apiFixtures.consultState(2));
    vi.spyOn(api, "consultTurn").mockImplementation(() => new Promise(() => undefined));
    renderWorkbench();

    const input = await screen.findByPlaceholderText(/告诉小意你的想法/);
    await user.type(input, "再补充一条偏好");
    await user.click(screen.getByRole("button", { name: "发送" }));

    expect(await screen.findByText("小意正在回复…")).toBeVisible();
    expect(screen.getByRole("button", { name: "生成确认单" })).toBeDisabled();
  });
});

describe("resume confirmation profile", () => {
  function mockUnconfirmedFullResume() {
    mockWorkbenchApi();
    vi.mocked(api.resumePreview).mockResolvedValue({
      session_id: "sess-1",
      resume_version: 2,
      confirmed: false,
      education: [
        {
          institution: "Birmingham University",
          degree: "MSc",
          field: "Computer Science",
          dates: "2025–2026",
          details: ["Distinction track"],
          evidence_span_ids: ["R-EDU-1"],
        },
      ],
      experience: [
        {
          organization: "Career Lab",
          title: "Backend Engineer",
          location: "Shanghai",
          dates: "2024–2025",
          responsibilities: ["Built retrieval services"],
          achievements: ["Reduced latency by 30%"],
          technologies: ["Python", "PostgreSQL"],
          evidence_span_ids: ["R-EXP-1"],
        },
      ],
      projects: [
        {
          name: "Career Arbor",
          summary: "Evidence-grounded career matching",
          dates: "2026",
          actions: ["Implemented RRF fusion"],
          outcomes: ["Produced traceable recommendations"],
          technologies: ["FastAPI", "pgvector"],
          evidence_span_ids: ["R-PROJ-1"],
        },
      ],
      skills: ["Python", "SQL"],
      resume_quality_issues: ["缺少部分经历的量化结果"],
      evidence: [{ evidence_span_id: "R-EVID-1", content: "Built an async retrieval service." }],
    });
  }

  it("keeps the confirmed profile and state-aware PM welcome in the timeline", async () => {
    mockWorkbenchApi();
    renderWorkbench();

    expect(
      await screen.findByText(
        "欢迎来到职业规划服务群。我是项目经理 PM，小意负责需求、小检负责岗位、小策负责规划，我会在每个环节前后做质量把关。你的简历档案已确认，接下来和小意聊清求职方向就能开始匹配。",
      ),
    ).toBeVisible();
    expect(
      screen.getByText("✅ 简历档案已确认（v1），随时可以点右下档案重新查看。"),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "查看完整档案" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "确认简历档案" })).not.toBeInTheDocument();
  });

  it("opens the confirmed consultation with direction guidance when the transcript is empty", async () => {
    mockWorkbenchApi();
    renderWorkbench();

    expect(
      await screen.findByText(
        '现在告诉我你的求职方向吧——目标岗位、期望地点、签证情况，一句话说清也行；不确定的话切到"探索方向"，我们一起梳理。',
      ),
    ).toBeVisible();
  });

  it("shows mode microcopy and changes the opening guidance for exploration", async () => {
    const user = userEvent.setup();
    mockWorkbenchApi();
    renderWorkbench();

    const targeted = await screen.findByRole("tab", { name: "目标明确" });
    const explore = screen.getByRole("tab", { name: "探索方向" });
    expect(screen.getByText("已有意向岗位，直接补条件")).toBeVisible();
    expect(screen.getByText("不确定方向，小意帮你梳理")).toBeVisible();
    expect(targeted).toHaveAttribute("aria-describedby");
    expect(explore).toHaveAttribute("aria-describedby");
    expect(
      screen.getByText(
        '现在告诉我你的求职方向吧——目标岗位、期望地点、签证情况，一句话说清也行；不确定的话切到"探索方向"，我们一起梳理。',
      ),
    ).toBeVisible();

    await user.click(explore);

    expect(
      screen.getByText("还不确定方向？没关系，切到这里我们先聊聊你的兴趣和优势，一起找方向。"),
    ).toBeVisible();
  });

  it("hides the confirmed-profile continuity card once a run exists", async () => {
    mockWorkbenchApi();
    renderWorkbench("/app/sessions/sess-1?run=run-created");

    expect(
      await screen.findByText(
        "欢迎来到职业规划服务群。我是项目经理 PM，小意负责需求、小检负责岗位、小策负责规划，我会在每个环节前后做质量把关。你的简历档案已确认，接下来和小意聊清求职方向就能开始匹配。",
      ),
    ).toBeVisible();
    expect(
      screen.getAllByText(/欢迎来到职业规划服务群。我是项目经理 PM/),
    ).toHaveLength(1);
    expect(screen.queryByText(/✅ 简历档案已确认/)).not.toBeInTheDocument();
  });

  it("does not repeat the direction guidance when confirmed consultation history exists", async () => {
    mockWorkbenchApi();
    vi.mocked(api.consultState).mockResolvedValue(apiFixtures.consultState(1));
    renderWorkbench();

    expect(await screen.findByText("用户第 1 轮")).toBeVisible();
    expect(
      screen.queryByText(
        '现在告诉我你的求职方向吧——目标岗位、期望地点、签证情况，一句话说清也行；不确定的话切到"探索方向"，我们一起梳理。',
      ),
    ).not.toBeInTheDocument();
  });

  it("preserves the exact unconfirmed PM welcome copy", async () => {
    mockUnconfirmedFullResume();
    renderWorkbench();

    expect(
      await screen.findByText(
        "欢迎来到职业规划服务群。我是项目经理 PM，小意负责需求、小检负责岗位、小策负责规划，我会在每个环节前后做质量把关。先点下方输入框左侧的 📎 把简历发进群（PDF/DOCX/TXT）。",
      ),
    ).toBeVisible();
  });

  it("expands all six preview DTO categories inline without dropping their fields", async () => {
    const user = userEvent.setup();
    mockUnconfirmedFullResume();
    renderWorkbench();

    const trigger = await screen.findByRole("button", { name: "查看完整档案" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("region", { name: "完整简历档案" })).not.toBeInTheDocument();
    await user.click(trigger);

    const profile = screen.getByRole("region", { name: "完整简历档案" });
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    for (const heading of ["教育经历", "工作经历", "项目经历", "技能", "档案质量提示", "原文证据"]) {
      expect(within(profile).getByRole("heading", { name: heading })).toBeVisible();
    }
    // B1 R3：质量提示与原文证据默认折叠，点击展开后内容可见
    expect(within(profile).getByText("缺少部分经历的量化结果")).not.toBeVisible();
    await user.click(within(profile).getByRole("heading", { name: "档案质量提示" }));
    await user.click(within(profile).getByRole("heading", { name: "原文证据" }));
    for (const content of [
      "Birmingham University",
      "Distinction track",
      "Career Lab",
      "Reduced latency by 30%",
      "Career Arbor",
      "Produced traceable recommendations",
      "SQL",
      "缺少部分经历的量化结果",
      "Built an async retrieval service.",
      "R-EVID-1",
    ]) {
      expect(within(profile).getByText(content)).toBeVisible();
    }
  });

  it("routes re-upload through the composer paperclip with an explicit confirm", async () => {
    // B2：三处旧上传入口收敛到 composer 📎；选文件≠上传，确认后才发请求
    const user = userEvent.setup();
    mockUnconfirmedFullResume();
    vi.spyOn(api, "uploadResume").mockResolvedValue(apiFixtures.resumeUploaded());
    renderWorkbench();

    await screen.findByRole("button", { name: "查看完整档案" });
    const attach = screen.getByLabelText("上传简历");
    const input = attach.querySelector("input[type=file]") as HTMLInputElement;
    const replacement = new File(["updated resume"], "updated-resume.txt", { type: "text/plain" });
    await user.upload(input, replacement);

    expect(api.uploadResume).not.toHaveBeenCalled();
    await user.click(await screen.findByRole("button", { name: "确认上传" }));
    await waitFor(() =>
      expect(api.uploadResume).toHaveBeenCalledWith("sess-1", replacement),
    );
  });

  it("shows the re-upload guidance when parse hits 409 resume_ocr_disabled", async () => {
    // OCR 开启期上传的图片，在能力关闭后确认解析会被 409 拒绝；
    // 解析被 409 拒绝（不扣额度）——确认卡原地给出重传文字版引导
    const user = userEvent.setup();
    mockWorkbenchApi();
    vi.mocked(api.resumePreview).mockRejectedValue(new ApiError(409, "resume_unparsed"));
    vi.mocked(api.pendingResumeUpload).mockResolvedValue(
      apiFixtures.resumeUploaded({ filename: "resume.png", ocr_suggested: true }),
    );
    vi.spyOn(api, "parseResume").mockRejectedValue(
      new ApiError(409, "resume_ocr_disabled"),
    );
    renderWorkbench();

    await user.click(await screen.findByRole("button", { name: "确认解析" }));

    expect(
      await screen.findByText(/图片识别功能暂时关闭/),
    ).toBeVisible();
    // 上传仍在场：确认卡不退场，等待用户重传
    expect(screen.getByRole("button", { name: "确认解析" })).toBeVisible();
  });

  it("enables image accept, title, OCR guidance, and 415 copy only when capability is true", async () => {
    const user = userEvent.setup();
    mockWorkbenchApi();
    vi.mocked(api.capabilities).mockResolvedValue(
      apiFixtures.capabilities({ resume_image_upload_enabled: true }),
    );
    vi.mocked(api.resumePreview).mockRejectedValue(new ApiError(409, "resume_unparsed"));
    vi.mocked(api.pendingResumeUpload).mockResolvedValue(
      apiFixtures.resumeUploaded({ ocr_suggested: true }),
    );
    vi.spyOn(api, "uploadResume").mockRejectedValue(new ApiError(415, "unsupported_media_type"));
    renderWorkbench();

    const attach = screen.getByLabelText("上传简历");
    const input = attach.querySelector('input[type="file"]') as HTMLInputElement;
    await waitFor(() =>
      expect(attach).toHaveAttribute("title", "支持 PDF/DOCX/TXT/图片（PNG/JPG/WEBP）"),
    );
    expect(input.accept).toContain(".png");
    expect(input.accept).toContain("image/webp");
    expect(
      await screen.findByText(
        // 方案钉死文案：成本提示（分钱），不是时间提示
        "检测到扫描件/图片，确认解析后小意会用视觉识别读取（约几分钱）。",
        { exact: false },
      ),
    ).toBeVisible();

    await user.upload(input, new File(["resume"], "resume.txt", { type: "text/plain" }));
    await user.click(await screen.findByRole("button", { name: "确认上传" }));
    expect(
      await screen.findByText("暂不支持该文件格式（当前支持 PDF/DOCX/TXT/图片）。"),
    ).toBeVisible();
  });

  it("shows image formats in the PM welcome and Xiaoyi guide when capability is true", async () => {
    mockWorkbenchApi();
    vi.mocked(api.capabilities).mockResolvedValue(
      apiFixtures.capabilities({ resume_image_upload_enabled: true }),
    );
    vi.mocked(api.resumePreview).mockRejectedValue(new ApiError(409, "resume_missing"));
    renderWorkbench();

    await waitFor(() =>
      expect(screen.getByText(/先点下方输入框左侧/)).toHaveTextContent(
        "把简历发进群（PDF/DOCX/TXT/图片）",
      ),
    );
    expect(await screen.findByText(/用下方输入框左侧/)).toHaveTextContent(
      "（PDF/DOCX/TXT/图片）",
    );
  });

  it.each([
    ["false", false],
    ["missing", undefined],
  ])("keeps image upload closed and legacy copy when capability is %s", async (_label, value) => {
    const user = userEvent.setup();
    mockWorkbenchApi();
    const capabilities = apiFixtures.capabilities({ resume_image_upload_enabled: false });
    if (value === undefined) {
      delete (capabilities as Partial<typeof capabilities>).resume_image_upload_enabled;
    }
    vi.mocked(api.capabilities).mockResolvedValue(capabilities);
    vi.mocked(api.resumePreview).mockRejectedValue(new ApiError(409, "resume_unparsed"));
    vi.mocked(api.pendingResumeUpload).mockResolvedValue(
      apiFixtures.resumeUploaded({ ocr_suggested: true }),
    );
    vi.spyOn(api, "uploadResume").mockRejectedValue(new ApiError(415, "unsupported_media_type"));
    renderWorkbench();

    const attach = screen.getByLabelText("上传简历");
    const input = attach.querySelector('input[type="file"]') as HTMLInputElement;
    await waitFor(() =>
      expect(attach).toHaveAttribute("title", "支持 PDF/DOCX/TXT；图片识别即将开放"),
    );
    expect(input.accept).toBe(".pdf,.docx,.txt");
    expect(input.accept).not.toMatch(/\.png|image\/webp/);
    expect(
      await screen.findByText(
        "文字较少，可能是扫描件/图片——图片识别即将开放，建议先换文字版试试。",
        { exact: false },
      ),
    ).toBeVisible();
    expect(screen.getByText(/先点下方输入框左侧/)).toHaveTextContent(
      "把简历发进群（PDF/DOCX/TXT）",
    );

    await user.upload(input, new File(["resume"], "resume.txt", { type: "text/plain" }));
    await user.click(await screen.findByRole("button", { name: "确认上传" }));
    expect(
      await screen.findByText("暂不支持该文件格式（当前支持 PDF/DOCX/TXT）。"),
    ).toBeVisible();
  });

  it("confirms the exact resume version shown in the preview", async () => {
    const user = userEvent.setup();
    mockUnconfirmedFullResume();
    vi.spyOn(api, "confirmResume").mockResolvedValue({
      session_id: "sess-1",
      resume_version: 2,
      confirmed: true,
      confirmed_at: "2026-08-07T09:01:00Z",
    });
    renderWorkbench();

    await user.click(await screen.findByRole("button", { name: "确认简历档案" }));

    await waitFor(() =>
      expect(api.confirmResume).toHaveBeenCalledWith("sess-1", {
        expected_resume_version: 2,
      }),
    );
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

describe("truthful result cards", () => {
  function mockCompletedResult() {
    mockWorkbenchApi();
    vi.mocked(api.runStatus).mockResolvedValue(
      apiFixtures.runStatus({
        status: "completed",
        stage: "finalization",
        completedStages: RUN_STAGES,
        resultReady: true,
        retryAfterMs: null,
      }),
    );
    vi.mocked(api.runConversation).mockResolvedValue(apiFixtures.runConversation("completed", null));
    vi.spyOn(api, "capabilities").mockResolvedValue(apiFixtures.capabilities());
  }

  it("publishes strategist analysis, a strategist result table, then the PM closing", async () => {
    mockCompletedResult();
    vi.spyOn(api, "runResult").mockResolvedValue(apiFixtures.runResult(1));

    renderWorkbench("/app/sessions/sess-1?run=run-created");

    const analysis = await screen.findByText(/岗位分析完成：Now Fit/);
    const results = await screen.findByRole("region", { name: "匹配结果" });
    const closing = screen.getByText(/结果已发布。投递后欢迎回来/);
    expect(analysis.closest(".v2-msg")).toHaveAttribute("data-persona", "strategist");
    expect(results.closest(".v2-msg")).toHaveAttribute("data-persona", "strategist");
    expect(closing.closest(".v2-msg")).toHaveAttribute("data-persona", "pm");
    expect(analysis.compareDocumentPosition(results) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(results.compareDocumentPosition(closing) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(closing).toHaveTextContent("不构成 offer 承诺");
  });

  it("shows a compact table and expands only the selected job with aria state", async () => {
    const user = userEvent.setup();
    mockCompletedResult();
    vi.spyOn(api, "runResult").mockResolvedValue(apiFixtures.runResult(2));

    renderWorkbench("/app/sessions/sess-1?run=run-created");

    const table = await screen.findByRole("table", { name: "岗位推荐列表" });
    for (const heading of ["#", "分层", "岗位名", "公司·地点", "语料标签"]) {
      expect(within(table).getByRole("columnheader", { name: heading })).toBeVisible();
    }
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "被拒" })).not.toBeInTheDocument();

    const first = within(table).getByRole("button", { name: "查看 Backend Engineer 详情" });
    const second = within(table).getByRole("button", { name: "查看 Backend Engineer 2 详情" });
    expect(first).toHaveAttribute("aria-expanded", "false");
    await user.click(first);
    expect(first).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("article", { name: "Backend Engineer 详情" })).toBeVisible();

    await user.click(second);
    expect(first).toHaveAttribute("aria-expanded", "false");
    expect(second).toHaveAttribute("aria-expanded", "true");
    expect(screen.queryByRole("article", { name: "Backend Engineer 详情" })).not.toBeInTheDocument();
    expect(screen.getByRole("article", { name: "Backend Engineer 2 详情" })).toBeVisible();
  });

  it("mounts the existing reaction form only after the in-card progress disclosure", async () => {
    const user = userEvent.setup();
    mockCompletedResult();
    vi.spyOn(api, "runResult").mockResolvedValue(apiFixtures.runResult(1));

    renderWorkbench("/app/sessions/sess-1?run=run-created");

    const row = await screen.findByRole("button", { name: "查看 Backend Engineer 详情" });
    expect(screen.queryByRole("button", { name: "被拒" })).not.toBeInTheDocument();
    await user.click(row);

    const progress = screen.getByRole("button", { name: "提交进展" });
    expect(progress).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("button", { name: "被拒" })).not.toBeInTheDocument();
    await user.click(progress);

    expect(screen.getByRole("button", { name: "被拒" })).toBeVisible();
    expect(screen.getByRole("button", { name: "过筛" })).toBeVisible();
    expect(progress).toHaveAttribute("aria-expanded", "true");
  });

  it("covers the full ranking rule and shows only truth-sourced capability chips", async () => {
    mockCompletedResult();
    vi.spyOn(api, "runResult").mockResolvedValue(apiFixtures.runResult(5));

    renderWorkbench("/app/sessions/sess-1?run=run-created");

    const results = await screen.findByRole("region", { name: "匹配结果" });
    expect(await within(results).findByText("混合检索（BM25+语义双路）")).toBeVisible();
    expect(await within(results).findByText("支持双空间增强")).toBeVisible();
    for (const rank of ["①", "②", "③", "4.", "5."]) {
      expect(within(results).getByText(rank)).toBeVisible();
    }
    expect(results).not.toHaveTextContent(/RAPTOR|Cross|匹配强度|%/i);
  });

  it("links only http(s) source URLs and exposes demo context without hover", async () => {
    const user = userEvent.setup();
    mockCompletedResult();
    const result = apiFixtures.runResult(2);
    result.result.recommended_roles![0].source_url = "https://jobs.example.com/role-1";
    result.result.recommended_roles![0].listing_kind = "source_url";
    result.result.recommended_roles![1].source_url = "javascript:alert(1)";
    result.result.recommended_roles![1].listing_kind = "source_url";
    vi.spyOn(api, "runResult").mockResolvedValue(result);

    renderWorkbench("/app/sessions/sess-1?run=run-created");

    const table = await screen.findByRole("table", { name: "岗位推荐列表" });
    await user.click(within(table).getByRole("button", { name: "查看 Backend Engineer 详情" }));
    const firstCard = screen.getByRole("article", { name: "Backend Engineer 详情" });
    const sourceLink = within(firstCard).getByRole("link", { name: "查看原岗位 ↗" });
    expect(sourceLink).toHaveAttribute("href", "https://jobs.example.com/role-1");
    expect(sourceLink).toHaveAttribute("rel", "noopener noreferrer");

    const demoDisclosure = within(firstCard).getByRole("button", { name: /演示数据 · CN/ });
    await user.click(demoDisclosure);
    expect(within(firstCard).getByText(/合成演示语料/)).toBeVisible();

    await user.click(within(table).getByRole("button", { name: "查看 Backend Engineer 2 详情" }));
    const secondCard = screen.getByRole("article", { name: "Backend Engineer 2 详情" });
    expect(within(secondCard).queryByRole("link", { name: "查看原岗位 ↗" })).not.toBeInTheDocument();
  });

  it("maps all three result actions to existing evidence, progress, and new-consult interactions", async () => {
    const user = userEvent.setup();
    mockCompletedResult();
    vi.spyOn(api, "runResult").mockResolvedValue(apiFixtures.runResult(1));

    renderWorkbench("/app/sessions/sess-1?run=run-created");

    const actions = await screen.findByRole("group", { name: "结果后续行动" });
    expect(within(actions).getAllByRole("button")).toHaveLength(3);

    const evidenceAction = within(actions).getByRole("button", { name: "查看第 1 名的证据" });
    await user.click(evidenceAction);
    expect(await screen.findByText("Python, SQL required.")).toBeVisible();
    const evidenceTrigger = screen.getByRole("button", { name: "查看证据" });
    expect(evidenceTrigger).toHaveAttribute("aria-expanded", "true");
    await user.click(evidenceAction);
    expect(evidenceTrigger).toHaveAttribute("aria-expanded", "true");

    await user.click(within(actions).getByRole("button", { name: "更新申请进展" }));
    expect(screen.getByRole("button", { name: "被拒" })).toHaveFocus();

    await user.click(within(actions).getByRole("button", { name: "新建咨询细化方向" }));
    expect(screen.getByRole("dialog", { name: "新建咨询确认" })).toHaveTextContent(
      "创建成功后可继续细化方向",
    );
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

describe("resume-generation conflict recovery", () => {
  it("polls only the preview processing lifecycle state", () => {
    expect(resumePreviewInterval(new ApiError(409, "resume_processing"))).toBe(2500);
    expect(resumePreviewInterval(new ApiError(409, "resume_error"))).toBe(false);
    expect(resumePreviewInterval(new ApiError(500, "server_error"))).toBe(false);
  });

  it("renders preview resume_processing as processing without an upload entry", async () => {
    mockWorkbenchApi();
    vi.mocked(api.resumePreview).mockRejectedValue(new ApiError(409, "resume_processing"));

    renderWorkbench();

    expect(await screen.findByText(/正在归一化你的简历/)).toBeVisible();
    expect(screen.queryByText("选择简历文件")).not.toBeInTheDocument();
  });

  it("stops on preview resume_error and offers an explicit re-upload action", async () => {
    mockWorkbenchApi();
    vi.mocked(api.resumePreview).mockRejectedValue(new ApiError(409, "resume_error"));

    renderWorkbench();

    expect(
      await screen.findByText("这份文件我没能整理成功，旧档案已作废。"),
    ).toBeVisible();
    // B2：重传入口收敛到 composer 📎，错误气泡只做引导
    expect(screen.getByText(/重新发一份给我/)).toBeVisible();
    expect(screen.getByLabelText("上传简历")).toBeVisible();
  });

  it("uses lifecycle recovery for confirm and clears it after a successful retry", async () => {
    const user = userEvent.setup();
    mockWorkbenchApi();
    vi.mocked(api.resumePreview).mockResolvedValue(apiFixtures.resumePreview(false));
    vi.spyOn(api, "confirmResume")
      .mockRejectedValueOnce(new ApiError(409, "resume_processing"))
      .mockResolvedValueOnce({
        session_id: "sess-1",
        resume_version: 1,
        confirmed: true,
        confirmed_at: "2026-08-07T00:00:00Z",
      });
    renderWorkbench();

    const confirm = await screen.findByRole("button", { name: "确认简历档案" });
    await user.click(confirm);
    expect(await screen.findByText("简历已更新，本轮未提交；请确认新档案后重试")).toBeVisible();

    await user.click(confirm);
    await waitFor(() => expect(api.confirmResume).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(
        screen.queryByText("简历已更新，本轮未提交；请确认新档案后重试"),
      ).not.toBeInTheDocument(),
    );
  });

  it.each([
    ["finalize", "resume_processing", "生成确认单"],
    ["match-brief", "resume_error", "确认无误，开始匹配"],
  ])("uses lifecycle recovery for %s conflicts", async (operation, detail, buttonName) => {
    const user = userEvent.setup();
    mockWorkbenchApi();
    if (operation === "finalize") {
      vi.mocked(api.consultFinalize).mockRejectedValue(new ApiError(409, detail));
    } else {
      vi.mocked(api.createMatchBrief).mockRejectedValue(new ApiError(409, detail));
    }
    const { queryClient } = renderWorkbench();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    if (operation === "match-brief") {
      await user.click(await screen.findByRole("button", { name: "生成确认单" }));
    }
    await user.click(await screen.findByRole("button", { name: buttonName }));

    const lifecycleMessages = await screen.findAllByText(
      detail === "resume_error"
        ? "旧档案已作废，请重传"
        : "简历已更新，本轮未提交；请确认新档案后重试",
    );
    expect(lifecycleMessages[0]).toBeVisible();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["resume-preview", "sess-1"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["consult", "sess-1"] });
  });

  it("keeps the turn draft, clears the stale brief, refetches both resources, and advances the two-stage copy", async () => {
    const user = userEvent.setup();
    mockWorkbenchApi();
    const initialPreview = apiFixtures.resumePreview(true);
    let resolvePreview!: (value: typeof initialPreview) => void;
    const refreshedPreview = new Promise<typeof initialPreview>((resolve) => {
      resolvePreview = resolve;
    });
    vi.mocked(api.resumePreview)
      .mockResolvedValueOnce(initialPreview)
      .mockImplementation(() => refreshedPreview);
    vi.spyOn(api, "consultTurn").mockRejectedValue(new ApiError(409, "resume_changed"));
    const { queryClient } = renderWorkbench();
    const input = await screen.findByPlaceholderText(/告诉小意你的想法/);
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    await user.click(screen.getByRole("button", { name: "生成确认单" }));
    expect(await screen.findByText("需求摘要（Match Brief）")).toBeVisible();
    await user.type(input, "保留这段尚未提交的输入");
    await user.click(screen.getByRole("button", { name: "发送" }));

    expect(await screen.findByText("新简历处理中")).toBeVisible();
    expect(input).toHaveValue("保留这段尚未提交的输入");
    expect(screen.queryByText("需求摘要（Match Brief）")).not.toBeInTheDocument();
    expect(api.consultTurn).toHaveBeenCalledTimes(1);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["resume-preview", "sess-1"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["consult", "sess-1"] });

    const updatedPreview = apiFixtures.resumePreview(false);
    updatedPreview.resume_version = 2;
    act(() => resolvePreview(updatedPreview));
    expect(
      await screen.findByText("简历已更新，本轮未提交；请确认新档案后重试"),
    ).toBeVisible();
    expect(api.consultTurn).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["resume_processing", "新简历处理中"],
    ["resume_error", "旧档案已作废，请重传"],
  ])("routes %s without replaying the pending input", async (detail, expectedCopy) => {
    const user = userEvent.setup();
    mockWorkbenchApi();
    vi.mocked(api.resumePreview)
      .mockResolvedValueOnce(apiFixtures.resumePreview(true))
      .mockRejectedValue(new ApiError(409, detail));
    vi.spyOn(api, "consultTurn").mockRejectedValue(new ApiError(409, detail));
    renderWorkbench();

    const input = await screen.findByPlaceholderText(/告诉小意你的想法/);
    await user.type(input, "这条输入不能自动重放");
    await user.click(screen.getByRole("button", { name: "发送" }));

    const recoveryMessages = await screen.findAllByText(expectedCopy);
    expect(recoveryMessages.length).toBeGreaterThan(0);
    expect(recoveryMessages.every((message) => message.isConnected)).toBe(true);
    expect(input).toHaveValue("这条输入不能自动重放");
    expect(api.consultTurn).toHaveBeenCalledTimes(1);
  });
});

describe("workbench query failures", () => {
  it("shows a retry action for non-lifecycle preview errors", async () => {
    const user = userEvent.setup();
    mockWorkbenchApi();
    vi.mocked(api.resumePreview)
      .mockRejectedValueOnce(new ApiError(500, "server_error"))
      .mockResolvedValueOnce(apiFixtures.resumePreview(true));
    renderWorkbench();

    expect(await screen.findByText("简历档案加载失败，请重试")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "重试加载简历档案" }));

    await waitFor(() => expect(api.resumePreview).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(screen.queryByText("简历档案加载失败，请重试")).not.toBeInTheDocument(),
    );
    expect(await screen.findByRole("button", { name: "生成确认单" })).toBeEnabled();
  });

  it("shows a retry action for consult GET failures and keeps sending disabled until ready", async () => {
    const user = userEvent.setup();
    mockWorkbenchApi();
    vi.mocked(api.consultState)
      .mockRejectedValueOnce(new ApiError(500, "server_error"))
      .mockResolvedValueOnce({
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
    renderWorkbench();

    expect(await screen.findByText("咨询状态加载失败，请重试")).toBeVisible();
    expect(screen.getByRole("button", { name: "发送" })).toBeDisabled();
    expect(screen.getByRole("textbox")).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "重试加载咨询状态" }));
    await waitFor(() => expect(api.consultState).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByRole("textbox")).toBeEnabled());
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
    await screen.findByText(
      "我已接手确认单，岗位检索正在执行：适用的 metadata 条件筛选 → BM25/Dense 并行 → job_id 级 RRF 融合。你要求的 Shanghai 我已锁定为硬条件，绝不放宽。",
    );

    const timeline = document.querySelector<HTMLOListElement>(".v2-timeline");
    expect(timeline).not.toBeNull();
    setTimelineMetrics(timeline!, { scrollHeight: 1000, clientHeight: 400, scrollTop: 479 });
    const secondMessage = {
      seq: 5,
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
            seq: 6,
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

  it("treats a same-seq stage or text replacement as new timeline content", async () => {
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
    const firstConversation = {
      ...apiFixtures.runConversation("running", null),
      messages: [
        {
          seq: 2,
          persona: "job_scout" as const,
          display_name: "岗位顾问·小检",
          kind: "progress" as const,
          stage: "retrieval",
          text: "正在筛选岗位",
        },
      ],
    };
    vi.mocked(api.runConversation).mockResolvedValue(firstConversation);
    const { queryClient } = renderWorkbench("/app/sessions/sess-1?run=run-created");
    await screen.findByText("正在筛选岗位");

    const timeline = document.querySelector<HTMLOListElement>(".v2-timeline");
    expect(timeline).not.toBeNull();
    setTimelineMetrics(timeline!, { scrollHeight: 1000, clientHeight: 400, scrollTop: 200 });
    act(() => {
      queryClient.setQueryData(["v2-run-conv", "run-created"], {
        ...firstConversation,
        messages: [
          {
            ...firstConversation.messages[0],
            stage: "strategy",
            text: "正在整理规划建议",
          },
        ],
      });
    });

    expect(await screen.findByRole("button", { name: "↓ 有新消息" })).toBeVisible();
    expect(timeline!.scrollTop).toBe(200);
  });

  it("treats a refetched note on the same transcript round as a new rendered bubble", async () => {
    mockWorkbenchApi();
    const initial = apiFixtures.consultState(1);
    vi.mocked(api.consultState).mockResolvedValue(initial);
    const { queryClient } = renderWorkbench();
    await screen.findByText(/明白了（第 1 轮）/);

    const timeline = document.querySelector<HTMLOListElement>(".v2-timeline");
    expect(timeline).not.toBeNull();
    setTimelineMetrics(timeline!, { scrollHeight: 1000, clientHeight: 400, scrollTop: 200 });
    const note = apiFixtures.supervisorNote({ text: "同轮返回的 PM 督导建议。" });
    act(() => {
      queryClient.setQueryData(
        ["consult", "sess-1"],
        apiFixtures.consultState(1, { supervisor_notes: [note] }),
      );
    });

    expect(await screen.findByText(note.text)).toBeVisible();
    expect(await screen.findByRole("button", { name: "↓ 有新消息" })).toBeVisible();
    expect(timeline!.scrollTop).toBe(200);
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
    const firstResultRow = resultAnchor.querySelector<HTMLElement>(".v2-result-row");
    expect(firstResultRow).not.toBeNull();
    const regionScrollIntoView = vi.fn();
    const rowScrollIntoView = vi.fn();
    Object.defineProperty(resultAnchor, "scrollIntoView", {
      configurable: true,
      value: regionScrollIntoView,
    });
    Object.defineProperty(firstResultRow!, "scrollIntoView", {
      configurable: true,
      value: rowScrollIntoView,
    });
    await user.click(resultButton);

    expect(rowScrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "start" });
    expect(regionScrollIntoView).not.toHaveBeenCalled();
    expect(firstResultRow).toHaveClass("is-highlighted");
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
    expect(localStorage.getItem("title:user-1:sess-1")).toBe("backend engi");
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

  it("groups consecutive personas, inserts stage sections, and exposes stage-only metadata", async () => {
    mockWorkbenchApi();
    vi.mocked(api.runStatus).mockResolvedValue(
      apiFixtures.runStatus({
        status: "running",
        stage: "verification",
        completedStages: ["resume", "intent", "retrieval", "strategy"],
        resultReady: false,
        retryAfterMs: null,
      }),
    );
    vi.mocked(api.runConversation).mockResolvedValue({
      run_id: "run-created",
      status: "running",
      stage: "verification",
      next_poll_ms: null,
      messages: [
        {
          seq: 2,
          persona: "job_scout",
          display_name: "岗位顾问·小检",
          kind: "progress",
          stage: "retrieval",
          text: "开始筛选岗位",
        },
        {
          seq: 3,
          persona: "job_scout",
          display_name: "岗位顾问·小检",
          kind: "progress",
          stage: "retrieval",
          text: "岗位检索已完成",
        },
        {
          seq: 4,
          persona: "pm",
          display_name: "项目经理·PM",
          kind: "checkpoint",
          stage: "verification",
          text: "进入发布核查",
        },
      ],
    });
    renderWorkbench("/app/sessions/sess-1?run=run-created");

    expect(await screen.findByRole("separator", { name: "运行阶段：岗位检索" })).toBeVisible();
    expect(screen.getByRole("separator", { name: "运行阶段：发布核查" })).toBeVisible();
    const groupedMessage = screen.getByText("岗位检索已完成").closest(".v2-msg");
    expect(groupedMessage).toHaveAttribute("data-grouped", "true");
    expect(groupedMessage?.querySelector(".v2-avatar")).not.toBeInTheDocument();
    expect(within(groupedMessage as HTMLElement).getByText("阶段 · 岗位检索")).toHaveAttribute(
      "data-meta-kind",
      "stage",
    );
    expect(groupedMessage?.querySelector('[data-meta-kind="round"]')).not.toBeInTheDocument();
    expect(groupedMessage).toHaveAttribute("tabindex", "0");
  });

  it("shows round-only metadata on consultation messages", async () => {
    mockWorkbenchApi();
    vi.mocked(api.consultState).mockResolvedValue({
      transcript: [
        {
          round: 3,
          user_message: "我不需要签证担保",
          assistant_reply: "签证情况已记录。",
          next_question: "还有想补充的吗？",
          phase: "deepen",
        },
      ],
      profile_draft: {
        current_goal: ["Backend engineer"],
        hard_constraints: { locations: ["Shanghai"], need_visa_sponsor: false },
        soft_preferences: {},
        avoid_roles: [],
      },
      round: 3,
      phase: "deepen",
      completeness: 0.6,
      can_finalize: true,
    });
    renderWorkbench();

    const userMessage = (await screen.findByText("我不需要签证担保")).closest(".v2-msg");
    const assistantMessage = screen.getByText(/签证情况已记录/).closest(".v2-msg");
    for (const message of [userMessage, assistantMessage]) {
      expect(within(message as HTMLElement).getByText("第 3 轮")).toHaveAttribute(
        "data-meta-kind",
        "round",
      );
      expect(message?.querySelector('[data-meta-kind="stage"]')).not.toBeInTheDocument();
      expect(message).toHaveAttribute("tabindex", "0");
    }
  });
});

describe("resume lifecycle regressions (audit round 3)", () => {
  const READY_PREVIEW = {
    session_id: "sess-x",
    resume_version: 1,
    confirmed: false,
    education: [],
    experience: [],
    projects: [],
    skills: ["Python"],
    resume_quality_issues: [],
    evidence: [],
  };

  function renderWithRouter(initialEntry: string) {
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
    return router;
  }

  it("resets pending upload state on session switch so a fresh session shows the entry", async () => {
    // B2 泄漏形态升级：A 会话选中的待上传文件/限额 409 不得带进 B 会话
    const user = userEvent.setup();
    mockWorkbenchApi();
    vi.mocked(api.resumePreview).mockImplementation(async () => {
      throw new ApiError(409, "resume_missing");
    });
    const router = renderWithRouter("/app/sessions/sess-1");

    expect(await screen.findByText(/就能发/)).toBeVisible();
    const attach = screen.getByLabelText("上传简历");
    const fileInput = attach.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(fileInput, new File(["resume"], "r.txt", { type: "text/plain" }));
    expect(await screen.findByRole("button", { name: "确认上传" })).toBeVisible();

    await act(async () => {
      await router.navigate("/app/sessions/sess-2");
    });

    expect(screen.queryByRole("button", { name: "确认上传" })).not.toBeInTheDocument();
    expect(await screen.findByText(/就能发/)).toBeVisible();
    expect(screen.queryByText(/正在归一化你的简历/)).not.toBeInTheDocument();
  });

  it("exits stale confirm card into processing when parse hits resume_processing", async () => {
    // 双标签页并发确认解析：慢的一方收到 409 resume_processing，必须刷新
    // 双查询——确认卡经 GET 404 退场、preview 409 进入处理中（对侧抽查 r2-M4）
    const user = userEvent.setup();
    mockWorkbenchApi();
    let raced = false;
    vi.mocked(api.resumePreview).mockImplementation(async () => {
      throw new ApiError(409, raced ? "resume_processing" : "resume_unparsed");
    });
    vi.mocked(api.pendingResumeUpload).mockImplementation(async () => {
      if (!raced) return apiFixtures.resumeUploaded();
      throw new ApiError(404, "no pending resume upload");
    });
    vi.spyOn(api, "parseResume").mockImplementation(async () => {
      raced = true;
      throw new ApiError(409, "resume_processing");
    });
    renderWithRouter("/app/sessions/sess-1");

    await user.click(await screen.findByRole("button", { name: "确认解析" }));

    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "确认解析" })).not.toBeInTheDocument(),
    );
    expect(await screen.findByText(/正在归一化你的简历/)).toBeVisible();
  });

  it("recovers from resume_error through re-upload and confirm-parse to a ready profile", async () => {
    const user = userEvent.setup();
    mockWorkbenchApi();
    let phase: "error" | "unparsed" | "ready" = "error";
    vi.mocked(api.resumePreview).mockImplementation(async () => {
      if (phase === "error") throw new ApiError(409, "resume_error");
      if (phase === "unparsed") throw new ApiError(409, "resume_unparsed");
      return READY_PREVIEW;
    });
    vi.mocked(api.pendingResumeUpload).mockImplementation(async () => {
      if (phase === "unparsed") return apiFixtures.resumeUploaded();
      throw new ApiError(404, "no pending resume upload");
    });
    vi.spyOn(api, "uploadResume").mockImplementation(async () => {
      phase = "unparsed";
      return apiFixtures.resumeUploaded();
    });
    vi.spyOn(api, "parseResume").mockImplementation(async () => {
      phase = "ready";
      return { session_id: "sess-1", status: "resume_queued" };
    });
    renderWithRouter("/app/sessions/sess-1");

    expect(await screen.findByText(/旧档案已作废/)).toBeVisible();
    const attach = screen.getByLabelText("上传简历");
    const fileInput = attach.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(fileInput, new File(["resume"], "r2.txt", { type: "text/plain" }));
    await user.click(await screen.findByRole("button", { name: "确认上传" }));

    await user.click(await screen.findByRole("button", { name: "确认解析" }));

    await screen.findByRole("button", { name: "确认简历档案" });
    expect(screen.queryByText(/旧档案已作废/)).not.toBeInTheDocument();
  });
});


describe("useStaggeredReveal (B1 R5)", () => {
  function HookProbe({ keys, resetKey }: { keys: string[]; resetKey: string }) {
    const style = useStaggeredReveal(keys, resetKey);
    return (
      <ul>
        {keys.map((key) => (
          <li key={key} data-testid={key} style={style(key)} />
        ))}
      </ul>
    );
  }

  function delayOf(key: string): string {
    return screen.getByTestId(key).style.animationDelay;
  }

  it("treats the first non-empty batch as history baseline (no replay after async load)", () => {
    // 冷加载时序：resetKey 变化帧无数据 → 首批全量历史异步到达。
    const { rerender } = render(<HookProbe keys={[]} resetKey="s1:r1" />);
    rerender(<HookProbe keys={["a", "b", "c"]} resetKey="s1:r1" />);
    for (const key of ["a", "b", "c"]) expect(delayOf(key)).toBe("");
  });

  it("freshBaseline staggers even the very first batch (self-initiated narration, Codex C8)", () => {
    function FreshProbe({ keys, resetKey }: { keys: string[]; resetKey: string }) {
      const style = useStaggeredReveal(keys, resetKey, true);
      return (
        <ul>
          {keys.map((key) => (
            <li key={key} data-testid={key} style={style(key)} />
          ))}
        </ul>
      );
    }
    // 自发解析：首轮轮询同拍返回的 received/extracted/normalizing 也要逐条
    const { rerender } = render(<FreshProbe keys={[]} resetKey="s1:g1" />);
    rerender(<FreshProbe keys={["e1", "e2", "e3"]} resetKey="s1:g1" />);
    expect(delayOf("e1")).toBe("");
    expect(delayOf("e2")).toBe("450ms");
    expect(delayOf("e3")).toBe("900ms");
  });

  it("staggers only messages added after the baseline, capped at 3 steps", () => {
    const { rerender } = render(<HookProbe keys={["a"]} resetKey="s1:r1" />);
    rerender(
      <HookProbe keys={["a", "b", "c", "d", "e", "f", "g"]} resetKey="s1:r1" />,
    );
    expect(delayOf("a")).toBe("");
    expect(delayOf("b")).toBe("");
    expect(delayOf("c")).toBe("450ms");
    expect(delayOf("d")).toBe("900ms");
    expect(delayOf("e")).toBe("1350ms");
    // 封顶：1350ms < 1500ms 轮询间隔，后批不会先于前批可见
    expect(delayOf("f")).toBe("1350ms");
    expect(delayOf("g")).toBe("1350ms");
  });

  it("does not replay on re-render and resets baseline on resetKey change", () => {
    const { rerender } = render(<HookProbe keys={["a"]} resetKey="s1:r1" />);
    rerender(<HookProbe keys={["a", "b"]} resetKey="s1:r1" />);
    expect(delayOf("b")).toBe("");
    rerender(<HookProbe keys={["a", "b"]} resetKey="s1:r1" />);
    expect(delayOf("b")).toBe("");
    // 切 run：首个非空批次成为新基线，不编排
    rerender(<HookProbe keys={["x", "y"]} resetKey="s1:r2" />);
    for (const key of ["x", "y"]) expect(delayOf(key)).toBe("");
  });
});

describe("useStaggeredReveal concurrent safety (B1 review r3)", () => {
  it("stays correct when a render is discarded by Suspense (Codex counterexample)", async () => {
    // 反例时序：committed 基线 {a} → 渲染 [a,b,c] 后同组件 suspend（整帧
    // 丢弃、effect 未跑）→ 提交帧 [a,b,c,d]：fresh=[b,c,d]，d 必须是
    // 900ms。旧实现（渲染期写 ref）在此路径下 d 会退化为 0ms。
    const gate = new Promise<void>(() => {});
    function Inner({ keys, suspend }: { keys: string[]; suspend: boolean }) {
      const style = useStaggeredReveal(keys, "suspense-run");
      if (suspend) throw gate;
      return (
        <ul>
          {keys.map((key) => (
            <li key={key} data-testid={`sus-${key}`} style={style(key)} />
          ))}
        </ul>
      );
    }
    const view = render(
      <React.Suspense fallback={<p>loading</p>}>
        <Inner keys={["a"]} suspend={false} />
      </React.Suspense>,
    );
    view.rerender(
      <React.Suspense fallback={<p>loading</p>}>
        <Inner keys={["a", "b", "c"]} suspend={true} />
      </React.Suspense>,
    );
    view.rerender(
      <React.Suspense fallback={<p>loading</p>}>
        <Inner keys={["a", "b", "c", "d"]} suspend={false} />
      </React.Suspense>,
    );
    expect(screen.getByTestId("sus-a").style.animationDelay).toBe("");
    expect(screen.getByTestId("sus-b").style.animationDelay).toBe("");
    expect(screen.getByTestId("sus-c").style.animationDelay).toBe("450ms");
    expect(screen.getByTestId("sus-d").style.animationDelay).toBe("900ms");
  });
});

describe("resume intake narration (B3 R2/R6)", () => {
  const NARRATION_PREVIEW = {
    session_id: "sess-1",
    resume_version: 1,
    confirmed: false,
    education: [
      {
        institution: "伯明翰大学",
        degree: "MSc Data Science",
        field: "",
        dates: "2024-2025",
        details: [],
        evidence_span_ids: ["S001"],
      },
    ],
    experience: [
      {
        organization: "字节跳动",
        title: "数据分析实习生",
        dates: "2023",
        location: "",
        responsibilities: [],
        achievements: [],
        technologies: [],
        evidence_span_ids: ["S002"],
      },
    ],
    projects: [
      {
        name: "简历匹配系统",
        dates: "",
        summary: "",
        actions: [],
        technologies: [],
        outcomes: [],
        evidence_span_ids: ["S003"],
      },
    ],
    skills: ["Python", "SQL"],
    resume_quality_issues: [],
    evidence: [],
  };

  it("polls every 1200ms until done then stops", () => {
    expect(resumeProgressInterval(undefined)).toBe(1200);
    expect(resumeProgressInterval({ done: false })).toBe(1200);
    expect(resumeProgressInterval({ done: true })).toBe(false);
  });

  it("builds the line-by-line profile summary from preview data", () => {
    const lines = buildProfileSummaryLines(NARRATION_PREVIEW);
    expect(lines[0]).toContain("伯明翰大学");
    expect(lines[1]).toContain("字节跳动 · 数据分析实习生");
    expect(lines[2]).toContain("简历匹配系统");
    expect(lines[3]).toContain("Python");
    expect(lines.at(-1)).toContain("完整档案");
    expect(buildProfileSummaryLines(undefined)).toEqual([]);
  });

  it("streams Xiaoyi narration during parsing and lands in an animated line-by-line summary with elapsed time", async () => {
    mockWorkbenchApi();
    let phase: "processing" | "ready" = "processing";
    vi.mocked(api.resumePreview).mockImplementation(async () => {
      if (phase === "processing") throw new ApiError(409, "resume_processing");
      return NARRATION_PREVIEW;
    });
    const narrationEvents = [
      {
        seq: 1,
        step: "received",
        text: "收到！我现在就把你的简历完整读一遍～",
        elapsed_ms: 6,
        created_at: "2026-08-09T10:00:00Z",
      },
      {
        seq: 2,
        step: "extracted",
        text: "读完啦！我从简历里整理出 12 条原文片段。",
        elapsed_ms: 60,
        created_at: "2026-08-09T10:00:01Z",
      },
    ];
    const doneEvent = {
      seq: 100,
      step: "done",
      text: "档案生成完毕，用时 3.2 秒。来看看整理结果吧！",
      elapsed_ms: 3200,
      created_at: "2026-08-09T10:00:04Z",
    };
    vi.mocked(api.resumeProgress).mockImplementation(async () =>
      phase === "processing"
        ? {
            generation: 1,
            status: "resume_queued",
            // 纵深防御夹具（Codex 二轮 m3 更正口径）：服务端已单快照
            // （C6 repeatable read），该形态只可能来自异常/迟到响应——
            // 叙事仍必须过滤终态事件（子 agent 审查 Major：钉死 seq<100）
            events: [...narrationEvents, doneEvent],
            done: false,
          }
        : {
            generation: 1,
            status: "resume_ready",
            events: [...narrationEvents, doneEvent],
            done: true,
          },
    );
    renderWorkbench();

    // 叙事气泡逐条进群（终态 seq=100 不作为叙事气泡渲染）
    expect(await screen.findByText(/收到！我现在就把你的简历完整读一遍/)).toBeVisible();
    expect(screen.getByText(/读完啦/)).toBeVisible();
    expect(screen.getByText(/小意整理中/)).toBeVisible();
    // 解析中：终态文本绝不能以叙事气泡形式提前出现
    expect(screen.queryByText(/用时 3.2 秒/)).not.toBeInTheDocument();

    // 下一拍轮询返回 done → 停轮询并刷新 preview → 档案摘要接棒
    phase = "ready";
    expect(await screen.findByText(/用时 3.2 秒/, undefined, { timeout: 5000 })).toBeVisible();
    await screen.findByRole("button", { name: "确认简历档案" });
    expect(screen.queryByText(/小意整理中/)).not.toBeInTheDocument();

    // 亲历解析的挂载：逐行 350ms 递进（reduced-motion 由 theme.css 全局归零）
    const lines = document.querySelectorAll(".v2-profile-line");
    expect(lines.length).toBeGreaterThanOrEqual(4);
    expect((lines[0] as HTMLElement).style.animationDelay).toBe("0ms");
    expect((lines[1] as HTMLElement).style.animationDelay).toBe("350ms");
  });

  it("backfills the terminal done event exactly once when preview wins the race", async () => {
    // Codex C4 反向竞态回归钉死（子 agent 二轮 minor）：preview 先翻 ready
    // → 进度查询停用时缓存里还没有 seq=100 → 补拉 effect 恰好一次 refetch
    // 把"用时 X.X 秒"拉回来；此后查询已停用+ref 防重，不再有请求。
    mockWorkbenchApi();
    let previewReady = false;
    let progressServesDone = false;
    let progressCalls = 0;
    vi.mocked(api.resumePreview).mockImplementation(async () => {
      if (!previewReady) throw new ApiError(409, "resume_processing");
      return NARRATION_PREVIEW;
    });
    const receivedEvent = {
      seq: 1,
      step: "received",
      text: "收到！我现在就把你的简历完整读一遍～",
      elapsed_ms: 6,
      created_at: "2026-08-09T10:00:00Z",
    };
    vi.mocked(api.resumeProgress).mockImplementation(async () => {
      progressCalls += 1;
      if (!progressServesDone) {
        return {
          generation: 1,
          status: "resume_queued",
          events: [receivedEvent],
          done: false,
        };
      }
      return {
        generation: 1,
        status: "resume_ready",
        events: [
          receivedEvent,
          {
            seq: 100,
            step: "done",
            text: "档案生成完毕，用时 3.2 秒。来看看整理结果吧！",
            elapsed_ms: 3200,
            created_at: "2026-08-09T10:00:04Z",
          },
        ],
        done: true,
      };
    });
    const { queryClient } = renderWorkbench();

    expect(await screen.findByText(/收到！我现在就把你的简历完整读一遍/)).toBeVisible();
    expect(progressCalls).toBe(1);

    // 服务端已达终态；preview 抢先翻 ready（progress 下一拍还没到就被停用）
    progressServesDone = true;
    previewReady = true;
    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: ["resume-preview", "sess-1"] });
    });

    expect(await screen.findByText(/用时 3.2 秒/)).toBeVisible();
    // 恰好一次补拉：首拍 1 次 + 补拉 1 次，无第三次
    expect(progressCalls).toBe(2);
    await screen.findByRole("button", { name: "确认简历档案" });
    expect(progressCalls).toBe(2);
  });

  it("backfills again for a second self-parsed generation (no stale dedup key)", async () => {
    // Codex 二轮 M1：progress 缓存被 onSuccess 清空时，补拉去重键不得退化
    // 复用（旧实现两代都是 "sess-1:" → 第二代跳过补拉丢失耗时行）。
    // 轮询全程悬置（never-resolve），终态只能靠补拉取回——同会话连续两代
    // preview 抢跑，两代的"用时"都必须出现。
    const user = userEvent.setup();
    mockWorkbenchApi();
    let gen = 1;
    let phase: "unparsed" | "processing" | "ready" = "unparsed";
    let progressServesDone = false;
    vi.mocked(api.pendingResumeUpload).mockImplementation(async () => {
      if (phase === "unparsed") {
        return apiFixtures.resumeUploaded({ generation: gen, filename: `resume-v${gen}.pdf` });
      }
      throw new ApiError(404, "no pending resume upload");
    });
    vi.mocked(api.resumePreview).mockImplementation(async () => {
      if (phase === "ready") return NARRATION_PREVIEW;
      throw new ApiError(
        409,
        phase === "processing" ? "resume_processing" : "resume_unparsed",
      );
    });
    vi.spyOn(api, "uploadResume").mockImplementation(async () => {
      gen = 2;
      phase = "unparsed";
      progressServesDone = false;
      return apiFixtures.resumeUploaded({ generation: 2, filename: "resume-v2.pdf" });
    });
    vi.spyOn(api, "parseResume").mockImplementation(async () => {
      phase = "processing";
      return { session_id: "sess-1", status: "resume_queued" };
    });
    const progressCallLog: boolean[] = [];
    vi.mocked(api.resumeProgress).mockImplementation(() => {
      progressCallLog.push(progressServesDone);
      if (!progressServesDone) return new Promise(() => {});
      return Promise.resolve({
        generation: gen,
        status: "resume_ready",
        events: [
          {
            seq: 100,
            step: "done",
            text: gen === 1 ? "档案生成完毕，用时 3.2 秒。" : "档案生成完毕，用时 5.0 秒。",
            elapsed_ms: gen === 1 ? 3200 : 5000,
            created_at: "2026-08-09T10:00:04Z",
          },
        ],
        done: true,
      });
    });
    const { queryClient } = renderWorkbench();

    // 第一代：确认解析 → preview 抢跑 ready → 补拉取回耗时
    await user.click(await screen.findByRole("button", { name: "确认解析" }));
    await screen.findByText(/正在归一化你的简历|小意整理中/);
    phase = "ready";
    progressServesDone = true;
    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: ["resume-preview", "sess-1"] });
    });
    await waitFor(() => expect(JSON.stringify(progressCallLog)).toContain("true"));
    expect(await screen.findByText(/用时 3.2 秒/)).toBeVisible();

    // 第二代：重传 → 确认上传 → 确认解析 → 再次 preview 抢跑
    const attach = screen.getByLabelText("上传简历");
    const fileInput = attach.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(fileInput, new File(["resume"], "r2.txt", { type: "text/plain" }));
    await user.click(await screen.findByRole("button", { name: "确认上传" }));
    await user.click(await screen.findByRole("button", { name: "确认解析" }));
    await screen.findByText(/正在归一化你的简历|小意整理中/);
    phase = "ready";
    progressServesDone = true;
    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: ["resume-preview", "sess-1"] });
    });
    expect(await screen.findByText(/用时 5.0 秒/)).toBeVisible();
  });

  it("does not claim another generation's completion after tab-back focus race", async () => {
    // 子 agent 三轮 minor：切走期间远端完成了 gen2，切回时 progress
    // （staleTime 0）先于 preview 解决——data 已是 gen2 终态而 processing
    // 还 stale-true。亲历标记不得被终态数据盖写：gen2 的耗时庆祝与逐行
    // 动画都不属于本页（本页只亲历过 gen1 的进行时）。
    mockWorkbenchApi();
    let progressCalls = 0;
    let remoteDone = false;
    vi.mocked(api.resumePreview).mockImplementation(async () => {
      if (remoteDone) return NARRATION_PREVIEW;
      throw new ApiError(409, "resume_processing");
    });
    vi.mocked(api.resumeProgress).mockImplementation(async () => {
      progressCalls += 1;
      if (progressCalls >= 2) {
        remoteDone = true; // 远端 gen2 已完成：progress 先带回终态
        return {
          generation: 2,
          status: "resume_ready",
          events: [
            {
              seq: 100,
              step: "done",
              text: "档案生成完毕，用时 9.9 秒。来看看整理结果吧！",
              elapsed_ms: 9900,
              created_at: "2026-08-09T10:02:00Z",
            },
          ],
          done: true,
        };
      }
      return {
        generation: 1,
        status: "resume_queued",
        events: [
          {
            seq: 1,
            step: "received",
            text: "收到！我现在就把你的简历完整读一遍～",
            elapsed_ms: 6,
            created_at: "2026-08-09T10:00:00Z",
          },
        ],
        done: false,
      };
    });
    renderWorkbench();

    // 亲历 gen1 进行时
    expect(await screen.findByText(/收到！我现在就把你的简历完整读一遍/)).toBeVisible();

    // 第二拍带回 gen2 终态 → settle 刷新 preview → gen2 档案上屏
    await screen.findByRole(
      "button",
      { name: "确认简历档案" },
      { timeout: 5000 },
    );
    // gen2 的完成不属于本页：无耗时庆祝、无逐行动画
    expect(screen.queryByText(/用时 9.9 秒/)).not.toBeInTheDocument();
    expect(document.querySelectorAll(".v2-profile-line").length).toBe(0);
  });

  it("clears watched provenance on upload so a remotely-parsed successor shows no stale celebration", async () => {
    // Codex 三轮 Major：本页亲历 gen1 完成后上传 gen2，远端标签页秒解析
    // ——本页从未观察到 gen2 的 queued 态（progress 查询全程停用），旧
    // gen1 的 done 缓存/亲历标记若不随上传清场，gen1 的用时庆祝与逐行
    // 动画会挂到 gen2 的档案上。上传即换代，归属全部作废。
    const user = userEvent.setup();
    mockWorkbenchApi();
    let phase: "processing1" | "ready1" | "remote2" = "processing1";
    vi.mocked(api.resumePreview).mockImplementation(async () => {
      if (phase === "processing1") throw new ApiError(409, "resume_processing");
      return NARRATION_PREVIEW;
    });
    vi.mocked(api.pendingResumeUpload).mockImplementation(async () => {
      throw new ApiError(404, "no pending resume upload");
    });
    vi.spyOn(api, "uploadResume").mockImplementation(async () => {
      phase = "remote2"; // 远端标签页在本页刷新前已确认解析并完成 gen2
      return apiFixtures.resumeUploaded({ generation: 2, filename: "resume-v2.pdf" });
    });
    let progressCalls = 0;
    vi.mocked(api.resumeProgress).mockImplementation(async () => {
      progressCalls += 1;
      if (progressCalls >= 2) {
        phase = "ready1";
        return {
          generation: 1,
          status: "resume_ready",
          events: [
            {
              seq: 100,
              step: "done",
              text: "档案生成完毕，用时 3.2 秒。来看看整理结果吧！",
              elapsed_ms: 3200,
              created_at: "2026-08-09T10:00:04Z",
            },
          ],
          done: true,
        };
      }
      return {
        generation: 1,
        status: "resume_queued",
        events: [
          {
            seq: 1,
            step: "received",
            text: "收到！我现在就把你的简历完整读一遍～",
            elapsed_ms: 6,
            created_at: "2026-08-09T10:00:00Z",
          },
        ],
        done: false,
      };
    });
    renderWorkbench();

    // 亲历 gen1 完成：庆祝与逐行动画合法在场
    expect(
      await screen.findByText(/用时 3.2 秒/, undefined, { timeout: 5000 }),
    ).toBeVisible();
    expect(document.querySelectorAll(".v2-profile-line").length).toBeGreaterThan(0);

    // 上传 gen2（远端秒解析，本页直接从 unparsed 跳到 ready）
    const attach = screen.getByLabelText("上传简历");
    const fileInput = attach.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(fileInput, new File(["resume"], "r2.txt", { type: "text/plain" }));
    await user.click(await screen.findByRole("button", { name: "确认上传" }));

    // gen2 档案上屏：gen1 的用时与动画不得残留
    await screen.findByRole("button", { name: "确认简历档案" });
    await waitFor(() =>
      expect(screen.queryByText(/用时 3.2 秒/)).not.toBeInTheDocument(),
    );
    expect(document.querySelectorAll(".v2-profile-line").length).toBe(0);
  });

  it("falls back to the confirm card when a re-upload lands mid-parse (uploaded interleave)", async () => {
    // 换代语义之一（自洽夹具，Codex 二轮 M2 修正）：远端标签页重传但未确认
    // → 新代 resume_uploaded → progress done=true。三端状态一致：progress=
    // uploaded/done、upload GET=新代 200、preview=unparsed。结果钉死"确认卡
    // 回场展示新代"（done 分支与双保险殊途同归，此用例钉结果不钉分支）。
    const user = userEvent.setup();
    mockWorkbenchApi();
    let serverPhase: "unparsed" | "parsing" | "reuploaded" = "unparsed";
    vi.mocked(api.resumePreview).mockImplementation(async () => {
      throw new ApiError(
        409,
        serverPhase === "parsing" ? "resume_processing" : "resume_unparsed",
      );
    });
    vi.mocked(api.pendingResumeUpload).mockImplementation(async () => {
      if (serverPhase === "parsing") throw new ApiError(404, "no pending resume upload");
      if (serverPhase === "reuploaded") {
        return apiFixtures.resumeUploaded({ generation: 2, filename: "resume-v2.pdf" });
      }
      return apiFixtures.resumeUploaded();
    });
    vi.spyOn(api, "parseResume").mockImplementation(async () => {
      serverPhase = "parsing";
      return { session_id: "sess-1", status: "resume_queued" };
    });
    let progressCalls = 0;
    vi.mocked(api.resumeProgress).mockImplementation(async () => {
      // 第二拍才换代：确保 parse onSuccess 的刷新已按"parsing"消化完
      progressCalls += 1;
      if (serverPhase === "parsing" && progressCalls >= 2) {
        serverPhase = "reuploaded";
        return { generation: 2, status: "resume_uploaded", events: [], done: true };
      }
      return { generation: 1, status: "resume_queued", events: [], done: false };
    });
    renderWorkbench();

    await user.click(await screen.findByRole("button", { name: "确认解析" }));

    expect(
      await screen.findByText(/resume-v2\.pdf/, undefined, { timeout: 5000 }),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "确认解析" })).toBeVisible();
    expect(screen.queryByText(/小意整理中|正在归一化你的简历/)).not.toBeInTheDocument();
  });

  it("follows the successor generation when the other tab already confirmed it (queued takeover)", async () => {
    // 换代语义之二（钉死双保险 mismatch 分支）：远端标签页重传并已确认解析
    // → 新代 resume_queued → done=false。done 分支永不触发，upload 第三次
    // 请求只能来自 mismatch 分支的刷新；叙事跟随新代事件（共享会话模型，
    // key/stagger/归属按代绑定）。
    const user = userEvent.setup();
    mockWorkbenchApi();
    let takenOver = false;
    let uploadCalls = 0;
    vi.mocked(api.resumePreview).mockImplementation(async () => {
      throw new ApiError(409, takenOver ? "resume_processing" : "resume_unparsed");
    });
    vi.mocked(api.pendingResumeUpload).mockImplementation(async () => {
      uploadCalls += 1;
      if (uploadCalls === 1) return apiFixtures.resumeUploaded();
      throw new ApiError(404, "no pending resume upload");
    });
    vi.spyOn(api, "parseResume").mockImplementation(async () => {
      takenOver = true; // 远端在任务启动瞬间接管：会话已是新代 queued
      return { session_id: "sess-1", status: "resume_queued" };
    });
    let progressCalls = 0;
    vi.mocked(api.resumeProgress).mockImplementation(async () => {
      progressCalls += 1;
      if (progressCalls >= 2) {
        return {
          generation: 2,
          status: "resume_queued",
          events: [
            {
              seq: 1,
              step: "received",
              text: "新一版简历收到！我重新读一遍～",
              elapsed_ms: 8,
              created_at: "2026-08-09T10:01:00Z",
            },
            {
              seq: 2,
              step: "extracted",
              text: "新一版读完啦，片段更充实了！",
              elapsed_ms: 60,
              created_at: "2026-08-09T10:01:01Z",
            },
          ],
          done: false,
        };
      }
      return { generation: 1, status: "resume_queued", events: [], done: false };
    });
    renderWorkbench();

    await user.click(await screen.findByRole("button", { name: "确认解析" }));

    // 接管：新代叙事上屏（轮询继续，渲染的是现行解析）
    const takeoverBubble = await screen.findByText(/新一版简历收到/, undefined, {
      timeout: 5000,
    });
    expect(takeoverBubble).toBeVisible();
    // freshBaseline 的代数比对（Codex 三轮 m2）：本页自发的是 gen1，gen2
    // 是远端流——旁观模式首批整批即时到场，两条 gen2 气泡都不得有到场
    // 延迟（若退化为只比会话，第二条会被编排 450ms）
    const secondBubble = await screen.findByText(/新一版读完啦/);
    expect(
      (takeoverBubble.closest(".v2-msg") as HTMLElement).style.animationDelay,
    ).toBe("");
    expect(
      (secondBubble.closest(".v2-msg") as HTMLElement).style.animationDelay,
    ).toBe("");
    // mismatch 分支的上传态刷新：mount(1) + onSuccess(2) + mismatch(3)
    await waitFor(() => expect(uploadCalls).toBe(3));
    expect(screen.queryByText(/收到！我现在就把你的简历完整读一遍/)).not.toBeInTheDocument();
  });
});
