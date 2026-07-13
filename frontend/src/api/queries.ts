import type { components } from "./generated";
import { apiRequest, jsonRequest, uploadRequest } from "./client";

type Schemas = components["schemas"];

export type Capabilities = Schemas["CapabilitiesResponse"];
export type SessionCreateRequest = Schemas["SessionCreateRequest"];
export type Session = Schemas["SessionResponse"];
export type ResumeAccepted = Schemas["ResumeAcceptedResponse"];
export type ResumePreview = Schemas["ResumePreviewResponse"];
export type ResumeConfirm = Schemas["ResumeConfirmResponse"];
export type IntentConsultRequest = Schemas["IntentConsultRequest"];
export type IntentConsult = Schemas["IntentConsultResponse"];
export type MatchBriefRequest = Schemas["MatchBriefRequest"];
export type MatchBriefResponse = Schemas["MatchBriefResponse"];
export type ExecuteRunRequest = Schemas["ExecuteRunRequest"];
export type RunStatus = Schemas["RunStatusResponse"];
export type RunResult = Schemas["RunResultResponse"];
export type RunExplain = Schemas["RunExplainResponse"];
export type ReactionRequest = Schemas["ReactionRequest"];
export type ReactionResponse = Schemas["ReactionResponse"];
export type MonitoringOverview = Schemas["MonitoringOverviewResponse"];
export type RecentRuns = Schemas["RecentRunsResponse"];
export type EvidenceItem = Schemas["EvidenceItem"];
export type Recommendation = Schemas["RecommendationResult"];
export type SkillGap = Schemas["SkillGap"];

const id = (value: string): string => encodeURIComponent(value);

export const api = {
  capabilities: (): Promise<Capabilities> => apiRequest("/capabilities"),
  createSession: (body: SessionCreateRequest): Promise<Session> =>
    jsonRequest("/sessions", "POST", body),
  uploadResume: (sessionId: string, file: File): Promise<ResumeAccepted> =>
    uploadRequest(`/sessions/${id(sessionId)}/resume`, file),
  resumePreview: (sessionId: string): Promise<ResumePreview> =>
    apiRequest(`/sessions/${id(sessionId)}/resume-preview`),
  confirmResume: (sessionId: string): Promise<ResumeConfirm> =>
    apiRequest(`/sessions/${id(sessionId)}/resume-confirm`, { method: "POST" }),
  getIntentConsult: (sessionId: string): Promise<IntentConsult> =>
    apiRequest(`/sessions/${id(sessionId)}/intent-consult`),
  consultIntent: (sessionId: string, body: IntentConsultRequest): Promise<IntentConsult> =>
    jsonRequest(`/sessions/${id(sessionId)}/intent-consult`, "POST", body),
  createMatchBrief: (sessionId: string, body: MatchBriefRequest): Promise<MatchBriefResponse> =>
    jsonRequest(`/sessions/${id(sessionId)}/match-brief`, "POST", body),
  executeRun: (runId: string, body: ExecuteRunRequest): Promise<RunStatus> =>
    jsonRequest(`/runs/${id(runId)}/execute`, "POST", body),
  runStatus: (runId: string): Promise<RunStatus> => apiRequest(`/runs/${id(runId)}/status`),
  runResult: (runId: string): Promise<RunResult> => apiRequest(`/runs/${id(runId)}/result`),
  runExplain: (runId: string): Promise<RunExplain> => apiRequest(`/runs/${id(runId)}/explain`),
  addReaction: (runId: string, body: ReactionRequest): Promise<ReactionResponse> =>
    jsonRequest(`/runs/${id(runId)}/reaction`, "POST", body),
  monitoringOverview: (windowHours = 24): Promise<MonitoringOverview> =>
    apiRequest(`/monitoring/overview?window_hours=${windowHours}`),
  monitoringRuns: (windowHours = 24, limit = 20): Promise<RecentRuns> =>
    apiRequest(`/monitoring/runs?window_hours=${windowHours}&limit=${limit}`),
};
