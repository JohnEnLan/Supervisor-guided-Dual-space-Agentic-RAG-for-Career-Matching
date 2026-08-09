import { Navigate, createBrowserRouter, useOutletContext, useParams } from "react-router-dom";

import { useLanguage } from "../i18n";
import { AdminPage } from "../v2/AdminPage";
import { AppShell, type AppShellOutletContext } from "../v2/AppShell";
import { HomePage } from "../v2/HomePage";
import { hasSeenIntro } from "../v2/introSeen";
import { LandingPage } from "../v2/LandingPage";
import { ProfilePage } from "../v2/ProfilePage";
import { WelcomePage } from "../v2/WelcomePage";
import { WorkbenchPage } from "../v2/WorkbenchPage";
import { RouteError } from "./App";


// Unacknowledged first visits see the introduction before the homepage.
// Brand links and introduction exits acknowledge this gate; module memory keeps
// the current session loop-free when localStorage is unavailable.
function HomeGate() {
  if (!hasSeenIntro()) return <Navigate replace to="/welcome" />;
  return <HomePage />;
}

function EmptyWorkbench() {
  const { startNewConsultation, isCreatingConsultation } = useOutletContext<AppShellOutletContext>();
  const { t } = useLanguage();
  return (
    <section className="v2-empty" role="region" aria-label={t("开始咨询")}>
      <p className="v2-empty-eyebrow">{t("职业顾问团队已就位")}</p>
      <h1>{t("用三步拿到可追溯的岗位建议")}</h1>
      <ol className="v2-empty-guide">
        <li><strong>{t("上传简历")}</strong><span>{t("整理经历并保留原文证据")}</span></li>
        <li><strong>{t("聊清方向")}</strong><span>{t("确认目标、地点与签证条件")}</span></li>
        <li><strong>{t("查看结果")}</strong><span>{t("获得分层岗位、证据与行动建议")}</span></li>
      </ol>
      <button
        type="button"
        className="v2-btn primary v2-empty-action"
        disabled={isCreatingConsultation}
        onClick={startNewConsultation}
      >
        {t(isCreatingConsultation ? "正在创建…" : "开始新的咨询")}
      </button>
    </section>
  );
}

function LegacyEvaluationRedirect() {
  const { runId } = useParams();
  const search = new URLSearchParams({ tab: "evaluation" });
  if (runId) search.set("runId", runId);
  return <Navigate replace to={{ pathname: "/admin", search: `?${search.toString()}` }} />;
}

export const router = createBrowserRouter([
  {
    path: "/",
    element: <HomeGate />,
    errorElement: <RouteError />,
  },
  {
    path: "/welcome",
    element: <WelcomePage />,
    errorElement: <RouteError />,
  },
  {
    path: "/login",
    element: <LandingPage />,
    errorElement: <RouteError />,
  },
  {
    path: "/admin",
    element: <AdminPage />,
    errorElement: <RouteError />,
  },
  {
    path: "/app/settings/evaluation",
    element: <LegacyEvaluationRedirect />,
  },
  {
    path: "/app/settings/evaluation/:runId",
    element: <LegacyEvaluationRedirect />,
  },
  {
    path: "/app/settings/monitoring",
    element: <Navigate replace to="/admin?tab=monitoring" />,
  },
  {
    path: "/app",
    element: <AppShell />,
    errorElement: <RouteError />,
    children: [
      { index: true, element: <EmptyWorkbench /> },
      { path: "sessions/:sessionId", element: <WorkbenchPage /> },
      { path: "profile", element: <ProfilePage /> },
    ],
  },
  { path: "*", element: <Navigate replace to="/" /> },
]);
