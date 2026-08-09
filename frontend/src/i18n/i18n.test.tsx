import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import { api } from "../api/queries";
import { RouteError } from "../app/App";
import { AppProviders } from "../app/providers";
import { router as appRouter } from "../app/router";
import { ExplainUnavailable } from "../features/evaluation/EvaluationRunPage";
import { ReactionForm } from "../features/feedback/ReactionForm";
import { MonitoringUnavailable } from "../features/monitoring/MonitoringPage";
import { EvidenceDrawer } from "../features/results/EvidenceDrawer";
import { AdminPage } from "../v2/AdminPage";
import { AppShell } from "../v2/AppShell";
import { HomePage } from "../v2/HomePage";
import { LandingPage } from "../v2/LandingPage";
import { ProfilePage } from "../v2/ProfilePage";
import { ResumeProfileAccordion } from "../v2/ResumeProfileAccordion";
import themeSource from "../v2/theme.css?raw";
import { WelcomePage } from "../v2/WelcomePage";
import { WorkbenchPage } from "../v2/WorkbenchPage";
import {
  LANGUAGE_STORAGE_KEY,
  LanguageProvider,
  LanguageToggle,
  resetLanguageForTests,
  translate,
  useLanguage,
} from ".";

const ZH_TITLE = "Career RAG 答辩工作台";

function LanguageProbe() {
  const { lang } = useLanguage();
  return <output aria-label="language">{lang}</output>;
}

function BareInterpolationProbe() {
  const { t } = useLanguage();
  return <p>{t("已创建 {count} 次咨询", { count: 2 })}</p>;
}

function renderHomePage() {
  vi.spyOn(api, "me").mockRejectedValue(new ApiError(401, "unauthorized"));
  const router = createMemoryRouter([{ path: "/", element: <HomePage /> }]);
  render(
    <AppProviders>
      <RouterProvider router={router} />
    </AppProviders>,
  );
}

function renderWelcomePage() {
  vi.spyOn(api, "me").mockRejectedValue(new ApiError(401, "unauthorized"));
  const router = createMemoryRouter(
    [
      { path: "/", element: <p>home</p> },
      { path: "/welcome", element: <WelcomePage /> },
    ],
    { initialEntries: ["/welcome"] },
  );
  render(
    <AppProviders>
      <RouterProvider router={router} />
    </AppProviders>,
  );
}

function renderLandingPage() {
  vi.spyOn(api, "me").mockRejectedValue(new ApiError(401, "unauthorized"));
  vi.spyOn(api, "capabilities").mockResolvedValue({
    api_version: "v1",
    dual_space_enabled: true,
    resume_image_upload_enabled: true,
    execution_durability: "process_local",
    explain_enabled: false,
    monitoring_enabled: false,
    otp_channels: ["email"],
  });
  const router = createMemoryRouter([{ path: "/login", element: <LandingPage /> }], {
    initialEntries: ["/login"],
  });
  render(
    <AppProviders>
      <RouterProvider router={router} />
    </AppProviders>,
  );
}

function renderAppShell() {
  vi.spyOn(api, "me").mockResolvedValue({
    user_id: "user-1",
    status: "active",
    is_admin: false,
    display_name: "Test User",
    created_at: "2026-08-06T10:00:00Z",
  });
  vi.spyOn(api, "meSessions").mockResolvedValue({
    sessions: [],
    page: 1,
    page_size: 30,
    has_more: false,
  });
  const router = createMemoryRouter(
    [
      {
        path: "/app",
        element: <AppShell />,
        children: [{ index: true, element: <p>Workbench content</p> }],
      },
    ],
    { initialEntries: ["/app"] },
  );
  render(
    <AppProviders>
      <RouterProvider router={router} />
    </AppProviders>,
  );
}

beforeEach(() => {
  localStorage.removeItem(LANGUAGE_STORAGE_KEY);
  resetLanguageForTests();
  document.documentElement.lang = "zh-CN";
  document.title = ZH_TITLE;
});

afterEach(() => {
  localStorage.removeItem(LANGUAGE_STORAGE_KEY);
  resetLanguageForTests();
  document.documentElement.lang = "zh-CN";
  document.title = ZH_TITLE;
});

describe("translation primitives", () => {
  it("keeps Chinese unchanged and translates known English entries", () => {
    expect(translate("zh", "进入应用")).toBe("进入应用");
    expect(translate("en", "进入应用")).toBe("Open the app");
  });

  it("falls back to the original Chinese when an English entry is missing", () => {
    expect(translate("en", "这条词典里没有")).toBe("这条词典里没有");
  });
});

describe("LanguageProvider", () => {
  it("defaults to Chinese when no language has been stored", () => {
    render(
      <LanguageProvider>
        <LanguageProbe />
      </LanguageProvider>,
    );

    expect(screen.getByRole("status", { name: "language" })).toHaveTextContent("zh");
  });

  it("treats an invalid stored value as Chinese", () => {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, "fr");

    render(
      <LanguageProvider>
        <LanguageProbe />
      </LanguageProvider>,
    );

    expect(screen.getByRole("status", { name: "language" })).toHaveTextContent("zh");
  });

  it("persists English and restores it after remounting", async () => {
    const user = userEvent.setup();
    const first = render(
      <LanguageProvider>
        <LanguageProbe />
        <LanguageToggle />
      </LanguageProvider>,
    );

    await user.click(
      screen.getByRole("button", { name: "当前语言：中文；切换到 English" }),
    );
    expect(screen.getByRole("status", { name: "language" })).toHaveTextContent("en");
    expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe("en");

    first.unmount();
    render(
      <LanguageProvider>
        <LanguageProbe />
      </LanguageProvider>,
    );
    expect(screen.getByRole("status", { name: "language" })).toHaveTextContent("en");
  });

  it("keeps a valid stored choice in memory if storage later becomes unavailable", () => {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, "en");
    const first = render(
      <LanguageProvider>
        <LanguageProbe />
      </LanguageProvider>,
    );
    expect(screen.getByRole("status", { name: "language" })).toHaveTextContent("en");
    first.unmount();

    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("storage unavailable");
    });
    render(
      <LanguageProvider>
        <LanguageProbe />
      </LanguageProvider>,
    );
    expect(screen.getByRole("status", { name: "language" })).toHaveTextContent("en");
  });

  it("synchronizes the document language and restores the Chinese title", async () => {
    const user = userEvent.setup();
    render(
      <LanguageProvider>
        <LanguageToggle />
      </LanguageProvider>,
    );

    expect(document.documentElement.lang).toBe("zh-CN");
    expect(document.title).toBe(ZH_TITLE);

    await user.click(
      screen.getByRole("button", { name: "当前语言：中文；切换到 English" }),
    );
    expect(document.documentElement.lang).toBe("en");
    expect(document.title).toBe("Career RAG Workbench");

    await user.click(
      screen.getByRole("button", { name: "Current language: English; switch to Chinese" }),
    );
    expect(document.documentElement.lang).toBe("zh-CN");
    expect(document.title).toBe(ZH_TITLE);
  });

  it("is mounted by AppProviders so routed content receives the real context", () => {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, "en");

    render(
      <AppProviders>
        <LanguageProbe />
      </AppProviders>,
    );

    expect(screen.getByRole("status", { name: "language" })).toHaveTextContent("en");
  });
});

describe("default context and toggle accessibility", () => {
  it("interpolates parameters in Chinese without a provider", () => {
    render(<BareInterpolationProbe />);
    expect(screen.getByText("已创建 2 次咨询")).toBeVisible();
  });

  it("exposes current and target languages and accepts visible keyboard focus", () => {
    render(
      <LanguageProvider>
        <LanguageToggle />
      </LanguageProvider>,
    );

    const toggle = screen.getByRole("button", {
      name: "当前语言：中文；切换到 English",
    });
    toggle.focus();
    expect(toggle).toHaveFocus();
    expect(toggle).toHaveClass("v2-language-toggle");
  });

  it("defines visible focus and responsive placement rules", () => {
    expect(themeSource).toMatch(/\.v2-language-toggle:focus-visible\s*\{[^}]*outline:/s);
    expect(themeSource).toMatch(/\.v2-main\s*\{[^}]*position:\s*relative/s);
    expect(themeSource).toMatch(/\.v2-lang-float\s*\{[^}]*position:\s*absolute/s);
    expect(themeSource).toMatch(/\.v2-lang-mobile\s*\{[^}]*display:\s*none/s);
    expect(themeSource).toContain("margin-left: auto");
    expect(themeSource).toMatch(/\.v2-login-card\s*\{[^}]*position:\s*relative/s);
    expect(themeSource).toMatch(/\.v2-login-lang\s*\{[^}]*position:\s*absolute/s);
  });

  it("reserves desktop flow space for the language notice and resets it on mobile", () => {
    expect(themeSource).toMatch(/\.v2-lang-notice\s*\{[^}]*margin:\s*56px\s+clamp\(16px,\s*4vw,\s*48px\)\s+8px/s);
    expect(themeSource).toMatch(/\.v2-lang-notice\s*\{[^}]*flex:\s*0\s+0\s+auto/s);
    expect(themeSource).toMatch(/@media\s*\(max-width:\s*900px\)\s*\{[\s\S]*?\.v2-lang-notice\s*\{[^}]*width:\s*auto;[^}]*margin:\s*8px\s+14px\s+0/s);
  });
});

describe("HomePage language switching", () => {
  it("renders the existing Chinese experience by default", async () => {
    renderHomePage();
    expect(
      await screen.findByRole("heading", {
        name: "把求职这件事，交给一支为你服务的团队",
      }),
    ).toBeVisible();
    expect(screen.getByRole("region", { name: "功能陈列" })).toBeVisible();
  });

  it("switches the navigation and page content to English", async () => {
    const user = userEvent.setup();
    renderHomePage();

    await user.click(
      screen.getByRole("button", { name: "当前语言：中文；切换到 English" }),
    );

    expect(
      screen.getByRole("heading", {
        name: "Put your job search in the hands of a team built around you",
      }),
    ).toBeVisible();
    expect(screen.getByRole("region", { name: "Features" })).toBeVisible();
    expect(screen.queryByText("一套认真对待求职的系统")).not.toBeInTheDocument();
  });
});

describe("WelcomePage language switching", () => {
  it("switches the introduction and its exit control to English", async () => {
    const user = userEvent.setup();
    renderWelcomePage();

    await user.click(
      screen.getByRole("button", { name: "当前语言：中文；切换到 English" }),
    );

    expect(
      screen.getByRole("heading", { name: "Job searching should not be a solo journey" }),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Skip introduction →" })).toBeVisible();
    expect(screen.queryByText("求职不该是一个人的事")).not.toBeInTheDocument();
  });
});

describe("LandingPage language switching", () => {
  it("switches the login card and product promise to English", async () => {
    const user = userEvent.setup();
    renderLandingPage();

    await user.click(
      screen.getByRole("button", { name: "当前语言：中文；切换到 English" }),
    );

    expect(
      screen.getByRole("heading", {
        name: "Put your job search in the hands of a team built around you",
      }),
    ).toBeVisible();
    expect(screen.getByRole("region", { name: "Sign in" })).toBeVisible();
    expect(screen.queryByText("把求职这件事，交给一支为你服务的团队")).not.toBeInTheDocument();
  });
});

describe("static English-page Han guards", () => {
  it("renders HomePage without Han characters in English", async () => {
    const user = userEvent.setup();
    renderHomePage();

    await user.click(
      screen.getByRole("button", { name: "当前语言：中文；切换到 English" }),
    );

    expect(document.body.textContent).not.toMatch(/[\u4e00-\u9fff]/);
  });

  it("renders WelcomePage without Han characters in English", async () => {
    const user = userEvent.setup();
    renderWelcomePage();

    await user.click(
      screen.getByRole("button", { name: "当前语言：中文；切换到 English" }),
    );

    expect(document.body.textContent).not.toMatch(/[\u4e00-\u9fff]/);
  });

  it("renders LandingPage without Han characters in English", async () => {
    const user = userEvent.setup();
    renderLandingPage();

    await user.click(
      screen.getByRole("button", { name: "当前语言：中文；切换到 English" }),
    );

    expect(document.body.textContent).not.toMatch(/[\u4e00-\u9fff]/);
  });
});

describe("AppShell language switching", () => {
  it("shows the generated-content language notice only in English", async () => {
    const user = userEvent.setup();
    renderAppShell();
    await screen.findByText("Test User");

    const notice = "Some generated or data-dependent conversation content may remain in Chinese.";
    expect(screen.queryByText(notice)).not.toBeInTheDocument();

    await user.click(
      screen.getByRole("button", {
        name: "当前语言：中文；切换到 English",
      }),
    );
    expect(screen.getByText(notice)).toBeVisible();

    await user.click(
      screen.getByRole("button", {
        name: "Current language: English; switch to Chinese",
      }),
    );
    expect(screen.queryByText(notice)).not.toBeInTheDocument();
  });

  it("provides desktop and mobile controls and translates shell-owned copy", async () => {
    const user = userEvent.setup();
    renderAppShell();
    await screen.findByText("Test User");

    const desktopToggle = screen.getByRole("button", {
      name: "当前语言：中文；切换到 English",
    });
    const mobileToggle = document.querySelector<HTMLButtonElement>(
      ".v2-mobile-nav > .v2-lang-mobile",
    );
    expect(document.querySelectorAll(".v2-language-toggle")).toHaveLength(2);
    expect(document.querySelector(".v2-main > .v2-lang-float")).toBe(desktopToggle);
    expect(mobileToggle).toHaveAttribute(
      "aria-label",
      "当前语言：中文；切换到 English",
    );

    await user.click(desktopToggle);
    expect(screen.getByRole("button", { name: "New consultation" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "新的咨询" })).not.toBeInTheDocument();
  });
});

describe("routed fallback copy", () => {
  it("translates the empty workbench without changing its create action", async () => {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, "en");
    vi.spyOn(api, "me").mockResolvedValue({
      user_id: "user-1",
      status: "active",
      is_admin: false,
      display_name: "Test User",
      created_at: "2026-08-06T10:00:00Z",
    });
    vi.spyOn(api, "meSessions").mockResolvedValue({
      sessions: [],
      page: 1,
      page_size: 30,
      has_more: false,
    });
    vi.spyOn(api, "createSession").mockResolvedValue({
      session_id: "new-session",
      status: "awaiting_resume",
    });
    await appRouter.navigate("/app");

    render(
      <AppProviders>
        <RouterProvider router={appRouter} />
      </AppProviders>,
    );

    expect(
      await screen.findByRole("region", { name: "Start a consultation" }),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Start a new consultation" })).toBeVisible();
    expect(screen.queryByText("职业顾问团队已就位")).not.toBeInTheDocument();
  });

  it("translates RouteError chrome but leaves dynamic error details untouched", async () => {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, "en");
    const router = createMemoryRouter([
      {
        path: "/",
        loader: () => {
          throw new Error("dynamic route detail");
        },
        element: <p>unreachable</p>,
        errorElement: <RouteError />,
      },
    ]);

    render(
      <AppProviders>
        <RouterProvider router={router} />
      </AppProviders>,
    );

    expect(await screen.findByRole("heading", { name: "Something went wrong" })).toBeVisible();
    expect(screen.getByText("dynamic route detail")).toBeVisible();
    expect(screen.getByRole("link", { name: "Return to homepage" })).toBeVisible();
  });
});

function renderEnglishWorkbench(
  confirmed: boolean,
  transcript: Awaited<ReturnType<typeof api.consultState>>["transcript"] = [],
  clarificationProgress?: Awaited<ReturnType<typeof api.consultState>>["clarification_progress"],
) {
  localStorage.setItem(LANGUAGE_STORAGE_KEY, "en");
  vi.spyOn(api, "me").mockResolvedValue({
    user_id: "user-1",
    status: "active",
    is_admin: false,
    display_name: "测试用户",
    created_at: "2026-08-06T10:00:00Z",
  });
  vi.spyOn(api, "capabilities").mockResolvedValue({
    api_version: "v1",
    dual_space_enabled: true,
    resume_image_upload_enabled: false,
    execution_durability: "process_local",
    explain_enabled: false,
    monitoring_enabled: false,
    otp_channels: ["email"],
  });
  vi.spyOn(api, "pendingResumeUpload").mockRejectedValue(
    new ApiError(404, "no pending resume upload"),
  );
  vi.spyOn(api, "resumePreview").mockResolvedValue({
    session_id: "sess-1",
    resume_version: 1,
    confirmed,
    education: [{
      institution: "伯明翰大学",
      degree: "MSc",
      field: "Computer Science",
      dates: "2025–2026",
      details: [],
      evidence_span_ids: [],
    }],
    experience: [],
    projects: [],
    skills: ["Python"],
    resume_quality_issues: [],
    evidence: [],
  });
  vi.spyOn(api, "consultState").mockResolvedValue({
    transcript,
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
    clarification_progress: clarificationProgress,
  });
  const router = createMemoryRouter(
    [{ path: "/app/sessions/:sessionId", element: <WorkbenchPage /> }],
    { initialEntries: ["/app/sessions/sess-1"] },
  );
  render(
    <AppProviders>
      <RouterProvider router={router} />
    </AppProviders>,
  );
}

describe("L2 business-page language switching", () => {
  it("translates Workbench chrome and profile-summary templates without translating profile data", async () => {
    renderEnglishWorkbench(false);

    expect(await screen.findByRole("heading", { name: "Career Planning Service Room" })).toBeVisible();
    expect(screen.getByText("🎓 Education: 伯明翰大学 · MSc")).toBeVisible();
    expect(screen.queryByText("职业规划服务群")).not.toBeInTheDocument();
  });

  it("rebuilds Workbench consult-slot and milestone templates while preserving dynamic values", async () => {
    renderEnglishWorkbench(true, [], {
      answered: 1,
      skipped: 1,
      total: 4,
      questions_used: 2,
    });

    expect(await screen.findByText("Goal: backend engineer")).toBeVisible();
    expect(screen.getByText("Location: Shanghai")).toBeVisible();
    expect(screen.getByText("Visa: No sponsorship needed")).toBeVisible();
    expect(
      screen.getByText("Resume follow-up: 1 answered, 1 skipped, 2 remaining"),
    ).toBeVisible();
    expect(
      screen.getByText(
        "Xiaoyi has collected the required details: goal backend engineer, location Shanghai, visa no sponsorship needed. You can add more preferences or ask me to arrange the match.",
      ),
    ).toBeVisible();
  });

  it("keeps Workbench transcript and Supervisor-generated content out of translation", async () => {
    renderEnglishWorkbench(true, [{
      round: 1,
      phase: "deepen",
      user_message: "无",
        assistant_reply: "顾问动态回复",
        next_question: "动态追问",
        supervisor_notes: [{
          coach_attempt_id: "note-1",
          kind: "coach",
          trigger: "stagnation",
          text: "Supervisor 动态提示",
          verdict: "advise",
        }],
      }]);

    expect(await screen.findByText("无")).toBeVisible();
    expect(screen.getByText(/顾问动态回复/)).toHaveTextContent("动态追问");
    expect(screen.getByText("Supervisor 动态提示")).toBeVisible();
  });

  it("translates ResumeProfileAccordion chrome while preserving resume fields", async () => {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, "en");
    const user = userEvent.setup();
    render(
      <AppProviders>
        <ResumeProfileAccordion
          preview={{
            session_id: "sess-1",
            resume_version: 1,
            confirmed: false,
            education: [],
            experience: [{
              organization: "动态公司字段",
              title: "Data Analyst",
              location: "London",
              dates: "2025",
              responsibilities: [],
              achievements: [],
              technologies: [],
              evidence_span_ids: [],
            }],
            projects: [],
            skills: [],
            resume_quality_issues: [],
            evidence: [],
          }}
        />
      </AppProviders>,
    );

    await user.click(screen.getByRole("button", { name: "View full profile" }));
    expect(screen.getByRole("heading", { name: "Work Experience" })).toBeVisible();
    expect(screen.getByText("动态公司字段")).toBeVisible();
    expect(screen.queryByText("工作经历")).not.toBeInTheDocument();
  });

  it("translates EvidenceDrawer chrome while preserving job evidence", async () => {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, "en");
    const user = userEvent.setup();
    render(
      <AppProviders>
        <EvidenceDrawer
          title="数据分析师"
          evidence={[{ evidence_span_id: "jd-1", content: "岗位要求中文原文" }]}
          resumeEvidence={[]}
        />
      </AppProviders>,
    );

    await user.click(screen.getByRole("button", { name: "View evidence" }));
    expect(screen.getByRole("heading", { name: "Source Job Evidence" })).toBeVisible();
    expect(screen.getByText("岗位要求中文原文")).toBeVisible();
    expect(screen.queryByText("岗位原文证据")).not.toBeInTheDocument();
  });

  it("translates ReactionForm controls", () => {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, "en");
    render(
      <AppProviders>
        <ReactionForm runId="run-1" jobId="job-1" />
      </AppProviders>,
    );

    expect(screen.getByRole("heading", { name: "Tell us how your application went" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Rejected" })).toBeVisible();
    expect(screen.queryByText("被拒")).not.toBeInTheDocument();
  });

  it("translates ProfilePage chrome while preserving account data", async () => {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, "en");
    vi.spyOn(api, "me").mockResolvedValue({
      user_id: "user-1",
      status: "active",
      is_admin: false,
      display_name: "测试用户",
      created_at: "2026-08-06T10:00:00Z",
    });
    vi.spyOn(api, "meProfile").mockResolvedValue({
      profile: {},
      updated_at: "2026-08-06T10:00:00Z",
    });

    render(
      <AppProviders>
        <ProfilePage />
      </AppProviders>,
    );

    expect(await screen.findByRole("heading", { name: "My Profile" })).toBeVisible();
    expect(screen.getByText(/测试用户/)).toBeVisible();
    expect(screen.queryByRole("heading", { name: "我的档案" })).not.toBeInTheDocument();
  });

  it("translates EvaluationRunPage capability-off copy", () => {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, "en");
    render(
      <AppProviders>
        <ExplainUnavailable />
      </AppProviders>,
    );

    expect(screen.getByRole("heading", { name: "Evaluation Details Are Disabled" })).toBeVisible();
    expect(screen.queryByText("评估解释未开启")).not.toBeInTheDocument();
  });

  it("translates MonitoringPage capability-off copy", () => {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, "en");
    render(
      <AppProviders>
        <MonitoringUnavailable />
      </AppProviders>,
    );

    expect(screen.getByRole("heading", { name: "Run Monitoring Is Disabled" })).toBeVisible();
    expect(screen.queryByText("运行监控未开启")).not.toBeInTheDocument();
  });

  it("translates AdminPage and its dashboard", async () => {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, "en");
    vi.spyOn(api, "me").mockResolvedValue({
      user_id: "admin-1",
      status: "active",
      is_admin: true,
      display_name: "测试管理员",
      created_at: "2026-08-06T10:00:00Z",
    });
    vi.spyOn(api, "adminOverview").mockResolvedValue({
      users_total: 1,
      logins_today: 1,
      logins_7d: 1,
      logins_30d: 1,
      sessions_total: 1,
      consult_turns_total: 1,
      runs_total: 1,
      tokens_by_day: [],
      tokens_by_model: [],
    });
    const router = createMemoryRouter(
      [
        { path: "/admin", element: <AdminPage /> },
        { path: "/app", element: <p>app</p> },
        { path: "/login", element: <p>login</p> },
      ],
      { initialEntries: ["/admin"] },
    );

    render(
      <AppProviders>
        <RouterProvider router={router} />
      </AppProviders>,
    );

    expect(await screen.findByRole("heading", { name: "Admin Console" })).toBeVisible();
    expect(screen.getByText("Read-only overview")).toBeVisible();
    expect(screen.getByText("测试管理员")).toBeVisible();
    expect(screen.queryByText("管理控制台")).not.toBeInTheDocument();
  });
});
