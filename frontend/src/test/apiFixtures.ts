import type { components } from "../api/generated";

type Schemas = components["schemas"];
type AdminOverview = Schemas["AdminOverviewResponse"];
type AdminResetParseCount = Schemas["AdminResetParseCountResponse"];
type AdminUserResume = Schemas["AdminUserResumeResponse"];
type AdminUsersPage = Schemas["AdminUsersPageResponse"];
type Capabilities = Schemas["CapabilitiesResponse"];
type ConsultFinalize = Schemas["ConsultBriefDraftResponse"];
type ClarificationProgress = Schemas["ClarificationProgress"];
type ConsultState = Schemas["ConsultStateResponse"];
type ConsultTurn = Schemas["ConsultResponse"];
type MatchBriefResponse = Schemas["MatchBriefResponse"];
type Me = Schemas["MeResponse"];
type MeProfile = Schemas["ProfileResponse"];
type MeSessions = Schemas["MeSessionsResponse"];
type MonitoringOverview = Schemas["MonitoringOverviewResponse"];
type OtpAccepted = Schemas["OtpRequestAccepted"];
type ReactionResponse = Schemas["ReactionResponse"];
type RecentRuns = Schemas["RecentRunsResponse"];
type ResumeAccepted = Schemas["ResumeAcceptedResponse"];
type ResumeProgress = Schemas["ResumeProgressResponse"];
type ResumeUploaded = Schemas["ResumeUploadedResponse"];
type ResumeConfirm = Schemas["ResumeConfirmResponse"];
type ResumePreview = Schemas["ResumePreviewResponse"];
type RunConversation = Schemas["RunConversationResponse"];
type RunExplain = Schemas["RunExplainResponse"];
type RunResult = Schemas["RunResultResponse"];
type RunStatus = Schemas["RunStatusResponse"];
type Session = Schemas["SessionResponse"];
type SupervisorNote = Schemas["SupervisorNote"];

type ConsultStateFixtureOptions = {
  supervisor_notes?: SupervisorNote[];
  clarification_progress?: Partial<ClarificationProgress>;
};

type ConsultTurnFixtureOptions = {
  clarification_progress?: Partial<ClarificationProgress>;
};

export const RUN_STAGES = [
  "resume",
  "intent",
  "retrieval",
  "strategy",
  "verification",
  "finalization",
  "result",
] as const;

const updatedAt = "2026-08-05T09:05:00Z";

function recommendation(index: number) {
  return {
    job_id: `job-e2e-${index}`,
    title: index === 1 ? "Backend Engineer" : `Backend Engineer ${index}`,
    company: "示例科技",
    location: "Shanghai",
    tier: index === 1 ? ("now_fit" as const) : ("stretch_fit" as const),
    concise_explanation: "你的 Python 服务经验与该岗位要求直接对应。",
    why_this_match: ["JD 要求 Python 服务开发"],
    evidence: [
      {
        evidence_span_id: `job-e2e-${index}:skills:1`,
        field: "required_skills",
        content: "Python, SQL required.",
      },
    ],
    resume_evidence: [
      { evidence_span_id: "R001", field: "resume", content: "Built a Python service." },
    ],
    source_url: index === 1 ? "https://jobs.example.com/e2e-backend" : null,
    listing_kind: index === 1 ? ("source_url" as const) : ("dataset_only" as const),
    demo_synthetic: true,
    country_code: "CN" as const,
  };
}

function consultProfile(round: number): Schemas["ConsultProfileDraft"] {
  return {
    current_goal: round >= 1 ? ["backend engineer"] : [],
    hard_constraints:
      round >= 2
        ? { locations: ["Shanghai"], need_visa_sponsor: false }
        : round >= 1
          ? { locations: ["Shanghai"] }
          : {},
    soft_preferences: {},
    avoid_roles: [],
  };
}

function consultCompleteness(round: number): number {
  if (round >= 2) return 0.6;
  if (round >= 1) return 0.4;
  return 0;
}

function clarificationProgress(
  overrides: Partial<ClarificationProgress> = {},
): ClarificationProgress {
  return {
    answered: 0,
    skipped: 0,
    total: 0,
    questions_used: 0,
    ...overrides,
  };
}

export const apiFixtures = {
  capabilities: (overrides: Partial<Capabilities> = {}) =>
    ({
      api_version: "v1",
      dual_space_enabled: true,
      resume_image_upload_enabled: true,
      execution_durability: "process_local",
      explain_enabled: false,
      monitoring_enabled: false,
      otp_channels: ["email", "phone"],
      ...overrides,
    }) satisfies Capabilities,

  otpAccepted: () => ({ status: "otp_accepted" }) satisfies OtpAccepted,

  me: (isAdmin = false) =>
    ({
      user_id: "user-e2e-0001",
      status: "active",
      is_admin: isAdmin,
      display_name: isAdmin ? "考官" : "测试同学",
      avatar_url: null,
      last_login_at: null,
      created_at: "2026-08-01T08:00:00Z",
    }) satisfies Me,

  adminOverview: (overrides: Partial<AdminOverview> = {}) =>
    ({
      users_total: 42,
      logins_today: 5,
      logins_7d: 19,
      logins_30d: 31,
      sessions_total: 76,
      consult_turns_total: 114,
      runs_total: 38,
      tokens_by_day: [
        { date: "2026-08-08", total_tokens: 1200 },
        { date: "2026-08-09", total_tokens: 1800 },
      ],
      tokens_by_model: [
        {
          model: "deepseek-v4-flash",
          prompt_tokens: 1_000_000,
          completion_tokens: 500_000,
          total_tokens: 1_500_000,
        },
      ],
      ...overrides,
    }) satisfies AdminOverview,

  adminUsers: (overrides: Partial<AdminUsersPage> = {}) =>
    ({
      items: [
        {
          user_id: "user-e2e-0001",
          email: "student@example.com",
          created_at: "2026-08-01T08:00:00Z",
          last_login_at: "2026-08-09T08:30:00Z",
          session_count: 2,
          resume_name: "张三",
          resume_phone: null,
          resume_school: "Demo University",
          resume_degree: "MSc",
        },
      ],
      page: 1,
      page_size: 20,
      has_more: false,
      ...overrides,
    }) satisfies AdminUsersPage,

  adminUserResume: (overrides: Partial<AdminUserResume> = {}) =>
    ({
      user_id: "user-e2e-0001",
      session_id: "sess-e2e-1",
      resume_state: {
        contact: { name: "张三", phone: "13800000000", email: "student@example.com" },
        skills: ["Python", "SQL"],
      },
      reset_session_id: "sess-e2e-1",
      ...overrides,
    }) satisfies AdminUserResume,

  adminResetParseCount: (overrides: Partial<AdminResetParseCount> = {}) =>
    ({
      session_id: "sess-e2e-1",
      resume_parse_count: 0,
      status: "resume_uploaded",
      ...overrides,
    }) satisfies AdminResetParseCount,

  adminRunExplain: (runId = "run-e2e-1") =>
    ({
      run_id: runId,
      fusion: { implicit_max_weight: 0.2 },
      rank_trace: [
        {
          job_id: "job-e2e-1",
          explicit_rank: 1,
          implicit_rank: 2,
          final_rank: 1,
          implicit_weight: 0.2,
        },
      ],
      recovery_events: [],
      stage_durations_ms: { retrieval: 1800 },
    }) satisfies RunExplain,

  profile: () => ({ profile: {}, updated_at: updatedAt }) satisfies MeProfile,

  sessions: (sessionId: string | null = "sess-e2e-1") =>
    ({
      sessions: sessionId ? [{ session_id: sessionId, status: "active", updated_at: updatedAt }] : [],
      page: 1,
      page_size: 30,
      has_more: false,
    }) satisfies MeSessions,

  session: (sessionId = "sess-e2e-1") =>
    ({ session_id: sessionId, status: "awaiting_resume" }) satisfies Session,

  resumeAccepted: () =>
    ({ session_id: "sess-e2e-1", status: "resume_queued" }) satisfies ResumeAccepted,

  resumeUploaded: (overrides: Partial<ResumeUploaded> = {}) =>
    ({
      session_id: "sess-e2e-1",
      status: "resume_uploaded",
      generation: 1,
      filename: "resume.pdf",
      pages: 2,
      chars: 1800,
      text_preview: "张三 数据分析实习……",
      parses_used: 0,
      parses_limit: 3,
      ocr_suggested: false,
      ...overrides,
    }) satisfies ResumeUploaded,

  // B3：解析进度（mock 跳过归一化耗时，默认给终态完整叙事）
  resumeProgress: (overrides: Partial<ResumeProgress> = {}) =>
    ({
      generation: 1,
      status: "resume_ready",
      events: [
        {
          seq: 1,
          step: "received",
          text: "收到！我现在就把你的简历完整读一遍～",
          elapsed_ms: 6,
          created_at: "2026-08-09T10:00:00Z",
        },
        {
          seq: 100,
          step: "done",
          text: "档案生成完毕，用时 3.2 秒。来看看整理结果吧！",
          elapsed_ms: 3200,
          created_at: "2026-08-09T10:00:03Z",
        },
      ],
      done: true,
      ...overrides,
    }) satisfies ResumeProgress,

  resumePreview: (confirmed: boolean) =>
    ({
      session_id: "sess-e2e-1",
      resume_version: 1,
      confirmed,
      education: [
        {
          institution: "Demo University",
          degree: "MSc",
          field: "CS",
          dates: "2024-2025",
          details: [],
          evidence_span_ids: ["R002"],
        },
      ],
      experience: [
        {
          organization: "Demo Co",
          title: "Engineer",
          location: "Shanghai",
          dates: "2025-2026",
          responsibilities: ["Built a Python service."],
          achievements: [],
          technologies: ["Python", "SQL"],
          evidence_span_ids: ["R001"],
        },
      ],
      projects: [
        {
          name: "Career RAG",
          summary: "Evidence-grounded career matching",
          dates: "2026",
          actions: ["Implemented RRF fusion"],
          outcomes: ["Produced traceable recommendations"],
          technologies: ["FastAPI", "pgvector"],
          evidence_span_ids: ["R003"],
        },
      ],
      skills: ["Python", "SQL"],
      resume_quality_issues: ["补充更多量化结果"],
      evidence: [
        { evidence_span_id: "R001", content: "Built a Python service." },
        { evidence_span_id: "R002", content: "MSc in Computer Science." },
        { evidence_span_id: "R003", content: "Built an evidence-grounded career matcher." },
      ],
    }) satisfies ResumePreview,

  resumeConfirm: () =>
    ({
      session_id: "sess-e2e-1",
      resume_version: 1,
      confirmed: true,
      confirmed_at: "2026-08-05T09:01:00Z",
    }) satisfies ResumeConfirm,

  consultState: (round: number, options: ConsultStateFixtureOptions = {}) =>
    ({
      transcript: Array.from({ length: round }, (_, index) => ({
        round: index + 1,
        user_message: `用户第 ${index + 1} 轮`,
        assistant_reply: `明白了（第 ${index + 1} 轮）。`,
        next_question: index + 1 >= 2 ? "还有想补充的吗？" : "你更看重地点还是方向？",
        phase: index === 0 ? ("template" as const) : ("deepen" as const),
        ...(index + 1 === round && options.supervisor_notes
          ? { supervisor_notes: options.supervisor_notes }
          : {}),
      })),
      profile_draft: consultProfile(round),
      round,
      phase: round === 0 ? ("template" as const) : ("deepen" as const),
      completeness: consultCompleteness(round),
      can_finalize: round >= 2,
      clarification_progress: clarificationProgress(options.clarification_progress),
    }) satisfies ConsultState,

  consultTurn: (round: number, options: ConsultTurnFixtureOptions = {}) =>
    ({
      assistant_reply: `明白了（第 ${round} 轮）。`,
      next_question: round >= 2 ? "还有想补充的吗？" : "你更看重地点还是方向？",
      phase: round === 1 ? "template" : "deepen",
      completeness: consultCompleteness(round),
      can_finalize: round >= 2,
      round,
      profile_draft: consultProfile(round),
      clarification_progress: clarificationProgress(options.clarification_progress),
    }) satisfies ConsultTurn,

  supervisorNote: (overrides: Partial<SupervisorNote> = {}) =>
    ({
      kind: "coach",
      trigger: "deepen_entry",
      text: "方向已经明确，下一轮补充岗位取舍依据。",
      verdict: "advise",
      coach_attempt_id: "coach-e2e-1",
      ...overrides,
    }) satisfies SupervisorNote,

  consultFinalize: () =>
    ({
      career_goal: "Find backend engineer roles matching my Python experience",
      hard_constraints: { locations: ["Shanghai"], need_visa_sponsor: false },
      soft_preferences: { preferred_industries: ["tech"] },
      avoid_roles: ["sales"],
      result_count: 5,
    }) satisfies ConsultFinalize,

  matchBrief: () =>
    ({
      run_id: "run-e2e-1",
      session_id: "sess-e2e-1",
      brief: {
        career_goal: "Find backend engineer roles matching my Python experience",
        hard_constraints: { locations: ["Shanghai"], need_visa_sponsor: false },
        soft_preferences: { preferred_industries: ["tech"] },
        avoid_roles: ["sales"],
        result_count: 5,
        needs_clarification: false,
        plan_version: 1,
        plan_hash: "b".repeat(64),
      },
    }) satisfies MatchBriefResponse,

  runStatus: ({
    status,
    stage,
    completedStages,
    resultReady,
    retryAfterMs,
  }: {
    status: string;
    stage: string | null;
    completedStages: readonly string[];
    resultReady: boolean;
    retryAfterMs: number | null;
  }) =>
    ({
      run_id: "run-e2e-1",
      session_id: "sess-e2e-1",
      status,
      stage,
      result_ready: resultReady,
      plan_version: 1,
      plan_hash: "b".repeat(64),
      retry_after_ms: retryAfterMs,
      completed_stages: [...completedStages],
      total_stages: RUN_STAGES.length,
      warning_codes: [],
      error_code: null,
      execution_durability: "process_local",
      updated_at: updatedAt,
    }) satisfies RunStatus,

  runConversation: (
    status: string,
    nextPollMs: number | null,
    recommendationCount = 1,
  ) => {
    const messages: RunConversation["messages"] = [
      {
        seq: 1,
        persona: "pm",
        display_name: "项目经理·PM",
        kind: "intro",
        stage: "intent",
        text: "欢迎来到职业规划服务群。我是项目经理 PM，本次由需求顾问小意、岗位顾问小检和规划师小策协作，依次完成需求确认、岗位检索、策略规划与发布核查。我们会如实说明匹配依据与限制，建议不代表 offer 承诺。",
      },
      {
        seq: 2,
        persona: "intent_consultant",
        display_name: "需求顾问·小意",
        kind: "brief",
        stage: "intent",
        text: "本次需求已确认：目标「Find backend engineer roles matching my Python experience」；硬条件——地点 Shanghai、不需要签证担保；排序偏好——preferred_industries tech；暂不考虑：sales。接下来小检会基于你的完整简历档案 + 以上条件开始检索。",
      },
      {
        seq: 3,
        persona: "pm",
        display_name: "项目经理·PM",
        kind: "checkpoint",
        stage: "intent",
        text: "我确认小检接收的约束与确认单一致，现交给小检执行。",
      },
      {
        seq: 4,
        persona: "job_scout",
        display_name: "岗位顾问·小检",
        kind: "progress",
        stage: "retrieval",
        text: "我已接手确认单，岗位检索正在执行：适用的 metadata 条件筛选 → BM25/Dense 并行 → job_id 级 RRF 融合。你要求的 Shanghai 我已锁定为硬条件，绝不放宽。",
      },
      {
        seq: 5,
        persona: "job_scout",
        display_name: "岗位顾问·小检",
        kind: "progress",
        stage: "retrieval",
        text: "检索与融合已完成，候选集已提交 PM 进行交接检查。",
      },
      {
        seq: 6,
        persona: "pm",
        display_name: "项目经理·PM",
        kind: "checkpoint",
        stage: "retrieval",
        text: "小检返回了 2 个候选；我核对了候选集、排序与证据完整性，现交给小策。",
      },
      {
        seq: 7,
        persona: "strategist",
        display_name: "规划师·小策",
        kind: "progress",
        stage: "strategy",
        text: "我正在基于候选岗位开展能力缺口分析，并生成有证据约束的简历建议与职业路径；所有建议只引用简历原始证据和用户确认的澄清证据，不补写未经证实的经历。",
      },
      {
        seq: 8,
        persona: "strategist",
        display_name: "规划师·小策",
        kind: "progress",
        stage: "strategy",
        text: "缺口分析与简历建议已生成，现提交 PM 做最终发布核查。如果你之后想让我基于某个岗位细化简历，可在结果卡提交反馈或开启新咨询。",
      },
      {
        seq: 9,
        persona: "pm",
        display_name: "项目经理·PM",
        kind: "checkpoint",
        stage: "verification",
        text: "进入最终核查检查点：检查硬约束、JD/简历证据可追溯性、建议可执行性与结果完整性。必要时只允许一次受控重检索或修复。",
      },
      {
        seq: 10,
        persona: "strategist",
        display_name: "规划师·小策",
        kind: "result",
        stage: "result",
        text: `岗位分析完成：Now Fit ${recommendationCount > 0 ? 1 : 0} 个、Stretch Fit ${Math.max(recommendationCount - 1, 0)} 个、Bridge Role 0 个。下面把结果发给你，每个岗位都附证据与建议。`,
      },
      {
        seq: 11,
        persona: "pm",
        display_name: "项目经理·PM",
        kind: "result",
        stage: "result",
        text: "结果已发布。投递后欢迎回来在对应岗位卡上提交进展（被拒/过筛/面试/Offer），这些反馈会帮助我们持续校准推荐。匹配结果仅供求职决策参考，不构成 offer 承诺。",
      },
    ];
    // 真实投影对 completed 与 completed_with_warnings 都会生成 result 消息
    // （conversation_projector.py），fixture 语义保持一致。
    const resultReady = status === "completed" || status === "completed_with_warnings";
    return {
      run_id: "run-e2e-1",
      status,
      stage: resultReady ? "result" : "retrieval",
      next_poll_ms: nextPollMs,
      // 消息随进度渐进出现：终局的小策分析与 PM 收尾只在完成态下发，
      // 与真实后端投影语义一致（运行中不得预告结果）。
      messages: resultReady ? messages : messages.slice(0, 4),
    } satisfies RunConversation;
  },

  runResult: (recommendationCount = 1) =>
    ({
      run_id: "run-e2e-1",
      status: "completed",
      result: {
        summary: `${recommendationCount} evidence-grounded roles recommended.`,
        recommended_roles: Array.from({ length: recommendationCount }, (_, index) =>
          recommendation(index + 1),
        ),
        resume_strategy: [
          {
            section: "experience",
            suggestion: "量化你的服务性能收益。",
            evidence_span_ids: ["R001"],
          },
        ],
        skill_gaps: [],
        career_path: [],
        warnings: [],
      },
    }) satisfies RunResult,

  reaction: (feedbackId: number) =>
    ({
      feedback_id: feedbackId,
      run_id: "run-e2e-1",
      status: "reaction_recorded",
    }) satisfies ReactionResponse,

  monitoringOverview: () =>
    ({
      window_hours: 24,
      generated_at: "2026-07-13T12:00:00Z",
      total_runs: 12,
      completion_rate: 0.75,
      failure_rate: 0.08,
      warning_rate: 0.16,
      duration_p50_ms: 12000,
      duration_p95_ms: 42000,
      average_recommendation_count: 4.4,
      jd_evidence_coverage_rate: 1,
      implicit_usage_rate: 0.5,
      reordered_run_count: 3,
      status_counts: { completed: 9, failed: 1 },
      stage_latencies: [{ stage: "retrieval", p50_ms: 2000, p95_ms: 6000 }],
    }) satisfies MonitoringOverview,

  recentRuns: () =>
    ({
      window_hours: 24,
      generated_at: "2026-07-13T12:00:00Z",
      runs: [
        {
          run_id: "run-safe-001",
          status: "completed",
          stage: "result",
          recommendation_count: 5,
          duration_ms: 24000,
          error_code: null,
          warning_codes: [],
          created_at: "2026-07-13T11:59:00Z",
          started_at: "2026-07-13T11:59:01Z",
          finished_at: "2026-07-13T11:59:25Z",
          updated_at: "2026-07-13T11:59:25Z",
        },
      ],
    }) satisfies RecentRuns,
};
