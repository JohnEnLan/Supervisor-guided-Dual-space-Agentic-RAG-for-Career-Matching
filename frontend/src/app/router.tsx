import { Navigate, createBrowserRouter, useOutletContext } from "react-router-dom";

import { EvaluationRunPage } from "../features/evaluation/EvaluationRunPage";
import { MonitoringPage } from "../features/monitoring/MonitoringPage";
import { AppShell, type AppShellOutletContext } from "../v2/AppShell";
import { LandingPage } from "../v2/LandingPage";
import { ProfilePage } from "../v2/ProfilePage";
import { WorkbenchPage } from "../v2/WorkbenchPage";
import { RouteError } from "./App";

function EmptyWorkbench() {
  const { startNewConsultation, isCreatingConsultation } = useOutletContext<AppShellOutletContext>();
  return (
    <section className="v2-empty" role="region" aria-label="开始咨询">
      <p className="v2-empty-eyebrow">职业顾问团队已就位</p>
      <h1>用三步拿到可追溯的岗位建议</h1>
      <ol className="v2-empty-guide">
        <li><strong>上传简历</strong><span>整理经历并保留原文证据</span></li>
        <li><strong>聊清方向</strong><span>确认目标、地点与签证条件</span></li>
        <li><strong>查看结果</strong><span>获得分层岗位、证据与行动建议</span></li>
      </ol>
      <button
        type="button"
        className="v2-btn primary v2-empty-action"
        disabled={isCreatingConsultation}
        onClick={startNewConsultation}
      >
        {isCreatingConsultation ? "正在创建…" : "开始新的咨询"}
      </button>
    </section>
  );
}

export const router = createBrowserRouter([
  {
    path: "/",
    element: <LandingPage />,
    errorElement: <RouteError />,
  },
  {
    path: "/app",
    element: <AppShell />,
    errorElement: <RouteError />,
    children: [
      { index: true, element: <EmptyWorkbench /> },
      { path: "sessions/:sessionId", element: <WorkbenchPage /> },
      { path: "profile", element: <ProfilePage /> },
      { path: "settings/evaluation", element: <EvaluationRunPage /> },
      { path: "settings/evaluation/:runId", element: <EvaluationRunPage /> },
      { path: "settings/monitoring", element: <MonitoringPage /> },
    ],
  },
  { path: "*", element: <Navigate replace to="/" /> },
]);
