import { createBrowserRouter } from "react-router-dom";

import { NewSessionPage } from "../features/session/NewSessionPage";
import { ResumeReviewPage } from "../features/session/ResumeReviewPage";
import { MatchBriefPage } from "../features/brief/MatchBriefPage";
import { RunPage } from "../features/run/RunPage";
import { ResultsPage } from "../features/results/ResultsPage";
import { EvaluationRunPage } from "../features/evaluation/EvaluationRunPage";
import { MonitoringPage } from "../features/monitoring/MonitoringPage";
import { App, RouteError } from "./App";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <App />,
    errorElement: <RouteError />,
    children: [
      { index: true, element: <NewSessionPage /> },
      { path: "sessions/:sessionId/resume", element: <ResumeReviewPage /> },
      { path: "sessions/:sessionId/brief", element: <MatchBriefPage /> },
      { path: "runs/:runId", element: <RunPage /> },
      { path: "runs/:runId/results", element: <ResultsPage /> },
      { path: "runs/:runId/explain", element: <EvaluationRunPage /> },
      { path: "monitoring", element: <MonitoringPage /> },
    ],
  },
]);
