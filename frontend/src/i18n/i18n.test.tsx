import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import { api } from "../api/queries";
import { RouteError } from "../app/App";
import { AppProviders } from "../app/providers";
import { router as appRouter } from "../app/router";
import { AppShell } from "../v2/AppShell";
import { HomePage } from "../v2/HomePage";
import { LandingPage } from "../v2/LandingPage";
import themeSource from "../v2/theme.css?raw";
import { WelcomePage } from "../v2/WelcomePage";
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
      screen.getByRole("button", { name: "Current language: English; switch to 中文" }),
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

describe("AppShell language switching", () => {
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
