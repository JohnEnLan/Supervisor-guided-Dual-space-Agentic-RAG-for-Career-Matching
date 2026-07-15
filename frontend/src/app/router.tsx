import { createBrowserRouter, Navigate } from "react-router-dom";

import { NewSessionPage } from "../features/session/NewSessionPage";
import { ResumeReviewPage } from "../features/session/ResumeReviewPage";
import { MatchBriefPage } from "../features/brief/MatchBriefPage";
import { RunPage } from "../features/run/RunPage";
import { ResultsPage } from "../features/results/ResultsPage";
import { EvaluationRunPage } from "../features/evaluation/EvaluationRunPage";
import { MonitoringPage } from "../features/monitoring/MonitoringPage";
import { CinematicOnboardingPage } from "../features/onboarding/CinematicOnboardingPage";
import { App, RouteError } from "./App";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <CinematicOnboardingPage />,
    errorElement: <RouteError />,
  },
  {
    element: <App />,
    errorElement: <RouteError />,
    children: [
      { path: "workspace", element: <NewSessionPage /> },
      { path: "sessions/:sessionId/resume", element: <ResumeReviewPage /> },
      { path: "sessions/:sessionId/brief", element: <MatchBriefPage /> },
      { path: "runs/:runId", element: <RunPage /> },
      { path: "runs/:runId/results", element: <ResultsPage /> },
      { path: "runs/:runId/evaluation", element: <EvaluationRunPage /> },
      { path: "runs/:runId/explain", element: <Navigate replace to="../evaluation" /> },
      { path: "monitoring", element: <MonitoringPage /> },
    ],
  },
]);
