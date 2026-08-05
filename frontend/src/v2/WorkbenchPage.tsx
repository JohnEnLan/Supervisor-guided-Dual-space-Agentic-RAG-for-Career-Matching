import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LoaderCircle, Paperclip, Send, Sparkles } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";

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
import "./theme.css";

const TERMINAL = new Set(["completed", "completed_with_warnings", "failed", "stale"]);

export const PERSONAS: Record<string, { short: string; name: string; role: string }> = {
  intent_consultant: { short: "意", name: "需求顾问·小意", role: "需求对接" },
  job_scout: { short: "检", name: "岗位顾问·小检", role: "岗位筛选" },
  strategist: { short: "策", name: "规划师·小策", role: "职业规划" },
  pm: { short: "PM", name: "项目经理·PM", role: "监督 · A2A" },
  user: { short: "你", name: "你", role: "" },
};

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
}: {
  persona: keyof typeof PERSONAS;
  children: React.ReactNode;
  tone?: "card";
}) {
  const meta = PERSONAS[persona] ?? PERSONAS.pm;
  const mine = persona === "user";
  return (
    <li className={mine ? "v2-msg mine" : "v2-msg"} data-persona={persona}>
      {!mine ? (
        <span className="v2-avatar" aria-hidden="true">
          {meta.short}
        </span>
      ) : null}
      <div className={tone === "card" ? "v2-bubble card" : "v2-bubble"}>
        {!mine ? (
          <header>
            <strong>{meta.name}</strong>
            {meta.role ? <span>{meta.role}</span> : null}
          </header>
        ) : null}
        {children}
      </div>
    </li>
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

function ResultCards({ runId }: { runId: string }) {
  const result = useQuery({
    queryKey: ["v2-result", runId],
    queryFn: () => api.runResult(runId),
  });
  
  if (result.isPending)
    return (
      <p className="v2-inline-loading">
        <LoaderCircle className="spin" size={15} /> 正在整理结果…
      </p>
    );
  if (result.isError) return <p className="v2-error">结果暂时无法读取，可稍后刷新。</p>;
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
    <div className="v2-results">
      {(product.recommended_roles ?? []).map((role: Recommendation) => (
        <article key={role.job_id} className="v2-job-card">
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
  const [searchParams, setSearchParams] = useSearchParams();
  const runId = searchParams.get("run");
  const queryClient = useQueryClient();
  const [message, setMessage] = useState("");
  const [mode, setMode] = useState<"targeted" | "explore">("targeted");
  const [briefDraft, setBriefDraft] = useState<ConsultFinalize | null>(null);
  const [brief, setBrief] = useState<MatchBriefResponse | null>(null);
  const timelineRef = useRef<HTMLOListElement>(null);
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
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) void status.refetch();
    },
  });

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
  const runMessages = conversation.data?.messages ?? [];
  const running = Boolean(runId) && !TERMINAL.has(status.data?.status ?? "");
  const completed =
    status.data?.status === "completed" || status.data?.status === "completed_with_warnings";

  const messageCount =
    transcript.length + runMessages.length + (briefDraft ? 1 : 0) + (completed ? 1 : 0);
  useEffect(() => {
    const timeline = timelineRef.current;
    if (timeline) timeline.scrollTop = timeline.scrollHeight;
  }, [messageCount, resumeReady]);

  const canConsult = resumeConfirmed && !runId;
  const inputDisabled = !canConsult || turn.isPending;

  const consultBubbles = useMemo(
    () =>
      transcript.flatMap((entry: ConsultTranscriptEntry) => {
        const items: { key: string; persona: keyof typeof PERSONAS; text: string }[] = [
          { key: `u-${entry.round}`, persona: "user", text: entry.user_message },
          {
            key: `a-${entry.round}`,
            persona: "intent_consultant",
            text: `${entry.assistant_reply}${entry.next_question ? `\n${entry.next_question}` : ""}`,
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

      <ol className="v2-timeline" ref={timelineRef} aria-live="polite">
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
          <Bubble key={item.key} persona={item.persona}>
            <p style={{ whiteSpace: "pre-line" }}>{item.text}</p>
          </Bubble>
        ))}

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

        {runMessages.map((item: ConversationMessage) => (
          <Bubble key={`run-${item.seq}`} persona={item.persona}>
            <p style={{ whiteSpace: "pre-line" }}>{item.text}</p>
          </Bubble>
        ))}

        {running ? (
          <li className="v2-typing">
            <LoaderCircle className="spin" size={14} /> 团队正在处理下一阶段…
          </li>
        ) : null}

        {completed && runId ? (
          <Bubble persona="pm" tone="card">
            <ResultCards runId={runId} />
          </Bubble>
        ) : null}

        {status.data?.status === "failed" || status.data?.status === "stale" ? (
          <Bubble persona="pm">
            <p className="v2-error">
              本次运行没有完成（{status.data.error_code ?? "RUN_FAILED"}）。可以重新生成确认单再试。
            </p>
          </Bubble>
        ) : null}
      </ol>

      <footer className="v2-composer">
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
    </section>
  );
}
