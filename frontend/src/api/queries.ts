import type { components } from "./generated";
import { apiRequest, jsonRequest, uploadRequest } from "./client";

type Schemas = components["schemas"];

export type Capabilities = Schemas["CapabilitiesResponse"];
export type SessionCreateRequest = Schemas["SessionCreateRequest"];
export type Session = Schemas["SessionResponse"];
export type ResumeAccepted = Schemas["ResumeAcceptedResponse"];
export type ResumeUploaded = Schemas["ResumeUploadedResponse"];
export type ResumeParseRequest = Schemas["ResumeParseRequest"];
export type ResumePreview = Schemas["ResumePreviewResponse"];
export type ResumeConfirmRequest = Schemas["ResumeConfirmRequest"];
export type ResumeConfirm = Schemas["ResumeConfirmResponse"];
export type MatchBriefRequest = Schemas["MatchBriefRequest"];
export type MatchBriefResponse = Schemas["MatchBriefResponse"];
export type ExecuteRunRequest = Schemas["ExecuteRunRequest"];
export type RunStatus = Schemas["RunStatusResponse"];
export type RunResult = Schemas["RunResultResponse"];
export type RunConversation = Schemas["RunConversationResponse"];
export type ConversationMessage = Schemas["ConversationMessageResponse"];
export type RunExplain = Schemas["RunExplainResponse"];
export type ReactionRequest = Schemas["ReactionRequest"];
export type ReactionResponse = Schemas["ReactionResponse"];
export type MonitoringOverview = Schemas["MonitoringOverviewResponse"];
export type RecentRuns = Schemas["RecentRunsResponse"];
export type OtpRequestBody = Schemas["OtpRequest"];
export type OtpAccepted = Schemas["OtpRequestAccepted"];
export type OtpVerifyBody = Schemas["OtpVerifyRequest"];
export type Me = Schemas["MeResponse"];
export type MeProfile = Schemas["ProfileResponse"];
export type MeProfilePatch = Schemas["ProfilePatchRequest"];
export type MeSessions = Schemas["MeSessionsResponse"];
export type MeSession = Schemas["MeSessionResponse"];
export type ConsultTurnRequest = Schemas["ConsultRequest"];
export type ConsultTurn = Schemas["ConsultResponse"];
export type ConsultState = Schemas["ConsultStateResponse"];
export type ConsultFinalize = Schemas["ConsultBriefDraftResponse"];
export type ConsultTranscriptEntry = Schemas["ConsultTranscriptEntry"];
export type EvidenceItem = Schemas["EvidenceItem"];
export type Recommendation = Schemas["RecommendationResult"];
export type SkillGap = Schemas["SkillGap"];

const id = (value: string): string => encodeURIComponent(value);

export const api = {
  capabilities: (): Promise<Capabilities> => apiRequest("/capabilities"),
  createSession: (body: SessionCreateRequest): Promise<Session> =>
    jsonRequest("/sessions", "POST", body),
  uploadResume: (sessionId: string, file: File): Promise<ResumeUploaded> =>
    uploadRequest(`/sessions/${id(sessionId)}/resume`, file),
  pendingResumeUpload: (sessionId: string): Promise<ResumeUploaded> =>
    apiRequest(`/sessions/${id(sessionId)}/resume-upload`),
  parseResume: (sessionId: string, body: ResumeParseRequest): Promise<ResumeAccepted> =>
    jsonRequest(`/sessions/${id(sessionId)}/resume/parse`, "POST", body),
  resumePreview: (sessionId: string): Promise<ResumePreview> =>
    apiRequest(`/sessions/${id(sessionId)}/resume-preview`),
  confirmResume: (sessionId: string, body: ResumeConfirmRequest): Promise<ResumeConfirm> =>
    jsonRequest(`/sessions/${id(sessionId)}/resume-confirm`, "POST", body),
  createMatchBrief: (sessionId: string, body: MatchBriefRequest): Promise<MatchBriefResponse> =>
    jsonRequest(`/sessions/${id(sessionId)}/match-brief`, "POST", body),
  executeRun: (runId: string, body: ExecuteRunRequest): Promise<RunStatus> =>
    jsonRequest(`/runs/${id(runId)}/execute`, "POST", body),
  runStatus: (runId: string): Promise<RunStatus> => apiRequest(`/runs/${id(runId)}/status`),
  runConversation: (runId: string): Promise<RunConversation> =>
    apiRequest(`/runs/${id(runId)}/conversation`),
  runResult: (runId: string): Promise<RunResult> => apiRequest(`/runs/${id(runId)}/result`),
  runExplain: (runId: string): Promise<RunExplain> => apiRequest(`/runs/${id(runId)}/explain`),
  addReaction: (runId: string, body: ReactionRequest): Promise<ReactionResponse> =>
    jsonRequest(`/runs/${id(runId)}/reaction`, "POST", body),
  monitoringOverview: (windowHours = 24): Promise<MonitoringOverview> =>
    apiRequest(`/monitoring/overview?window_hours=${windowHours}`),
  monitoringRuns: (windowHours = 24, limit = 20): Promise<RecentRuns> =>
    apiRequest(`/monitoring/runs?window_hours=${windowHours}&limit=${limit}`),
  // --- V2 auth / me / consult ---
  otpRequest: (body: OtpRequestBody): Promise<OtpAccepted> =>
    jsonRequest("/auth/otp/request", "POST", body),
  otpVerify: (body: OtpVerifyBody): Promise<Me> =>
    jsonRequest("/auth/otp/verify", "POST", body),
  logout: (): Promise<unknown> => apiRequest("/auth/logout", { method: "POST" }),
  me: (): Promise<Me> => apiRequest("/me"),
  meProfile: (): Promise<MeProfile> => apiRequest("/me/profile"),
  patchProfile: (body: MeProfilePatch): Promise<MeProfile> =>
    jsonRequest("/me/profile", "PATCH", body),
  meSessions: (page = 1, pageSize = 20): Promise<MeSessions> =>
    apiRequest(`/me/sessions?page=${page}&page_size=${pageSize}`),
  consultState: (sessionId: string): Promise<ConsultState> =>
    apiRequest(`/sessions/${id(sessionId)}/consult`),
  consultTurn: (sessionId: string, body: ConsultTurnRequest): Promise<ConsultTurn> =>
    jsonRequest(`/sessions/${id(sessionId)}/consult`, "POST", body),
  consultFinalize: (sessionId: string): Promise<ConsultFinalize> =>
    apiRequest(`/sessions/${id(sessionId)}/consult/finalize`, { method: "POST" }),
};
