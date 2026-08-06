import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LoaderCircle, Paperclip, Send, Sparkles } from "lucide-react";
import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { ApiError } from "../api/client";
import {
  api,
  type ConsultFinalize,
  type ConsultTranscriptEntry,
  type ConversationMessage,
  type MatchBriefResponse,
  type Recommendation,
  type RunConversation,
  type RunStatus,
} from "../api/queries";
import { EvidenceDrawer } from "../features/results/EvidenceDrawer";
import { ReactionForm } from "../features/feedback/ReactionForm";
import { deriveConsultSlots } from "./consultSlots";
import { readLastRun, removeLastRun, writeLastRun } from "./localRunStorage";
import { deriveServiceProgress, type ServiceProgressItem } from "./runProgress";
import { useProtectedTimelineScroll } from "./useProtectedTimelineScroll";
import "./theme.css";

const TERMINAL = new Set(["completed", "completed_with_warnings", "failed", "stale", "cancelled"]);

/**
 * 焦点管理弹窗：初始焦点落在容器（避免默认聚焦到会消耗额度的确认按钮）、
 * Escape 关闭、Tab 循环约束、关闭后焦点归还打开前的触发元素。
 * 模式与 EvidenceDrawer 保持一致。
 */
function FocusModal({
  label,
  onClose,
  closeDisabled = false,
  modeKey,
  children,
}: {
  label: string;
  onClose: () => void;
  closeDisabled?: boolean;
  /** 同一实例内切换内容（如 confirm→quota）时变化，触发容器重新聚焦 */
  modeKey?: string;
  children: ReactNode;
}) {
  const container = useRef<HTMLDivElement>(null);
  const restoreTo = useRef<HTMLElement | null>(null);

  useEffect(() => {
    restoreTo.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    return () => {
      const target = restoreTo.current;
      queueMicrotask(() => target?.focus());
    };
  }, []);

  useEffect(() => {
    container.current?.focus();
  }, [modeKey]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (!closeDisabled) onClose();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = Array.from(
        container.current?.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      );
      if (!focusable.length) {
        event.preventDefault();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && (active === first || active === container.current)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (active === last || active === container.current)) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [closeDisabled, onClose]);

  return (
    <div className="v2-modal-backdrop" role="dialog" aria-modal="true" aria-label={label}>
      <div className="v2-modal" ref={container} tabIndex={-1}>
        {children}
      </div>
    </div>
  );
}

export const PERSONAS: Record<string, { short: string; name: string; role: string }> = {
  intent_consultant: { short: "意", name: "需求顾问·小意", role: "需求对接" },
  job_scout: { short: "检", name: "岗位顾问·小检", role: "岗位筛选" },
  strategist: { short: "策", name: "规划师·小策", role: "职业规划" },
  pm: { short: "PM", name: "项目经理·PM", role: "监督 · A2A" },
  user: { short: "你", name: "你", role: "" },
};

const RUN_MESSAGE_STAGE_LABELS: Record<string, string> = {
  resume: "简历整理",
  intent: "需求确认",
  retrieval: "岗位检索",
  strategy: "策略规划",
  verification: "发布核查",
  finalization: "发布整理",
  result: "结果发布",
};

function runMessageStageLabel(stage: string): string {
  return RUN_MESSAGE_STAGE_LABELS[stage] ?? "运行进展";
}

export function conversationInterval(
  data: Pick<RunConversation, "status" | "next_poll_ms"> | undefined,
): number | false {
  if (!data || TERMINAL.has(data.status) || data.next_poll_ms == null) return false;
  return data.next_poll_ms;
}

export function statusInterval(
  data: Pick<RunStatus, "status" | "retry_after_ms"> | undefined,
): number | false {
  if (!data || TERMINAL.has(data.status) || data.retry_after_ms == null) return false;
  return data.retry_after_ms;
}

function Bubble({
  persona,
  children,
  tone,
  sticky = false,
  grouped = false,
  metadata,
}: {
  persona: keyof typeof PERSONAS;
  children: React.ReactNode;
  tone?: "card";
  sticky?: boolean;
  grouped?: boolean;
  metadata?: { kind: "stage" | "round"; text: string };
}) {
  const meta = PERSONAS[persona] ?? PERSONAS.pm;
  const mine = persona === "user";
  return (
    <li
      className={`${mine ? "v2-msg mine" : "v2-msg"}${sticky ? " v2-progress-message" : ""}`}
      data-persona={persona}
      data-sticky={sticky ? "true" : undefined}
      data-grouped={grouped ? "true" : undefined}
      tabIndex={metadata ? 0 : undefined}
    >
      {!mine && !grouped ? (
        <span className="v2-avatar" aria-hidden="true">
          {meta.short}
        </span>
      ) : null}
      <div className={tone === "card" ? "v2-bubble card" : "v2-bubble"}>
        {!mine && !grouped ? (
          <header>
            <strong>{meta.name}</strong>
            {meta.role ? <span>{meta.role}</span> : null}
          </header>
        ) : null}
        {children}
        {metadata ? (
          <small className="v2-message-meta" data-meta-kind={metadata.kind}>
            {metadata.text}
          </small>
        ) : null}
      </div>
    </li>
  );
}

function progressMarker(item: ServiceProgressItem): string {
  if (item.state === "complete") return "✓";
  if (item.state === "interrupted") return "!";
  if (item.state === "current") return "●";
  return "—";
}

function ServiceProgressCard({
  status,
  hasRecovery,
  sticky,
}: {
  status: RunStatus | undefined;
  hasRecovery: boolean;
  sticky: boolean;
}) {
  const progress = deriveServiceProgress(status, hasRecovery);
  return (
    <Bubble persona="pm" tone="card" sticky={sticky}>
      <section className="v2-service-progress" aria-label="服务进度">
        <div className="v2-progress-heading">
          <strong>服务进度</strong>
          <span role="status" aria-label="服务运行状态">
            {progress.summary}
          </span>
        </div>
        <ol className="v2-progress-list">
          {progress.items.map((item) => (
            <li
              key={item.id}
              data-state={item.state}
              data-actor={item.actor ?? undefined}
              data-pulsing={item.state === "current" ? String(item.pulsing) : undefined}
              aria-current={item.state === "current" ? "step" : undefined}
            >
              <span className="v2-progress-marker" aria-hidden="true">
                {progressMarker(item)}
              </span>
              <span className="v2-progress-copy">
                <strong>{item.label}</strong>
                <small>{item.detail}</small>
                {item.recovery ? <small className="v2-progress-recovery">↻ 质量把关：受控重检</small> : null}
              </span>
            </li>
          ))}
        </ol>
      </section>
    </Bubble>
  );
}

function BriefCard({
  draft,
  brief,
  onConfirm,
  confirming,
  confirmed,
}: {
  draft: ConsultFinalize;
  brief: MatchBriefResponse | null;
  onConfirm: () => void;
  confirming: boolean;
  confirmed: boolean;
}) {
  const hard = draft.hard_constraints ?? {};
  return (
    <div className="v2-brief">
      <p className="v2-brief-title">Match Brief 确认单</p>
      <dl>
        <div>
          <dt>目标</dt>
          <dd>{draft.career_goal}</dd>
        </div>
        <div>
          <dt>硬条件（锁定）</dt>
          <dd>
            {Object.entries(hard).length
              ? Object.entries(hard)
                  .map(([key, value]) => `${key}: ${JSON.stringify(value)}`)
                  .join("；")
              : "无"}
          </dd>
        </div>
        <div>
          <dt>暂不考虑</dt>
          <dd>{draft.avoid_roles?.length ? draft.avoid_roles.join("、") : "无"}</dd>
        </div>
        <div>
          <dt>结果数量</dt>
          <dd>{draft.result_count}</dd>
        </div>
      </dl>
      {confirmed && brief ? (
        <p className="v2-notice">已确认，任务 {brief.run_id.slice(0, 8)} 开始执行。</p>
      ) : (
        <button type="button" className="v2-btn primary" disabled={confirming} onClick={onConfirm}>
          {confirming ? "创建中…" : "确认无误，开始匹配"}
        </button>
      )}
    </div>
  );
}

function ResultCards({
  runId,
  anchorRef,
  highlighted,
}: {
  runId: string;
  anchorRef: React.RefObject<HTMLDivElement | null>;
  highlighted: boolean;
}) {
  const result = useQuery({
    queryKey: ["v2-result", runId],
    queryFn: () => api.runResult(runId),
  });
  
  if (result.isPending)
    return (
      <div
        ref={anchorRef}
        className={`v2-results${highlighted ? " is-highlighted" : ""}`}
        role="region"
        aria-label="匹配结果"
        tabIndex={-1}
      >
        <p className="v2-inline-loading">
          <LoaderCircle className="spin" size={15} /> 正在整理结果…
        </p>
      </div>
    );
  if (result.isError)
    return (
      <div
        ref={anchorRef}
        className={`v2-results${highlighted ? " is-highlighted" : ""}`}
        role="region"
        aria-label="匹配结果"
        tabIndex={-1}
      >
        <p className="v2-error">结果暂时无法读取，可稍后刷新。</p>
      </div>
    );
  const product = result.data.result;
  const resumeStrategy = product.resume_strategy ?? [];
  const skillGaps = product.skill_gaps ?? [];
  const careerPath = product.career_path ?? [];
  const warnings = product.warnings ?? [];
  const tierLabel: Record<string, string> = {
    now_fit: "现在就投",
    stretch_fit: "值得冲刺",
    bridge_role: "跳板岗位",
  };
  return (
    <div
      ref={anchorRef}
      className="v2-results"
      role="region"
      aria-label="匹配结果"
      tabIndex={-1}
    >
      {(product.recommended_roles ?? []).map((role: Recommendation, index: number) => (
        <article
          key={role.job_id}
          className={`v2-job-card${highlighted && index === 0 ? " is-highlighted" : ""}`}
        >
          <header>
            <span className={`v2-tier ${role.tier}`}>{tierLabel[role.tier] ?? role.tier}</span>
            {role.demo_synthetic ? (
              <span className="v2-demo-badge" title="该岗位来自合成演示语料，公司与城市为演示映射">
                演示数据{role.country_code ? ` · ${role.country_code}` : ""}
              </span>
            ) : null}
            <h3>{role.title ?? role.job_id}</h3>
            <p>
              {role.company ?? "—"} · {role.location ?? "—"}
            </p>
          </header>
          <p className="v2-job-why">{role.concise_explanation}</p>
          <EvidenceDrawer
            title={role.title ?? role.job_id}
            evidence={role.evidence ?? []}
            resumeEvidence={role.resume_evidence ?? []}
            agentMatchReasons={role.why_this_match ?? []}
          />
          <ReactionForm runId={runId} jobId={role.job_id} />
        </article>
      ))}
      {resumeStrategy.length ? (
        <details className="v2-extra">
          <summary>简历修改建议（{resumeStrategy.length} 条）</summary>
          <ul>
            {resumeStrategy.map((item, index) => (
              <li key={index}>
                <strong>{item.section}</strong>：{item.suggestion}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      {skillGaps.length ? (
        <details className="v2-extra">
          <summary>能力缺口（{skillGaps.length} 项）</summary>
          <ul>
            {skillGaps.map((gap, index) => (
              <li key={index}>
                <strong>{gap.skill}</strong>
                {gap.gap ? `：${gap.gap}` : null}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      {careerPath.length ? (
        <details className="v2-extra">
          <summary>职业路径</summary>
          <ul>
            {careerPath.map((step, index) => (
              <li key={index}>
                <strong>{step.horizon}</strong>：{step.action}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      {warnings.length ? (
        <p className="v2-warnings">提示：{warnings.join("、")}</p>
      ) : null}
    </div>
  );
}

export function WorkbenchPage() {
  const { sessionId = "" } = useParams();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const runId = searchParams.get("run");
  const queryClient = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: api.me, retry: false });
  const [message, setMessage] = useState("");
  const [mode, setMode] = useState<"targeted" | "explore">("targeted");
  const [briefDraft, setBriefDraft] = useState<ConsultFinalize | null>(null);
  const [brief, setBrief] = useState<MatchBriefResponse | null>(null);
  // 单一 modal 状态：confirm→quota 的 402 切换保持同一 FocusModal 实例，
  // 避免旧实例卸载时的焦点归还 microtask 把焦点抢回背景（互审第 2 轮阻断）
  const [retryModal, setRetryModal] = useState<"confirm" | "quota" | null>(null);
  const timelineRef = useRef<HTMLOListElement>(null);
  const resultRef = useRef<HTMLDivElement>(null);
  const messageInputRef = useRef<HTMLTextAreaElement>(null);
  const executeAttempted = useRef(false);

  const consult = useQuery({
    queryKey: ["consult", sessionId],
    queryFn: () => api.consultState(sessionId),
    enabled: Boolean(sessionId),
  });
  const preview = useQuery({
    queryKey: ["resume-preview", sessionId],
    queryFn: () => api.resumePreview(sessionId),
    enabled: Boolean(sessionId),
    retry: false,
    refetchInterval: (query) =>
      query.state.error instanceof ApiError && query.state.error.status === 409 ? 2500 : false,
  });
  const status = useQuery({
    queryKey: ["v2-run-status", runId],
    queryFn: () => api.runStatus(runId ?? ""),
    enabled: Boolean(runId),
    refetchInterval: (query) => statusInterval(query.state.data),
  });
  const conversation = useQuery({
    queryKey: ["v2-run-conv", runId],
    queryFn: () => api.runConversation(runId ?? ""),
    enabled: Boolean(runId),
    refetchInterval: (query) => conversationInterval(query.state.data),
  });

  const upload = useMutation({
    mutationFn: (file: File) => api.uploadResume(sessionId, file),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["resume-preview", sessionId] }),
  });
  const confirmResume = useMutation({
    mutationFn: () => api.confirmResume(sessionId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["resume-preview", sessionId] }),
  });
  const turn = useMutation({
    mutationFn: () =>
      api.consultTurn(sessionId, {
        mode,
        message: message.trim(),
        expected_round: consult.data?.round ?? 0,
      }),
    onSuccess: () => {
      setMessage("");
      // 继续咨询会改画像：作废已生成的旧确认单，防止确认到过期内容
      setBriefDraft(null);
      void queryClient.invalidateQueries({ queryKey: ["consult", sessionId] });
    },
  });
  const finalize = useMutation({
    mutationFn: () => api.consultFinalize(sessionId),
    onSuccess: (draft) => setBriefDraft(draft),
  });
  const confirmBrief = useMutation({
    mutationFn: () => {
      const draft = briefDraft;
      if (!draft) throw new Error("draft missing");
      return api.createMatchBrief(sessionId, {
        career_goal: draft.career_goal,
        hard_constraints: draft.hard_constraints ?? {},
        soft_preferences: draft.soft_preferences ?? {},
        avoid_roles: draft.avoid_roles ?? [],
        result_count: draft.result_count,
        needs_clarification: false,
      });
    },
    onSuccess: (created) => {
      if (me.data?.user_id) writeLastRun(me.data.user_id, sessionId, created.run_id);
      setBrief(created);
      executeAttempted.current = false;
      setSearchParams({ run: created.run_id }, { replace: true });
    },
  });
  const execute = useMutation({
    mutationFn: (payload: { runId: string; plan_version: number; plan_hash: string }) =>
      api.executeRun(payload.runId, {
        plan_version: payload.plan_version,
        plan_hash: payload.plan_hash,
      }),
    onSuccess: (_, payload) => {
      if (me.data?.user_id) writeLastRun(me.data.user_id, sessionId, payload.runId);
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) {
        if (me.data?.user_id && runId) writeLastRun(me.data.user_id, sessionId, runId);
        void status.refetch();
      }
    },
  });
  const createSession = useMutation({
    mutationFn: () => api.createSession({}),
    onSuccess: (session) => {
      setBriefDraft(null);
      setBrief(null);
      setRetryModal(null);
      executeAttempted.current = false;
      queryClient.removeQueries({ queryKey: ["consult", sessionId], exact: true });
      queryClient.removeQueries({ queryKey: ["resume-preview", sessionId], exact: true });
      if (runId) {
        queryClient.removeQueries({ queryKey: ["v2-run-status", runId], exact: true });
        queryClient.removeQueries({ queryKey: ["v2-run-conv", runId], exact: true });
        queryClient.removeQueries({ queryKey: ["v2-result", runId], exact: true });
      }
      void queryClient.invalidateQueries({ queryKey: ["me-sessions"] });
      navigate(`/app/sessions/${session.session_id}`);
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 402) {
        setRetryModal("quota");
      }
    },
  });

  useEffect(() => {
    if (runId || !me.data?.user_id || !sessionId) return;
    const storedRunId = readLastRun(me.data.user_id, sessionId);
    if (storedRunId) setSearchParams({ run: storedRunId }, { replace: true });
  }, [me.data?.user_id, runId, sessionId, setSearchParams]);

  useEffect(() => {
    if (!runId || !me.data?.user_id || !(status.error instanceof ApiError)) return;
    if (status.error.status !== 403 && status.error.status !== 404) return;
    removeLastRun(me.data.user_id, sessionId);
    setBrief(null);
    executeAttempted.current = false;
    queryClient.removeQueries({ queryKey: ["v2-run-status", runId], exact: true });
    queryClient.removeQueries({ queryKey: ["v2-run-conv", runId], exact: true });
    setSearchParams({}, { replace: true });
  }, [me.data?.user_id, queryClient, runId, sessionId, setSearchParams, status.error]);

  const resumeReady = preview.isSuccess;
  // 后端对"未上传"与"归一化中"同为 409（known_issues #6）：
  // 只有本次会话发起过上传时才把 409 解释为"处理中"，否则展示上传入口。
  const preview409 = preview.error instanceof ApiError && preview.error.status === 409;
  const resumeProcessing = preview409 && (upload.isPending || upload.isSuccess);
  const resumeConfirmed = resumeReady && Boolean(preview.data?.confirmed);

  // plan_ready 自动提交执行（幂等：409 视为已在执行）
  useEffect(() => {
    const data = status.data;
    if (!data || !runId) return;
    if (data.status === "plan_ready" && data.plan_hash && !executeAttempted.current) {
      executeAttempted.current = true;
      execute.mutate({ runId, plan_version: data.plan_version, plan_hash: data.plan_hash });
    }
  }, [status.data, runId, execute]);

  const transcript = consult.data?.transcript ?? [];
  const runMessages = (conversation.data?.messages ?? []).filter((item) => item.kind !== "intro");
  const running = Boolean(runId) && !TERMINAL.has(status.data?.status ?? "");
  const completed =
    status.data?.status === "completed" || status.data?.status === "completed_with_warnings";
  const retryableTerminal = ["failed", "stale", "cancelled"].includes(status.data?.status ?? "");

  const timelineContentKey = [
    resumeReady,
    resumeProcessing,
    transcript
      .map((entry) => [entry.round, entry.user_message, entry.assistant_reply, entry.next_question].join("~"))
      .join("|"),
    turn.isPending,
    Boolean(briefDraft),
    runMessages
      .map((item) => [item.seq, item.persona, item.kind, item.stage, item.text].join("~"))
      .join("|"),
    completed,
    retryableTerminal,
  ].join(":");
  const timelineScroll = useProtectedTimelineScroll({
    timelineRef,
    resultRef,
    contentKey: timelineContentKey,
    resultReady: completed,
    resetKey: `${sessionId}:${runId ?? "consult"}`,
  });

  const canConsult = resumeConfirmed && !runId;
  const inputDisabled = !canConsult || turn.isPending;
  const consultSlots = deriveConsultSlots(consult.data?.profile_draft);
  const completenessPercent = Math.round(
    Math.min(1, Math.max(0, consult.data?.completeness ?? 0)) * 100,
  );

  const consultBubbles = useMemo(
    () =>
      transcript.flatMap((entry: ConsultTranscriptEntry) => {
        const items: {
          key: string;
          persona: keyof typeof PERSONAS;
          text: string;
          round: number;
        }[] = [
          { key: `u-${entry.round}`, persona: "user", text: entry.user_message, round: entry.round },
          {
            key: `a-${entry.round}`,
            persona: "intent_consultant",
            text: `${entry.assistant_reply}${entry.next_question ? `\n${entry.next_question}` : ""}`,
            round: entry.round,
          },
        ];
        return items;
      }),
    [transcript],
  );

  if (!sessionId) return null;

  return (
    <section className="v2-workbench">
      <header className="v2-room-header">
        <div>
          <h1>职业规划服务群</h1>
          <p>
            {Object.values(PERSONAS)
              .filter((meta) => meta.role)
              .map((meta) => meta.name)
              .join(" · ")}
          </p>
        </div>
        {running ? (
          <span className="v2-room-status">
            <LoaderCircle className="spin" size={14} /> 服务进行中
          </span>
        ) : null}
      </header>

      <ol className="v2-timeline" ref={timelineRef} onScroll={timelineScroll.onScroll} aria-live="polite">
        <Bubble persona="pm">
          <p>
            欢迎来到职业规划服务群。我是项目经理 PM，小意负责需求、小检负责岗位、小策负责规划，
            我会在每个环节前后做质量把关。先请上传你的简历（PDF/DOCX/TXT）。
          </p>
        </Bubble>

        {!resumeReady && !resumeProcessing ? (
          <Bubble persona="intent_consultant" tone="card">
            <p>把简历发到群里，我先帮你整理成标准档案（每条都会标注原文出处）。</p>
            <label className="v2-btn ghost v2-upload">
              <Paperclip size={16} />
              {upload.isPending ? "上传中…" : "选择简历文件"}
              <input
                type="file"
                accept=".pdf,.docx,.txt"
                hidden
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) upload.mutate(file);
                }}
              />
            </label>
            {upload.isError ? <p className="v2-error">上传失败，请重试。</p> : null}
          </Bubble>
        ) : null}

        {resumeProcessing ? (
          <Bubble persona="intent_consultant">
            <p className="v2-inline-loading">
              <LoaderCircle className="spin" size={15} /> 正在归一化你的简历（解析 → 切证据片段 →
              结构化 → 防编造校验）…
            </p>
          </Bubble>
        ) : null}

        {resumeReady && !resumeConfirmed ? (
          <Bubble persona="intent_consultant" tone="card">
            <p>
              档案整理好了：{preview.data?.education?.length ?? 0} 段教育、
              {preview.data?.experience?.length ?? 0} 段经历、{preview.data?.skills?.length ?? 0}{" "}
              项技能。请确认无误后我们开始聊方向。
            </p>
            <button
              type="button"
              className="v2-btn primary"
              disabled={confirmResume.isPending}
              onClick={() => confirmResume.mutate()}
            >
              {confirmResume.isPending ? "确认中…" : "确认简历档案"}
            </button>
          </Bubble>
        ) : null}

        {consultBubbles.map((item) => (
          <Bubble
            key={item.key}
            persona={item.persona}
            metadata={{ kind: "round", text: `第 ${item.round} 轮` }}
          >
            <p style={{ whiteSpace: "pre-line" }}>{item.text}</p>
          </Bubble>
        ))}

        {turn.isPending ? (
          <Bubble persona="intent_consultant">
            <p className="v2-inline-loading">
              <LoaderCircle className="spin" size={15} /> 小意正在回复…
            </p>
          </Bubble>
        ) : null}

        {canConsult && consult.data?.can_finalize && !briefDraft ? (
          <Bubble persona="pm" tone="card">
            <p>
              信息已经足够完整（完成度 {Math.round((consult.data.completeness ?? 0) * 100)}%）。
              可以继续深聊，也可以现在生成 Match Brief 确认单。
            </p>
            <button
              type="button"
              className="v2-btn primary"
              disabled={finalize.isPending}
              onClick={() => finalize.mutate()}
            >
              <Sparkles size={16} />
              {finalize.isPending ? "生成中…" : "生成确认单"}
            </button>
          </Bubble>
        ) : null}

        {briefDraft ? (
          <Bubble persona="pm" tone="card">
            <BriefCard
              draft={briefDraft}
              brief={brief}
              confirmed={Boolean(brief)}
              confirming={confirmBrief.isPending}
              onConfirm={() => confirmBrief.mutate()}
            />
            {confirmBrief.isError ? (
              <p className="v2-error">创建失败，请重试或继续补充信息。</p>
            ) : null}
          </Bubble>
        ) : null}

        {runId ? (
          <ServiceProgressCard
            status={status.data}
            hasRecovery={runMessages.some((item) => item.kind === "recovery")}
            sticky={running}
          />
        ) : null}

        {runMessages.map((item: ConversationMessage, index) => {
          const previous = runMessages[index - 1];
          const startsStage = !previous || previous.stage !== item.stage;
          const grouped = !startsStage && previous.persona === item.persona;
          const stageLabel = runMessageStageLabel(item.stage);
          return (
            <Fragment key={`run-${item.seq}`}>
              {startsStage ? (
                <li className="v2-stage-divider" role="separator" aria-label={`运行阶段：${stageLabel}`}>
                  <span>{stageLabel}</span>
                </li>
              ) : null}
              <Bubble
                persona={item.persona}
                grouped={grouped}
                metadata={{ kind: "stage", text: `阶段 · ${stageLabel}` }}
              >
                <p style={{ whiteSpace: "pre-line" }}>{item.text}</p>
              </Bubble>
            </Fragment>
          );
        })}

        {completed && runId ? (
          <Bubble persona="pm" tone="card">
            <ResultCards
              runId={runId}
              anchorRef={resultRef}
              highlighted={timelineScroll.resultHighlighted}
            />
          </Bubble>
        ) : null}

        {retryableTerminal ? (
          <Bubble persona="pm">
            <p className="v2-error">
              {status.data?.status === "cancelled" ? "本次运行已取消" : "本次运行没有完成"}
              {status.data?.error_code ? `（${status.data.error_code}）` : null}。当前会话不能重新生成确认单，
              需要新建咨询后重试。
            </p>
            <button type="button" className="v2-btn primary" onClick={() => setRetryModal("confirm")}>
              新建咨询重试
            </button>
          </Bubble>
        ) : null}
      </ol>

      {timelineScroll.notice ? (
        <button
          type="button"
          className={`v2-new-message${timelineScroll.notice === "result" ? " result-ready" : ""}`}
          onClick={timelineScroll.followNotice}
        >
          {timelineScroll.notice === "result" ? "结果已生成 ↓" : "↓ 有新消息"}
        </button>
      ) : null}

      <footer className="v2-composer">
        {canConsult ? (
          <section className="v2-consult-slots" aria-label="咨询必填信息">
            <div className="v2-slot-chips">
              {consultSlots.map((slot) => (
                <button
                  key={slot.id}
                  type="button"
                  className="v2-slot-chip"
                  data-complete={String(slot.complete)}
                  disabled={slot.complete || inputDisabled}
                  onClick={() => {
                    messageInputRef.current?.focus();
                    if (message === "") setMessage(slot.prompt);
                  }}
                >
                  <span aria-hidden="true">{slot.complete ? "✓" : "○"}</span>
                  {slot.label}
                </button>
              ))}
            </div>
            <progress
              className="v2-completeness"
              aria-label="咨询信息完成度"
              aria-valuenow={completenessPercent}
              value={completenessPercent}
              max={100}
            />
          </section>
        ) : null}
        <div className="v2-mode-toggle" role="tablist" aria-label="咨询模式">
          <button
            role="tab"
            aria-selected={mode === "targeted"}
            onClick={() => setMode("targeted")}
          >
            目标明确
          </button>
          <button role="tab" aria-selected={mode === "explore"} onClick={() => setMode("explore")}>
            探索方向
          </button>
        </div>
        <textarea
          ref={messageInputRef}
          value={message}
          placeholder={
            canConsult
              ? "告诉小意你的想法…（回车发送，Shift+回车换行）"
              : runId
                ? "任务执行中，可在上方查看团队进展"
                : "请先上传并确认简历"
          }
          disabled={inputDisabled}
          maxLength={2000}
          onChange={(event) => setMessage(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              if (message.trim() && !inputDisabled) turn.mutate();
            }
          }}
        />
        <button
          type="button"
          className="v2-btn primary v2-send"
          disabled={inputDisabled || !message.trim()}
          onClick={() => turn.mutate()}
          aria-label="发送"
        >
          <Send size={17} />
        </button>
        {turn.isError ? (
          <p className="v2-error v2-composer-error">
            {turn.error instanceof ApiError && turn.error.status === 409
              ? "对话状态已更新，请刷新后继续。"
              : "发送失败，请重试。"}
          </p>
        ) : null}
      </footer>
      {retryModal ? (
        <FocusModal
          label={retryModal === "confirm" ? "新建咨询确认" : "额度已用完"}
          modeKey={retryModal}
          closeDisabled={retryModal === "confirm" && createSession.isPending}
          onClose={() => setRetryModal(null)}
        >
          {retryModal === "confirm" ? (
            <>
              <h2>新建咨询后重试</h2>
              <p>新建咨询会消耗一次咨询额度。创建成功后才会离开当前终态页面。</p>
              <div className="v2-modal-actions">
                <button
                  type="button"
                  className="v2-btn primary"
                  disabled={createSession.isPending}
                  onClick={() => createSession.mutate()}
                >
                  {createSession.isPending ? "创建中…" : "确认新建咨询"}
                </button>
                <button
                  type="button"
                  className="v2-btn ghost"
                  disabled={createSession.isPending}
                  onClick={() => setRetryModal(null)}
                >
                  保留当前页面
                </button>
              </div>
              {createSession.isError && !(createSession.error instanceof ApiError && createSession.error.status === 402) ? (
                <p className="v2-error">新咨询暂时无法创建，请重试。</p>
              ) : null}
            </>
          ) : (
            <>
              <h2>咨询额度已用完</h2>
              <p>当前账户的咨询额度已用完。原终态页面已保留。</p>
              <button type="button" className="v2-btn ghost" onClick={() => setRetryModal(null)}>
                返回当前页面
              </button>
            </>
          )}
        </FocusModal>
      ) : null}
    </section>
  );
}
