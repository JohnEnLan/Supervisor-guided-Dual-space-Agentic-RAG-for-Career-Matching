import { Navigate, createBrowserRouter } from "react-router-dom";

import { EvaluationRunPage } from "../features/evaluation/EvaluationRunPage";
import { MonitoringPage } from "../features/monitoring/MonitoringPage";
import { AppShell } from "../v2/AppShell";
import { LandingPage } from "../v2/LandingPage";
import { ProfilePage } from "../v2/ProfilePage";
import { WorkbenchPage } from "../v2/WorkbenchPage";
import { RouteError } from "./App";

function EmptyWorkbench() {
  return (
    <section className="v2-empty">
      <h1>选择或新建一个咨询会话</h1>
      <p>左侧「新的咨询」开始：上传简历 → 和顾问团队聊方向 → 拿到带证据的推荐。</p>
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
