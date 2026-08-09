import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LoaderCircle, Paperclip, Send, Sparkles } from "lucide-react";
import { Fragment, useEffect, useId, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { ApiError } from "../api/client";
import {
  api,
  type ConsultFinalize,
  type ConsultState,
  type ConsultTranscriptEntry,
  type ConversationMessage,
  type MatchBriefResponse,
  type Recommendation,
  type ResumePreview,
  type ResumeProgress,
  type RunConversation,
  type RunStatus,
} from "../api/queries";
import { EvidenceDrawer } from "../features/results/EvidenceDrawer";
import { ReactionForm } from "../features/feedback/ReactionForm";
import { useLanguage, type Translate } from "../i18n";
import { deriveConsultSlots, type ConsultSlotState } from "./consultSlots";
import { FocusModal } from "./FocusModal";
import { readLastRun, removeLastRun, writeLastRun, writeSessionTitle } from "./localRunStorage";
import { ResumeProfileAccordion } from "./ResumeProfileAccordion";
import { deriveServiceProgress, type ServiceProgressItem } from "./runProgress";
import { useProtectedTimelineScroll } from "./useProtectedTimelineScroll";
import "./theme.css";

const TERMINAL = new Set(["completed", "completed_with_warnings", "failed", "stale", "cancelled"]);
type ResumeRecoveryState = "processing" | "updated" | "error";

function resumeRecoveryState(error: unknown): ResumeRecoveryState | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null;
  if (error.message === "resume_error") return "error";
  if (error.message === "resume_changed" || error.message === "resume_processing") return "processing";
  return null;
}

function resumeRecoveryMessage(state: ResumeRecoveryState): string {
  if (state === "processing") return "新简历处理中";
  if (state === "error") return "旧档案已作废，请重传";
  return "简历已更新，本轮未提交；请确认新档案后重试";
}

export function resumePreviewInterval(error: unknown): number | false {
  return resumeRecoveryState(error) === "processing" ? 2500 : false;
}

function supportedFormatsLabel(imageUploadEnabled: boolean): string {
  return imageUploadEnabled ? "PDF/DOCX/TXT/图片" : "PDF/DOCX/TXT";
}

function uploadErrorText(error: unknown, imageUploadEnabled: boolean): string {
  if (error instanceof ApiError) {
    if (error.status === 415) {
      return `暂不支持该文件格式（当前支持 ${supportedFormatsLabel(imageUploadEnabled)}）。`;
    }
    if (error.status === 422) return "文件无法解析，请确认未加密、未损坏后重试。";
    if (error.status === 413) return "文件超过 10MB 上限，请压缩后重试。";
  }
  return "上传失败，请重试。";
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

// B3 R2：解析叙事轮询节拍——done=已离开 resume_queued（含解析中重传的
// 新代 resume_uploaded），立即停轮询。
export const RESUME_PROGRESS_POLL_MS = 1200;

export function resumeProgressInterval(
  data: Pick<ResumeProgress, "done"> | undefined,
): number | false {
  if (data?.done) return false;
  return RESUME_PROGRESS_POLL_MS;
}

// B3 §3.2：档案摘要逐行文案——由 preview 数据纯函数合成（教育 1 行、每段
// 经历 1 行、每个项目 1 行、技能 1 行、末行指向完整档案）。
export function buildProfileSummaryLines(preview: ResumePreview | undefined): string[] {
  if (!preview) return [];
  const lines: string[] = [];
  const education = preview.education ?? [];
  if (education.length) {
    const first = education[0];
    const label = [first.institution, first.degree].filter(Boolean).join(" · ");
    lines.push(
      `🎓 教育：${label}${education.length > 1 ? `（等 ${education.length} 段）` : ""}`,
    );
  }
  for (const item of preview.experience ?? []) {
    const label = [item.organization, item.title].filter(Boolean).join(" · ");
    if (label) lines.push(`💼 经历：${label}`);
  }
  for (const item of preview.projects ?? []) {
    if (item.name) lines.push(`🧩 项目：${item.name}`);
  }
  const skills = preview.skills ?? [];
  if (skills.length) {
    lines.push(
      `🛠️ 技能：${skills.slice(0, 6).join("、")}${skills.length > 6 ? `（共 ${skills.length} 项）` : ""}`,
    );
  }
  lines.push("完整档案就在下方，点开可逐条核对原文出处 →");
  return lines;
}

function translatedProfileSummaryLines(
  preview: ResumePreview | undefined,
  t: Translate,
): string[] {
  if (!preview) return [];
  const lines: string[] = [];
  const education = preview.education ?? [];
  if (education.length) {
    const first = education[0];
    const label = [first.institution, first.degree].filter(Boolean).join(" · ");
    lines.push(
      education.length > 1
        ? t("🎓 教育：{label}（等 {count} 段）", { label, count: education.length })
        : t("🎓 教育：{label}", { label }),
    );
  }
  for (const item of preview.experience ?? []) {
    const label = [item.organization, item.title].filter(Boolean).join(" · ");
    if (label) lines.push(t("💼 经历：{label}", { label }));
  }
  for (const item of preview.projects ?? []) {
    if (item.name) lines.push(t("🧩 项目：{name}", { name: item.name }));
  }
  const skills = preview.skills ?? [];
  if (skills.length) {
    const visibleSkills = skills.slice(0, 6).join("、");
    lines.push(
      skills.length > 6
        ? t("🛠️ 技能：{skills}（共 {count} 项）", {
            skills: visibleSkills,
            count: skills.length,
          })
        : t("🛠️ 技能：{skills}", { skills: visibleSkills }),
    );
  }
  lines.push(t("完整档案就在下方，点开可逐条核对原文出处 →"));
  return lines;
}

function translatedConsultSlotLabel(slot: ConsultSlotState, t: Translate): string {
  if (slot.id === "goal") {
    return slot.complete
      ? t("目标：{value}", { value: slot.label.replace(/^目标：/, "") })
      : t("目标：待补充");
  }
  if (slot.id === "location") {
    if (!slot.complete) return t("地点：待补充");
    const value = slot.label.replace(/^地点：/, "");
    return t("地点：{value}", { value: value === "远程" ? t("远程") : value });
  }
  if (slot.id === "visa") {
    if (!slot.complete) return t("签证：待补充");
    const value = slot.label.replace(/^签证：/, "");
    return t("签证：{value}", { value: t(value) });
  }
  const progress = /^简历补充：已回答 (\d+)，已跳过 (\d+)，待补充 (\d+)$/.exec(slot.label);
  return progress
    ? t("简历补充：已回答 {answered}，已跳过 {skipped}，待补充 {remaining}", {
        answered: progress[1],
        skipped: progress[2],
        remaining: progress[3],
      })
    : slot.label;
}

// B1 R5：到场编排——只对"首批数据之后新增"的消息按批内顺序附加动画延迟。
// 基线在该 resetKey 下 keys **首次非空**时建立（评审 M1：resetKey 变化帧
// 几乎总是无数据帧，若在该帧建基线，异步到达的全量历史会被误判为新增而
// 重播）。批内延迟封顶 3 档（1350ms < 1500ms 轮询间隔，后批不会先于前批
// 可见）。reduced-motion 由 theme.css 全局禁动画兜底。
const STAGGER_STEP_MS = 450;
const STAGGER_MAX_STEPS = 3;

type StaggerSnapshot = {
  resetKey: string | null;
  baseline: Set<string> | null; // null=尚未见到首批数据
  delays: Map<string, number>;
};

export function useStaggeredReveal(
  keys: string[],
  resetKey: string,
  // Codex B3 审查 C8：本页自己发起的流（如确认解析的叙事）没有"历史"，
  // freshBaseline=true 时以空基线起步——首批同拍到达的事件也逐条编排；
  // false（默认）保持 B1 语义：首批非空 keys 视为历史，不重播。
  freshBaseline = false,
): (key: string) => React.CSSProperties | undefined {
  // 评审二轮 M（并发正确性）：渲染期只做"已提交快照 → 候选快照"的纯计算，
  // 提交发生在 effect（被丢弃的渲染不运行 effect，不会污染快照——旧实现
  // 的渲染期 ref 写入会让丢弃渲染预标 seen，改变后续提交帧的可观察样式）。
  const committed = useRef<StaggerSnapshot>({
    resetKey: null,
    baseline: null,
    delays: new Map(),
  });

  const base: StaggerSnapshot =
    committed.current.resetKey === resetKey
      ? committed.current
      : {
          resetKey,
          baseline: freshBaseline ? new Set<string>() : null,
          delays: new Map(),
        };

  let nextBaseline = base.baseline;
  const nextDelays = new Map(base.delays);
  if (nextBaseline === null) {
    if (keys.length > 0) {
      // 首批非空 keys＝历史基线：整批即时到场，不编排
      nextBaseline = new Set(keys);
    }
  } else {
    const tracked = nextBaseline;
    const fresh = keys.filter((key) => !tracked.has(key) && !nextDelays.has(key));
    if (fresh.length > 0) {
      nextBaseline = new Set(tracked);
      fresh.forEach((key, index) => {
        nextBaseline!.add(key);
        nextDelays.set(key, Math.min(index, STAGGER_MAX_STEPS) * STAGGER_STEP_MS);
      });
    }
  }

  useEffect(() => {
    committed.current = { resetKey, baseline: nextBaseline, delays: nextDelays };
  });

  return (key) => {
    const delay = nextDelays.get(key);
    return delay ? { animationDelay: `${delay}ms` } : undefined;
  };
}

function Bubble({
  persona,
  children,
  tone,
  sticky = false,
  grouped = false,
  metadata,
  style,
}: {
  persona: keyof typeof PERSONAS;
  children: React.ReactNode;
  tone?: "card";
  sticky?: boolean;
  grouped?: boolean;
  metadata?: { kind: "stage" | "round"; text: string };
  style?: React.CSSProperties;
}) {
  const { t } = useLanguage();
  const meta = PERSONAS[persona] ?? PERSONAS.pm;
  const mine = persona === "user";
  return (
    <li
      className={`${mine ? "v2-msg mine" : "v2-msg"}${sticky ? " v2-progress-message" : ""}`}
      data-persona={persona}
      data-sticky={sticky ? "true" : undefined}
      data-grouped={grouped ? "true" : undefined}
      tabIndex={metadata ? 0 : undefined}
      style={style}
    >
      {!mine && !grouped ? (
        <span className="v2-avatar" aria-hidden="true">
          {t(meta.short)}
        </span>
      ) : null}
      <div className={tone === "card" ? "v2-bubble card" : "v2-bubble"}>
        {!mine && !grouped ? (
          <header>
            <strong>{t(meta.name)}</strong>
            {meta.role ? <span>{t(meta.role)}</span> : null}
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
  const { t } = useLanguage();
  const progress = deriveServiceProgress(status, hasRecovery);
  return (
    <Bubble persona="pm" tone="card" sticky={sticky}>
      <section className="v2-service-progress" aria-label={t("服务进度")}>
        <div className="v2-progress-heading">
          <strong>{t("服务进度")}</strong>
          <span role="status" aria-label={t("服务运行状态")}>
            {t(progress.summary)}
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
                <strong>{t(item.label)}</strong>
                <small>{t(item.detail)}</small>
                {item.recovery ? <small className="v2-progress-recovery">{t("↻ 质量把关：受控重检")}</small> : null}
              </span>
            </li>
          ))}
        </ol>
      </section>
    </Bubble>
  );
}

function FinalizeAction({
  disabled,
  pending,
  onFinalize,
}: {
  disabled: boolean;
  pending: boolean;
  onFinalize: () => void;
}) {
  const { t } = useLanguage();
  return (
    <div className="v2-finalize-action">
      <button
        type="button"
        className="v2-btn primary"
        aria-label={t("生成确认单")}
        disabled={disabled}
        onClick={onFinalize}
      >
        <Sparkles size={16} />
        {pending ? t("生成中…") : t("生成确认单")}
      </button>
    </div>
  );
}

function finalizationMilestoneText(
  profile: ConsultState["profile_draft"],
  t: Translate,
): string {
  const [goal, location, visa] = deriveConsultSlots(profile);
  const value = (label: string) => label.replace(/^[^：]+：/, "");
  const locationValue = value(location.label);
  return t(
    "小意已把必填信息收集齐：目标 {goal}、地点 {location}、签证{visa}。你可以继续补充偏好，也可以让我安排匹配。",
    {
      goal: value(goal.label),
      location: locationValue === "远程" ? t("远程") : locationValue,
      visa: t(value(visa.label)).toLocaleLowerCase("en"),
    },
  );
}

const SUMMARY_FIELD_LABELS: Record<string, string> = {
  locations: "地点",
  need_visa_sponsor: "签证担保",
  preferred_locations: "偏好地点",
  preferred_role_clusters: "岗位簇",
  title_keywords: "关键词",
};

function summaryValue(value: unknown, t: Translate): string {
  if (value == null || value === "") return "";
  if (typeof value === "boolean") return value ? t("是") : t("否");
  if (Array.isArray(value)) {
    return value.map((item) => summaryValue(item, t)).filter(Boolean).join("、");
  }
  if (typeof value === "object") {
    return Object.entries(value)
      .map(([key, item]) => {
        const formatted = summaryValue(item, t);
        return formatted ? `${key} ${formatted}` : "";
      })
      .filter(Boolean)
      .join("、");
  }
  return String(value).trim();
}

function summaryText(
  value: Record<string, unknown> | null | undefined,
  emptyText: string,
  t: Translate,
): string {
  if (!value) return emptyText;
  const parts = Object.entries(value)
    .map(([key, item]) => {
      if (key === "need_visa_sponsor" && typeof item === "boolean") {
        return t(item ? "需要签证担保" : "不需要签证担保");
      }
      const formatted = summaryValue(item, t);
      if (!formatted) return "";
      const label = SUMMARY_FIELD_LABELS[key] ? t(SUMMARY_FIELD_LABELS[key]) : key;
      return `${label} ${formatted}`;
    })
    .filter(Boolean);
  return parts.join("、") || emptyText;
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
  const { t } = useLanguage();
  const hardSummary = summaryText(draft.hard_constraints, t("无额外限制"), t);
  const softSummary = summaryText(draft.soft_preferences, t("无额外偏好"), t);
  return (
    <div className="v2-brief">
      <p className="v2-brief-title">{t("需求摘要（Match Brief）")}</p>
      <dl>
        <div>
          <dt>{t("目标")}</dt>
          <dd>{draft.career_goal}</dd>
        </div>
        <div>
          <dt>{t("硬条件")}</dt>
          <dd>{hardSummary}</dd>
        </div>
        <div>
          <dt>{t("排序偏好")}</dt>
          <dd>{softSummary}</dd>
        </div>
        <div>
          <dt>{t("暂不考虑")}</dt>
          <dd>{draft.avoid_roles?.length ? draft.avoid_roles.join("、") : t("无")}</dd>
        </div>
        <div>
          <dt>{t("结果数量")}</dt>
          <dd>{draft.result_count}</dd>
        </div>
      </dl>
      <p className="v2-brief-guidance">
        {t("检索将基于你的完整简历档案 + 以上确认条件（硬条件数据库过滤，偏好参与排序）。")}
      </p>
      {confirmed && brief ? (
        <p className="v2-notice">{t("已确认，任务 {runId} 开始执行。", { runId: brief.run_id.slice(0, 8) })}</p>
      ) : (
        <button type="button" className="v2-btn primary" disabled={confirming} onClick={onConfirm}>
          {confirming ? t("创建中…") : t("确认无误，开始匹配")}
        </button>
      )}
    </div>
  );
}

function DemoDisclosure({ countryCode }: { countryCode: string | null | undefined }) {
  const { t } = useLanguage();
  const [open, setOpen] = useState(false);
  const panelId = useId();
  return (
    <div className="v2-demo-disclosure">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((current) => !current)}
      >
        {countryCode ? t("演示数据 · {countryCode}", { countryCode }) : t("演示数据")}
      </button>
      {open ? <p id={panelId}>{t("该岗位来自合成演示语料，公司与城市为演示映射。")}</p> : null}
    </div>
  );
}

function ResultCards({
  runId,
  anchorRef,
  highlighted,
  onNewConsult,
}: {
  runId: string;
  anchorRef: React.RefObject<HTMLDivElement | null>;
  highlighted: boolean;
  onNewConsult: () => void;
}) {
  const { t } = useLanguage();
  const [expandedJobId, setExpandedJobId] = useState<string | null>(null);
  const [feedbackJobId, setFeedbackJobId] = useState<string | null>(null);
  const [pendingControl, setPendingControl] = useState<"evidence" | "feedback" | null>(null);
  const result = useQuery({
    queryKey: ["v2-result", runId],
    queryFn: () => api.runResult(runId),
  });
  const capabilities = useQuery({
    queryKey: ["capabilities"],
    queryFn: api.capabilities,
  });
  const firstJobId = result.data?.result.recommended_roles?.[0]?.job_id ?? null;

  useEffect(() => {
    if (!pendingControl || !firstJobId) return;
    if (expandedJobId !== firstJobId) {
      setExpandedJobId(firstJobId);
      return;
    }
    if (pendingControl === "feedback" && feedbackJobId !== firstJobId) {
      setFeedbackJobId(firstJobId);
      return;
    }
    const selector = pendingControl === "evidence" ? ".v2-evidence-trigger" : ".reaction-outcomes button";
    const control = anchorRef.current?.querySelector<HTMLButtonElement>(selector);
    if (!control) return;
    if (pendingControl === "evidence" && control.getAttribute("aria-expanded") !== "true") {
      control.click();
    }
    control.focus();
    setPendingControl(null);
  }, [anchorRef, expandedJobId, feedbackJobId, firstJobId, pendingControl]);

  if (result.isPending)
    return (
      <div
        ref={anchorRef}
        className={`v2-results${highlighted ? " is-highlighted" : ""}`}
        role="region"
        aria-label={t("匹配结果")}
        tabIndex={-1}
      >
        <p className="v2-inline-loading">
          <LoaderCircle className="spin" size={15} /> {t("正在整理结果…")}
        </p>
      </div>
    );
  if (result.isError)
    return (
      <div
        ref={anchorRef}
        className={`v2-results${highlighted ? " is-highlighted" : ""}`}
        role="region"
        aria-label={t("匹配结果")}
        tabIndex={-1}
      >
        <p className="v2-error">{t("结果暂时无法读取，可稍后刷新。")}</p>
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
  const featuredRanks = ["①", "②", "③"];
  const safeSourceUrl = (sourceUrl: string | null | undefined): string | null => {
    if (!sourceUrl) return null;
    try {
      const url = new URL(sourceUrl);
      return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
    } catch {
      return null;
    }
  };
  const toggleDetails = (jobId: string) => {
    setExpandedJobId((current) => (current === jobId ? null : jobId));
    setFeedbackJobId(null);
    setPendingControl(null);
  };
  return (
    <div
      ref={anchorRef}
      className={`v2-results${highlighted ? " is-highlighted" : ""}`}
      role="region"
      aria-label={t("匹配结果")}
      tabIndex={-1}
    >
      <div className="v2-capabilities" aria-label={t("检索能力")}>
        <span>{t("混合检索（BM25+语义双路）")}</span>
        {capabilities.data?.dual_space_enabled === true ? <span>{t("支持双空间增强")}</span> : null}
      </div>
      <div className="v2-result-table-wrap">
        <table className="v2-result-table" aria-label={t("岗位推荐列表")}>
          <thead>
            <tr>
              <th scope="col">#</th>
              <th scope="col">{t("分层")}</th>
              <th scope="col">{t("岗位名")}</th>
              <th scope="col">{t("公司·地点")}</th>
              <th scope="col">{t("语料标签")}</th>
            </tr>
          </thead>
          <tbody>
            {(product.recommended_roles ?? []).map((role: Recommendation, index: number) => {
              const sourceUrl = safeSourceUrl(role.source_url);
              const title = role.title ?? role.job_id;
              const expanded = expandedJobId === role.job_id;
              const feedbackOpen = feedbackJobId === role.job_id;
              const detailId = `v2-job-detail-${index}`;
              const feedbackId = `v2-job-feedback-${index}`;
              return (
                <Fragment key={role.job_id}>
                  <tr
                    className={`v2-result-row${highlighted && index === 0 ? " is-highlighted" : ""}`}
                    onClick={() => toggleDetails(role.job_id)}
                  >
                    <td>
                      <span className="v2-rank" data-featured={index < 3 ? "true" : "false"}>
                        {featuredRanks[index] ?? `${index + 1}.`}
                      </span>
                    </td>
                    <td>
                      <span className={`v2-tier ${role.tier}`}>
                        {tierLabel[role.tier] ? t(tierLabel[role.tier]) : role.tier}
                      </span>
                    </td>
                    <td>
                      <button
                        type="button"
                        className="v2-result-row-trigger"
                        aria-expanded={expanded}
                        aria-controls={detailId}
                        aria-label={t("查看 {title} 详情", { title })}
                        onClick={(event) => {
                          event.stopPropagation();
                          toggleDetails(role.job_id);
                        }}
                      >
                        <h3>{title}</h3>
                      </button>
                    </td>
                    <td>{role.company ?? "—"} · {role.location ?? "—"}</td>
                    <td>
                      <span className="v2-corpus-tag" data-synthetic={role.demo_synthetic ? "true" : "false"}>
                        {role.demo_synthetic ? t("演示语料") : t("真实语料")}
                      </span>
                    </td>
                  </tr>
                  {expanded ? (
                    <tr className="v2-result-detail-row">
                      <td colSpan={5}>
                        <article id={detailId} className="v2-job-card" aria-label={t("{title} 详情", { title })}>
                          <header>
                            {role.demo_synthetic ? <DemoDisclosure countryCode={role.country_code} /> : null}
                            <h3>{title}</h3>
                            <p>{role.company ?? "—"} · {role.location ?? "—"}</p>
                            {sourceUrl ? (
                              <a className="v2-source-link" href={sourceUrl} target="_blank" rel="noopener noreferrer">
                                {t("查看原岗位 ↗")}
                              </a>
                            ) : null}
                          </header>
                          <p className="v2-job-why">{role.concise_explanation}</p>
                          <EvidenceDrawer
                            title={title}
                            evidence={role.evidence ?? []}
                            resumeEvidence={role.resume_evidence ?? []}
                            agentMatchReasons={role.why_this_match ?? []}
                          />
                          <button
                            type="button"
                            className="v2-feedback-trigger"
                            aria-expanded={feedbackOpen}
                            aria-controls={feedbackId}
                            onClick={() => setFeedbackJobId((current) => (current === role.job_id ? null : role.job_id))}
                          >
                            {feedbackOpen ? t("收起进展") : t("提交进展")}
                          </button>
                          {feedbackOpen ? (
                            <div id={feedbackId} className="v2-feedback-panel">
                              <ReactionForm runId={runId} jobId={role.job_id} />
                            </div>
                          ) : null}
                        </article>
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      {resumeStrategy.length ? (
        <details className="v2-extra">
          <summary>{t("简历修改建议（{count} 条）", { count: resumeStrategy.length })}</summary>
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
          <summary>{t("能力缺口（{count} 项）", { count: skillGaps.length })}</summary>
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
          <summary>{t("职业路径")}</summary>
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
        <p className="v2-warnings">{t("提示：{warnings}", { warnings: warnings.join("、") })}</p>
      ) : null}
      <div className="v2-result-actions" role="group" aria-label={t("结果后续行动")}>
        {(product.recommended_roles ?? []).length ? (
          <>
            <button type="button" onClick={() => setPendingControl("evidence")}>
              {t("查看第 1 名的证据")}
            </button>
            <button type="button" onClick={() => setPendingControl("feedback")}>
              {t("更新申请进展")}
            </button>
          </>
        ) : null}
        <button type="button" onClick={onNewConsult}>
          {t("新建咨询细化方向")}
        </button>
      </div>
    </div>
  );
}

export function WorkbenchPage() {
  const { t } = useLanguage();
  const { sessionId = "" } = useParams();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const runId = searchParams.get("run");
  const queryClient = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: api.me, retry: false });
  const capabilities = useQuery({ queryKey: ["capabilities"], queryFn: api.capabilities });
  const imageUploadEnabled = capabilities.data?.resume_image_upload_enabled === true;
  const [message, setMessage] = useState("");
  const [mode, setMode] = useState<"targeted" | "explore">("targeted");
  const [briefDraft, setBriefDraft] = useState<ConsultFinalize | null>(null);
  const [brief, setBrief] = useState<MatchBriefResponse | null>(null);
  const [resumeRecovery, setResumeRecovery] = useState<ResumeRecoveryState | null>(null);
  // B2 上传确认流：composer 选中、尚未确认上传的文件
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  // 单一 modal 状态：retry/refine→quota 的 402 切换保持同一 FocusModal 实例，
  // 避免旧实例卸载时的焦点归还 microtask 把焦点抢回背景（互审第 2 轮阻断）
  const [retryModal, setRetryModal] = useState<"retry" | "refine" | "quota" | null>(null);
  const timelineRef = useRef<HTMLOListElement>(null);
  const resultRef = useRef<HTMLDivElement>(null);
  const messageInputRef = useRef<HTMLTextAreaElement>(null);
  const executeAttempted = useRef(false);
  // B3 双保险：记录发起 parse 时的 generation——进度响应换代=解析中重传，
  // 停叙事并刷新上传态回落确认卡（方案 §3.1）
  const parseGeneration = useRef<number | null>(null);
  // B3 §3.2：只有"本次挂载亲历解析过程"才逐行动画，回访/刷新不重播。
  // 存 sessionId 而非布尔：会话切换首帧 ref 尚未被 effect 重置，布尔会把
  // 上个会话的"亲历"泄漏给新会话的缓存档案（子 agent 审查 minor）
  const watchedProcessingFor = useRef<string | null>(null);
  const progressSettled = useRef(false);
  // done 补拉去重（按会话+代数；parse onSuccess 重置）
  const doneBackfilledFor = useRef<string | null>(null);

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
    refetchInterval: (query) => resumePreviewInterval(query.state.error),
  });
  // B2：待确认解析的上传（刷新/切会话后由此恢复「确认解析」卡；404=无）
  const pendingUpload = useQuery({
    queryKey: ["resume-upload", sessionId],
    queryFn: () => api.pendingResumeUpload(sessionId),
    enabled: Boolean(sessionId),
    retry: false,
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

  const handleResumeLifecycleConflict = (error: unknown) => {
    const recovery = resumeRecoveryState(error);
    if (!recovery) return false;
    setResumeRecovery(recovery);
    setBriefDraft(null);
    void Promise.all([
      queryClient.invalidateQueries({ queryKey: ["resume-preview", sessionId] }),
      queryClient.invalidateQueries({ queryKey: ["consult", sessionId] }),
    ]);
    return true;
  };

  // 在途 mutation 的回调必须校验"发起时的会话"：A 会话请求完成于切到 B 之后
  // 时，不得清 B 的 pendingFile 或刷新 B 的查询（对侧抽查 M6）。
  const upload = useMutation({
    mutationFn: ({ file, forSession }: { file: File; forSession: string }) =>
      api.uploadResume(forSession, file),
    onSuccess: (_data, variables) => {
      if (variables.forSession !== sessionId) return;
      // 上传成功＝进入待确认解析态；清旧恢复提示，刷新待解析卡与 preview
      // （preview 将返回 409 resume_unparsed，由确认卡驱动后续）。
      setPendingFile(null);
      setResumeRecovery(null);
      // 上传即换代（Codex 三轮 Major）：旧代的亲历/补拉/自发标记与 done
      // 缓存全部作废——否则"远端标签页秒解析新代、本页未观察到 queued"
      // 时，旧代的用时庆祝与逐行动画会挂到新代档案上。
      parseGeneration.current = null;
      watchedProcessingFor.current = null;
      doneBackfilledFor.current = null;
      progressSettled.current = false;
      queryClient.removeQueries({
        queryKey: ["resume-progress", variables.forSession],
        exact: true,
      });
      void queryClient.invalidateQueries({ queryKey: ["resume-upload", variables.forSession] });
      void queryClient.invalidateQueries({ queryKey: ["resume-preview", variables.forSession] });
    },
  });
  const newSession = useMutation({
    mutationFn: () => api.createSession({}),
    onSuccess: (session) => {
      void queryClient.invalidateQueries({ queryKey: ["me-sessions"] });
      navigate(`/app/sessions/${session.session_id}`);
    },
  });
  const parseResume = useMutation({
    mutationFn: ({ generation, forSession }: { generation: number; forSession: string }) =>
      // 必须回传预览所得 generation：旧标签页拿旧代确认 → 后端 409 resume_changed
      api.parseResume(forSession, { generation }),
    onSuccess: (_data, variables) => {
      if (variables.forSession !== sessionId) return;
      parseGeneration.current = variables.generation;
      // 新一轮解析开始：补拉去重键随之作废（Codex 二轮 M1）
      doneBackfilledFor.current = null;
      // 上一轮解析的 done=true 缓存必须清场，否则新一轮轮询被闷死
      // （enabled 翻转时无数据才必然重取；Codex B3 审查 C4）
      queryClient.removeQueries({
        queryKey: ["resume-progress", variables.forSession],
        exact: true,
      });
      void queryClient.invalidateQueries({ queryKey: ["resume-upload", variables.forSession] });
      void queryClient.invalidateQueries({ queryKey: ["resume-preview", variables.forSession] });
    },
    onError: (error, variables) => {
      if (variables.forSession !== sessionId) return;
      if (
        error instanceof ApiError &&
        error.status === 409 &&
        // resume_processing = 另一标签页/双击已先确认解析——同样刷新，
        // 让确认卡退场（GET 404）并由 preview 409 进入处理中轮询
        (error.message === "resume_changed" ||
          error.message === "resume_unparsed" ||
          error.message === "resume_processing")
      ) {
        void queryClient.invalidateQueries({ queryKey: ["resume-upload", variables.forSession] });
        void queryClient.invalidateQueries({ queryKey: ["resume-preview", variables.forSession] });
      }
      // resume_ocr_disabled（B4 回滚窗口）：不刷新——上传仍在场，确认卡
      // 原地展示引导文案（见 parseErrorText），用户重传文字版即可
    },
  });
  const confirmResume = useMutation({
    mutationFn: () => {
      const expectedResumeVersion = preview.data?.resume_version;
      if (expectedResumeVersion === undefined) {
        throw new Error("resume preview version missing");
      }
      return api.confirmResume(sessionId, {
        expected_resume_version: expectedResumeVersion,
      });
    },
    onSuccess: () => {
      setResumeRecovery(null);
      void queryClient.invalidateQueries({ queryKey: ["resume-preview", sessionId] });
    },
    onError: handleResumeLifecycleConflict,
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
      setResumeRecovery(null);
      // 继续咨询会改画像：作废已生成的旧确认单，防止确认到过期内容
      setBriefDraft(null);
      void queryClient.invalidateQueries({ queryKey: ["consult", sessionId] });
    },
    onError: (error) => {
      handleResumeLifecycleConflict(error);
    },
  });
  const finalize = useMutation({
    mutationFn: () => api.consultFinalize(sessionId),
    onSuccess: (draft) => setBriefDraft(draft),
    onError: handleResumeLifecycleConflict,
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
      if (me.data?.user_id) {
        writeLastRun(me.data.user_id, sessionId, created.run_id);
        writeSessionTitle(me.data.user_id, sessionId, created.brief.career_goal);
      }
      setBrief(created);
      executeAttempted.current = false;
      setSearchParams({ run: created.run_id }, { replace: true });
    },
    onError: handleResumeLifecycleConflict,
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
      setResumeRecovery(null);
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
    setBriefDraft(null);
    setBrief(null);
    setResumeRecovery(null);
    setRetryModal(null);
    setPendingFile(null);
    executeAttempted.current = false;
    parseGeneration.current = null;
    progressSettled.current = false;
    // mutation 实例级状态必须随会话切换重置：不重置会把 A 会话的
    // 上传成功/限额 409 带进 B 会话（审计三轮阻断修复；B2 扩展到 parse）。
    upload.reset();
    parseResume.reset();
  }, [sessionId, upload.reset, parseResume.reset]);

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
  // 生命周期按后端稳定 detail 分流（审计二轮阻断修复；B2 扩展）：
  // resume_missing=从未上传；resume_unparsed=已上传待确认解析（确认卡由
  // pendingUpload 数据驱动）；resume_processing=归一化中；resume_error=失败。
  const preview409 = preview.error instanceof ApiError && preview.error.status === 409;
  const previewDetail =
    preview.error instanceof ApiError && preview.error.status === 409
      ? preview.error.message
      : null;
  const uploadPending = pendingUpload.isSuccess;
  // 刷新后限额态直接由 GET 数据推导（不等一次必败请求）；409 作即时信号
  const parseLimitReached =
    (pendingUpload.data !== undefined &&
      pendingUpload.data.parses_used >= pendingUpload.data.parses_limit) ||
    (parseResume.error instanceof ApiError &&
      parseResume.error.status === 409 &&
      parseResume.error.message === "resume_parse_limit");
  const pendingUploadLoadError =
    pendingUpload.isError &&
    !(pendingUpload.error instanceof ApiError && pendingUpload.error.status === 404);
  // Codex B3 审查 C7：isPending 必须绑定发起会话——A 会话 parse 在途时切到
  // B，不得把 B 标成"处理中/亲历解析"（variables 在 mutate 同步可得）
  const parsePendingForSession =
    parseResume.isPending && parseResume.variables?.forSession === sessionId;
  const resumeProcessing =
    parsePendingForSession || previewDetail === "resume_processing";
  const resumeError =
    !resumeProcessing && (previewDetail === "resume_error" || resumeRecovery === "error");
  const previewLoadError = preview.isError && !preview409;
  const resumeConfirmed = resumeReady && Boolean(preview.data?.confirmed);

  // B3 R2：解析中每 1200ms 轮询进度事件，小意叙事逐条进群；done 停轮询
  const resumeProgress = useQuery({
    queryKey: ["resume-progress", sessionId],
    queryFn: () => api.resumeProgress(sessionId),
    enabled: Boolean(sessionId) && resumeProcessing,
    retry: false,
    // 全局 staleTime 10s 会让上一代 done=true 的缓存在新解析启用时被当作
    // 新鲜数据——interval 直接 false、轮询永不启动（Codex B3 审查 C4）。
    // 轮询查询必须永远视缓存为过期。
    staleTime: 0,
    refetchInterval: (query) => resumeProgressInterval(query.state.data),
  });
  const progressEvents = resumeProcessing
    ? (resumeProgress.data?.events ?? []).filter((event) => event.seq < 100)
    : [];
  const progressStagger = useStaggeredReveal(
    progressEvents.map((event) => `ev-${event.seq}`),
    `${sessionId}:intake-${resumeProgress.data?.generation ?? ""}`,
    // 自发流判定绑定到具体代数（Codex 二轮 M2 溯源修正）：本页点击确认
    // 解析的那一代（variables 随 mutate 同步落地且跨 success 保留）才是
    // 自发流，首批事件也逐条出现；刷新恢复或远端标签页启动的新代＝历史/
    // 旁观，整批即时到场不重播（Codex B3 审查 C8）
    parseResume.variables?.forSession === sessionId &&
      parseResume.variables?.generation === resumeProgress.data?.generation,
  );
  // 终态 done 事件（seq=100，含"用时 X.X 秒"）：解析完成后并入档案摘要气泡
  const doneEvent = (resumeProgress.data?.events ?? []).find(
    (event) => event.step === "done",
  );

  // 亲历标记绑定 (session, generation)（Codex 二轮 M2）：跨标签页场景下，
  // 我看着 gen1 解析、远端 gen2 完成时，gen2 的耗时/逐行动画不得挂到本页
  // ——比对键里带代数，串代即失配。
  useEffect(() => {
    if (resumeProcessing) {
      // 焦点竞态收紧（子 agent 三轮 minor）：切回标签页时 progress
      // （staleTime 0）常先于 preview 解决——data 可能已是别代终态而
      // resumeProcessing 还 stale-true，此帧不得盖写亲历标记（只有仍在
      // 进行中的解析才算"亲历中"；data 缺席时保留 parseGeneration 回退）。
      if (resumeProgress.data?.done) return;
      const generation =
        resumeProgress.data?.generation ?? parseGeneration.current;
      if (generation != null) {
        watchedProcessingFor.current = `${sessionId}#${generation}`;
      }
      progressSettled.current = false;
    }
  }, [
    resumeProcessing,
    resumeProgress.data?.done,
    resumeProgress.data?.generation,
    sessionId,
  ]);
  const watchedProcessing =
    resumeProgress.data?.generation != null &&
    watchedProcessingFor.current ===
      `${sessionId}#${resumeProgress.data.generation}`;

  useEffect(() => {
    const data = resumeProgress.data;
    if (!data) return;
    // 双保险（换代语义，方案 §3.1 勘误码定）：响应代数 ≠ 发起 parse 时的
    // 代数 → 停掉旧代归属并刷新上传态。新代为 uploaded → done=true 停轮询
    // 回落确认卡；新代已 queued（远端标签页确认解析）→ 共享会话跟随新代
    // 叙事（气泡 key/stagger/亲历归属全部按代绑定，无串代）。
    if (
      parseGeneration.current != null &&
      data.generation != null &&
      data.generation !== parseGeneration.current
    ) {
      parseGeneration.current = null;
      void queryClient.invalidateQueries({ queryKey: ["resume-upload", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["resume-preview", sessionId] });
      return;
    }
    // done=离开 resume_queued：立刻刷新 preview/upload，让叙事无缝切换到
    // 档案摘要（不等 preview 自身 2.5s 轮询）；ref 防重复 invalidate 循环
    if (data.done && !progressSettled.current) {
      progressSettled.current = true;
      void queryClient.invalidateQueries({ queryKey: ["resume-preview", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["resume-upload", sessionId] });
    }
  }, [queryClient, resumeProgress.data, sessionId]);

  // Codex B3 审查 C4 反向竞态：preview 自己的轮询先读到 ready → processing
  // 翻 false → 进度查询停用，seq=100 终态（"用时 X.X 秒"）可能还没拉到。
  // 亲历解析且缺 done 事件时一次性补拉（refetch 对 disabled 查询照常执行；
  // ref 按会话+代数防重复，不构成循环）。
  const refetchResumeProgress = resumeProgress.refetch;
  useEffect(() => {
    // 门控：watchedProcessing（数据在场的亲历比对）∨ parseGeneration
    // （本页自发 parse 的标记——progress 缓存被 onSuccess 清空时数据缺席，
    // 仅靠前者会漏掉抢跑补拉）；两者都空 = 旁观/回访，不补拉。
    const selfParsed = parseGeneration.current != null;
    if (!resumeReady || (!watchedProcessing && !selfParsed) || doneEvent) return;
    // 去重键优先取本次 parse 的代数（Codex 二轮 M1：progress 缓存被
    // onSuccess 清空时 data.generation 为空，键若退化为 "sess#" 且不随
    // 新 parse 重置，同会话第二代 preview 抢跑会漏补拉）；onSuccess 同时
    // 重置本 ref，双保险。
    const backfillKey = `${sessionId}#${
      parseGeneration.current ?? resumeProgress.data?.generation ?? ""
    }`;
    if (doneBackfilledFor.current === backfillKey) return;
    doneBackfilledFor.current = backfillKey;
    // 必须先显式 cancel 再 refetch：v5 的 cancelRefetch 仅在缓存有数据时
    // 才取消在途请求——缓存为空 + 请求悬停（慢网/被清缓存后重启的轮询）
    // 时 refetch 会直接搭车在途请求，可能拿到终态提交前的旧快照、丢失
    // seq=100（Codex 二轮 M1 修复过程中实测发现）。
    void queryClient
      .cancelQueries({ queryKey: ["resume-progress", sessionId], exact: true })
      .then(() => refetchResumeProgress());
  }, [
    queryClient,
    doneEvent,
    refetchResumeProgress,
    resumeProgress.data?.generation,
    resumeReady,
    sessionId,
    watchedProcessing,
  ]);

  useEffect(() => {
    if (!resumeRecovery || preview.isFetching) return;
    if (resumeRecovery === "error") return;
    if (preview.isSuccess) {
      setResumeRecovery("updated");
      return;
    }
    const recovery = resumeRecoveryState(preview.error);
    if (recovery) setResumeRecovery(recovery);
  }, [preview.error, preview.isFetching, preview.isSuccess, resumeRecovery]);

  // plan_ready 自动提交执行（幂等：409 视为已在执行）
  useEffect(() => {
    const data = status.data;
    if (!data || !runId) return;
    if (data.status === "plan_ready" && data.plan_hash && !executeAttempted.current) {
      executeAttempted.current = true;
      execute.mutate({ runId, plan_version: data.plan_version, plan_hash: data.plan_hash });
    }
  }, [status.data, runId, execute.mutate]);

  const transcript = consult.data?.transcript ?? [];
  const runMessages = (conversation.data?.messages ?? []).filter((item) => item.kind !== "intro");
  // B1 R5：仅对本次轮询新增的运行消息做到场编排（i*450ms），历史不重播；
  // 切会话/换 run 时以首帧为基线重置。
  const staggerStyle = useStaggeredReveal(
    runMessages.map((item) => `run-${item.seq}`),
    `${sessionId}:${runId ?? ""}`,
  );
  const running = Boolean(runId) && !TERMINAL.has(status.data?.status ?? "");
  const completed =
    status.data?.status === "completed" || status.data?.status === "completed_with_warnings";
  const hasStrategistResult = runMessages.some(
    (item) => item.persona === "strategist" && item.kind === "result",
  );
  const retryableTerminal = ["failed", "stale", "cancelled"].includes(status.data?.status ?? "");

  const consultBubbles = useMemo(
    () =>
      transcript.flatMap((entry: ConsultTranscriptEntry) => {
        const items: {
          key: string;
          persona: keyof typeof PERSONAS;
          text: string;
          round: number;
          finalizableNote: boolean;
        }[] = [
          {
            key: `u-${entry.round}`,
            persona: "user",
            text: entry.user_message,
            round: entry.round,
            finalizableNote: false,
          },
          {
            key: `a-${entry.round}`,
            persona: "intent_consultant",
            text: `${entry.assistant_reply}${entry.next_question ? `\n${entry.next_question}` : ""}`,
            round: entry.round,
            finalizableNote: false,
          },
        ];
        for (const note of entry.supervisor_notes ?? []) {
          items.push({
            key: `n-${entry.round}-${note.coach_attempt_id}`,
            persona: "pm",
            text: note.text,
            round: entry.round,
            finalizableNote: note.trigger === "finalizable",
          });
        }
        return items;
      }),
    [transcript],
  );
  const finalizableNoteKey = [...consultBubbles]
    .reverse()
    .find((item) => item.finalizableNote)?.key;

  const timelineContentKey = [
    resumeReady,
    resumeProcessing,
    // B3：叙事事件逐条进群也要推动时间线跟随滚动
    progressEvents.map((event) => event.seq).join(","),
    consultBubbles.length,
    consultBubbles
      .map((item) => [item.key, item.persona, item.text].join("~"))
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

  const canConsult =
    resumeConfirmed &&
    consult.isSuccess &&
    !runId &&
    resumeRecovery !== "processing" &&
    resumeRecovery !== "error";
  const inputDisabled = !canConsult || turn.isPending;
  const consultSlots = deriveConsultSlots(
    consult.data?.profile_draft,
    consult.data?.clarification_progress,
  );
  const completenessPercent = Math.round(
    Math.min(1, Math.max(0, consult.data?.completeness ?? 0)) * 100,
  );

  if (!sessionId) return null;

  return (
    <section className="v2-workbench">
      <header className="v2-room-header">
        <div>
          <h1>{t("职业规划服务群")}</h1>
          <p>
            {Object.values(PERSONAS)
              .filter((meta) => meta.role)
              .map((meta) => t(meta.name))
              .join(" · ")}
          </p>
        </div>
        {running ? (
          <span className="v2-room-status">
            <LoaderCircle className="spin" size={14} /> {t("服务进行中")}
          </span>
        ) : null}
      </header>

      <ol className="v2-timeline" ref={timelineRef} onScroll={timelineScroll.onScroll} aria-live="polite">
        <Bubble persona="pm">
          <p>
            {resumeConfirmed
              ? t(
                  "欢迎来到职业规划服务群。我是项目经理 PM，小意负责需求、小检负责岗位、小策负责规划，我会在每个环节前后做质量把关。你的简历档案已确认，接下来和小意聊清求职方向就能开始匹配。",
                )
              : t(
                  "欢迎来到职业规划服务群。我是项目经理 PM，小意负责需求、小检负责岗位、小策负责规划，我会在每个环节前后做质量把关。先点下方输入框左侧的 📎 把简历发进群（{formats}）。",
                  { formats: t(supportedFormatsLabel(imageUploadEnabled)) },
                )}
          </p>
        </Bubble>

        {!resumeReady && !resumeProcessing && !resumeError && !previewLoadError &&
        !uploadPending && !pendingFile && !pendingUploadLoadError ? (
          // B1 R5：PM 先到场，小意 600ms 后跟进（reduced-motion 下即时）
          <Bubble persona="intent_consultant" tone="card" style={{ animationDelay: "600ms" }}>
            <p>
              {t(
                "把简历发到群里，我先帮你整理成标准档案（每条都会标注原文出处）——用下方输入框左侧的 📎 就能发{formats}。上传是免费预览，确认解析后才开始整理。",
                {
                  formats: imageUploadEnabled
                    ? t("（{formats}）", { formats: t(supportedFormatsLabel(imageUploadEnabled)) })
                    : "",
                },
              )}
            </p>
          </Bubble>
        ) : null}

        {pendingFile ? (
          <Bubble persona="user" tone="card">
            <p>
              {t("{filename}（{size} KB）", {
                filename: pendingFile.name,
                size: Math.max(1, Math.round(pendingFile.size / 1024)),
              })}
              {uploadPending ? t("——确认后将替换当前待解析的上传") : null}
            </p>
            <div className="v2-pending-actions">
              <button
                type="button"
                className="v2-btn primary"
                disabled={upload.isPending}
                onClick={() => upload.mutate({ file: pendingFile, forSession: sessionId })}
              >
                {upload.isPending ? t("上传中…") : t("确认上传")}
              </button>
              <button
                type="button"
                className="v2-btn ghost"
                disabled={upload.isPending}
                onClick={() => {
                  setPendingFile(null);
                  upload.reset();
                }}
              >
                {t("取消")}
              </button>
            </div>
            {upload.isError ? (
              <p className="v2-error">
                {upload.error instanceof ApiError && upload.error.status === 415
                  ? t("暂不支持该文件格式（当前支持 {formats}）。", {
                      formats: t(supportedFormatsLabel(imageUploadEnabled)),
                    })
                  : t(uploadErrorText(upload.error, imageUploadEnabled))}
              </p>
            ) : null}
          </Bubble>
        ) : null}

        {uploadPending && !resumeProcessing && !pendingFile ? (
          <Bubble persona="intent_consultant" tone="card">
            <p>
              {t("收到「{filename}」：共 {pages} 页、约 {chars} 字。", {
                filename: pendingUpload.data?.filename ?? "",
                pages: pendingUpload.data?.pages ?? 0,
                chars: pendingUpload.data?.chars ?? 0,
              })}
              {pendingUpload.data?.ocr_suggested
                ? imageUploadEnabled
                  ? t("检测到扫描件/图片，确认解析后小意会用视觉识别读取（约几分钱）。")
                  : t("文字较少，可能是扫描件/图片——图片识别即将开放，建议先换文字版试试。")
                : null}
            </p>
            {pendingUpload.data?.text_preview ? (
              <blockquote className="v2-upload-preview">
                {pendingUpload.data.text_preview}
              </blockquote>
            ) : null}
            <p className="v2-parse-quota">
              {t("解析会调用 AI 整理档案（本会话已用 {used}/{limit} 次）。", {
                used: pendingUpload.data?.parses_used ?? 0,
                limit: pendingUpload.data?.parses_limit ?? 3,
              })}
            </p>
            <button
              type="button"
              className="v2-btn primary"
              disabled={
                parseResume.isPending ||
                parseLimitReached ||
                pendingUpload.data === undefined
              }
              onClick={() => {
                const generation = pendingUpload.data?.generation;
                if (generation === undefined) return;
                parseResume.mutate({ generation, forSession: sessionId });
              }}
            >
              {parseResume.isPending ? t("已提交…") : t("确认解析")}
            </button>
            {parseLimitReached ? (
              <>
                <p className="v2-error">
                  {t("本会话解析次数已用完（{limit}/{limit}）。会话额度也用完时请联系管理员重置。", {
                    limit: pendingUpload.data?.parses_limit ?? 3,
                  })}
                </p>
                <button
                  type="button"
                  className="v2-btn ghost"
                  disabled={newSession.isPending}
                  onClick={() => newSession.mutate()}
                >
                  {newSession.isPending ? t("创建中…") : t("新建会话继续")}
                </button>
                {newSession.isError ? (
                  <p className="v2-error">
                    {newSession.error instanceof ApiError && newSession.error.status === 402
                      ? t("会话额度已用完，请联系管理员。")
                      : t("新建会话失败，请重试。")}
                  </p>
                ) : null}
              </>
            ) : parseResume.isError ? (
              <p className="v2-error">
                {parseResume.error instanceof ApiError &&
                parseResume.error.status === 409 &&
                parseResume.error.message === "resume_ocr_disabled"
                  ? t("图片识别功能暂时关闭，这份图片暂无法解析——请重新上传文字版简历（PDF/DOCX/TXT）。")
                  : t("确认解析失败，请重试。")}
              </p>
            ) : null}
          </Bubble>
        ) : null}

        {pendingUploadLoadError && !pendingFile ? (
          <Bubble persona="intent_consultant" tone="card">
            <p className="v2-error">{t("待解析上传状态加载失败，请重试")}</p>
            <button
              type="button"
              className="v2-btn ghost"
              disabled={pendingUpload.isFetching}
              onClick={() => void pendingUpload.refetch()}
            >
              {pendingUpload.isFetching ? t("重试中…") : t("重试加载")}
            </button>
          </Bubble>
        ) : null}

        {previewLoadError ? (
          <Bubble persona="intent_consultant" tone="card">
            <p className="v2-error">{t("简历档案加载失败，请重试")}</p>
            <button
              type="button"
              className="v2-btn ghost"
              disabled={preview.isFetching}
              onClick={() => void preview.refetch()}
            >
              {preview.isFetching ? t("重试中…") : t("重试加载简历档案")}
            </button>
          </Bubble>
        ) : null}

        {resumeError && !pendingFile && !uploadPending ? (
          <Bubble persona="intent_consultant" tone="card">
            <p className="v2-error">{t("这份文件我没能整理成功，旧档案已作废。")}</p>
            <p>{t("请点下方输入框左侧的 📎 重新发一份给我（换个格式或文字版更稳）。")}</p>
          </Bubble>
        ) : null}

        {resumeProcessing ? (
          <Fragment>
            {/* B3 R2：小意边解析边说话——进度事件逐条进群（新事件才有到场延迟） */}
            {progressEvents.map((event) => (
              <Bubble
                // key 含会话+代数（§3.1 绑定口径）：换代或切会话后同 seq
                // 不复用旧 DOM 节点（入场动画正常重播）
                key={`intake-${sessionId}-${resumeProgress.data?.generation ?? 0}-${event.seq}`}
                persona="intent_consultant"
                style={progressStagger(`ev-${event.seq}`)}
              >
                <p>{t(event.text)}</p>
              </Bubble>
            ))}
            <Bubble persona="intent_consultant">
              <p className="v2-inline-loading">
                <LoaderCircle className="spin" size={15} />{" "}
                {progressEvents.length
                  ? t("小意整理中，马上就好…")
                  : t("正在归一化你的简历（解析 → 切证据片段 → 结构化 → 防编造校验）…")}
              </p>
            </Bubble>
          </Fragment>
        ) : null}

        {resumeReady && !resumeConfirmed ? (
          <Bubble persona="intent_consultant" tone="card">
            {/* B3：终态事件带耗时（"用时 X.X 秒"）——亲历解析的这次挂载才展示 */}
            {watchedProcessing && doneEvent ? (
              <p className="v2-intake-done">{t(doneEvent.text)}</p>
            ) : null}
            <div className="v2-profile-summary">
              {translatedProfileSummaryLines(preview.data, t).map((line, index) => (
                <p
                  key={`${index}-${line}`}
                  className={watchedProcessing ? "v2-profile-line" : undefined}
                  style={
                    watchedProcessing
                      ? { animationDelay: `${index * 350}ms` }
                      : undefined
                  }
                >
                  {line}
                </p>
              ))}
            </div>
            <ResumeProfileAccordion preview={preview.data} />
            <p>{t("确认无误后，我们就开始聊方向！")}</p>
            <button
              type="button"
              className="v2-btn primary"
              disabled={confirmResume.isPending}
              onClick={() => confirmResume.mutate()}
            >
              {confirmResume.isPending ? t("确认中…") : t("确认简历档案")}
            </button>
          </Bubble>
        ) : null}

        {resumeConfirmed && !runId ? (
          <Bubble persona="intent_consultant" tone="card">
            <p>
              {t("✅ 简历档案已确认（v{version}），随时可以点右下档案重新查看。", {
                version: preview.data.resume_version,
              })}
            </p>
            <ResumeProfileAccordion preview={preview.data} />
            {consult.isSuccess &&
            (consult.data.round === 0 || transcript.length === 0) ? (
              <p>
                {t(
                  mode === "explore"
                    ? "还不确定方向？没关系，切到这里我们先聊聊你的兴趣和优势，一起找方向。"
                    : '现在告诉我你的求职方向吧——目标岗位、期望地点、签证情况，一句话说清也行；不确定的话切到"探索方向"，我们一起梳理。',
                )}
              </p>
            ) : null}
          </Bubble>
        ) : null}

        {resumeConfirmed && consult.isError ? (
          <Bubble persona="intent_consultant" tone="card">
            <p className="v2-error">{t("咨询状态加载失败，请重试")}</p>
            <button
              type="button"
              className="v2-btn ghost"
              disabled={consult.isFetching}
              onClick={() => void consult.refetch()}
            >
              {consult.isFetching ? t("重试中…") : t("重试加载咨询状态")}
            </button>
          </Bubble>
        ) : null}

        {consultBubbles.map((item) => (
          <Bubble
            key={item.key}
            persona={item.persona}
            metadata={{ kind: "round", text: t("第 {round} 轮", { round: item.round }) }}
          >
            <p style={{ whiteSpace: "pre-line" }}>{item.text}</p>
            {item.key === finalizableNoteKey && canConsult && consult.data?.can_finalize && !briefDraft ? (
              <FinalizeAction
                disabled={finalize.isPending || turn.isPending}
                pending={finalize.isPending}
                onFinalize={() => finalize.mutate()}
              />
            ) : null}
          </Bubble>
        ))}

        {turn.isPending ? (
          <Bubble persona="intent_consultant">
            <p className="v2-inline-loading">
              <LoaderCircle className="spin" size={15} /> {t("小意正在回复…")}
            </p>
          </Bubble>
        ) : null}

        {canConsult && consult.data?.can_finalize && !briefDraft && !finalizableNoteKey ? (
          <Bubble persona="pm" tone="card">
            <p>{finalizationMilestoneText(consult.data.profile_draft, t)}</p>
            <FinalizeAction
              disabled={finalize.isPending || turn.isPending}
              pending={finalize.isPending}
              onFinalize={() => finalize.mutate()}
            />
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
              <p className="v2-error">{t("创建失败，请重试或继续补充信息。")}</p>
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
          const stageLabel = t(runMessageStageLabel(item.stage));
          return (
            <Fragment key={`run-${item.seq}`}>
              {startsStage ? (
                <li className="v2-stage-divider" role="separator" aria-label={t("运行阶段：{stage}", { stage: stageLabel })}>
                  <span>{stageLabel}</span>
                </li>
              ) : null}
              <Bubble
                persona={item.persona}
                grouped={grouped}
                metadata={{ kind: "stage", text: t("阶段 · {stage}", { stage: stageLabel }) }}
                style={staggerStyle(`run-${item.seq}`)}
              >
                <p style={{ whiteSpace: "pre-line" }}>{t(item.text)}</p>
              </Bubble>
              {completed && runId && item.persona === "strategist" && item.kind === "result" ? (
                <Bubble persona="strategist" tone="card">
                  <ResultCards
                    runId={runId}
                    anchorRef={resultRef}
                    highlighted={timelineScroll.resultHighlighted}
                    onNewConsult={() => setRetryModal("refine")}
                  />
                </Bubble>
              ) : null}
            </Fragment>
          );
        })}

        {completed && runId && !hasStrategistResult ? (
          <Bubble persona="strategist" tone="card">
            <ResultCards
              runId={runId}
              anchorRef={resultRef}
              highlighted={timelineScroll.resultHighlighted}
              onNewConsult={() => setRetryModal("refine")}
            />
          </Bubble>
        ) : null}

        {retryableTerminal ? (
          <Bubble persona="pm">
            <p className="v2-error">
              {t("{outcome}{errorCode}。当前会话不能重新生成确认单，需要新建咨询后重试。", {
                outcome: status.data?.status === "cancelled" ? t("本次运行已取消") : t("本次运行没有完成"),
                errorCode: status.data?.error_code
                  ? t("（{errorCode}）", { errorCode: status.data.error_code })
                  : "",
              })}
            </p>
            <button type="button" className="v2-btn primary" onClick={() => setRetryModal("retry")}>
              {t("新建咨询重试")}
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
          {timelineScroll.notice === "result" ? t("结果已生成 ↓") : t("↓ 有新消息")}
        </button>
      ) : null}

      <footer className="v2-composer">
        <div className="v2-mode-toggle v2-composer-mode" role="tablist" aria-label={t("咨询模式")}>
          <button
            role="tab"
            aria-label={t("目标明确")}
            aria-describedby="v2-targeted-mode-description"
            aria-selected={mode === "targeted"}
            onClick={() => setMode("targeted")}
          >
            <span>{t("目标明确")}</span>
            <small id="v2-targeted-mode-description">{t("已有意向岗位，直接补条件")}</small>
          </button>
          <button
            role="tab"
            aria-label={t("探索方向")}
            aria-describedby="v2-explore-mode-description"
            aria-selected={mode === "explore"}
            onClick={() => setMode("explore")}
          >
            <span>{t("探索方向")}</span>
            <small id="v2-explore-mode-description">{t("不确定方向，小意帮你梳理")}</small>
          </button>
        </div>
        <div className="v2-composer-row">
          <label
            className="v2-btn ghost v2-attach"
            aria-label={t("上传简历")}
            title={
              imageUploadEnabled
                ? t("支持 {formats}（PNG/JPG/WEBP）", {
                    formats: t(supportedFormatsLabel(imageUploadEnabled)),
                  })
                : t("支持 PDF/DOCX/TXT；图片识别即将开放")
            }
          >
            <Paperclip size={17} />
            <input
              type="file"
              accept={
                imageUploadEnabled
                  ? ".pdf,.docx,.txt,.png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp"
                  : ".pdf,.docx,.txt"
              }
              hidden
              disabled={Boolean(runId) || upload.isPending}
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) {
                  setPendingFile(file);
                  upload.reset();
                  parseResume.reset();
                }
                event.target.value = "";
              }}
            />
          </label>
          <textarea
            ref={messageInputRef}
            value={message}
            placeholder={
              canConsult
                ? t("告诉小意你的想法…（回车发送，Shift+回车换行）")
                : runId
                  ? t("任务执行中，可在上方查看团队进展")
                  : t("先用左侧 📎 上传简历，确认档案后开聊")
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
            aria-label={t("发送")}
          >
            <Send size={17} />
          </button>
        </div>
        {canConsult ? (
          <section className="v2-consult-slots" aria-label={t("咨询必填信息")}>
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
                    if (message === "") setMessage(t(slot.prompt));
                  }}
                >
                  <span aria-hidden="true">{slot.complete ? "✓" : "○"}</span>
                  {translatedConsultSlotLabel(slot, t)}
                </button>
              ))}
            </div>
            <progress
              className="v2-completeness"
              aria-label={t("咨询信息完成度")}
              aria-valuenow={completenessPercent}
              value={completenessPercent}
              max={100}
            />
          </section>
        ) : null}
        {resumeRecovery ? (
          <p
            className={`${resumeRecovery === "error" ? "v2-error" : "v2-notice"} v2-composer-error`}
            role="status"
          >
            {t(resumeRecoveryMessage(resumeRecovery))}
          </p>
        ) : turn.isError ? (
          <p className="v2-error v2-composer-error">
            {turn.error instanceof ApiError && turn.error.status === 409
              ? t("对话状态已更新，请刷新后继续。")
              : t("发送失败，请重试。")}
          </p>
        ) : null}
      </footer>
      {retryModal ? (
        <FocusModal
          label={retryModal === "quota" ? t("额度已用完") : t("新建咨询确认")}
          modeKey={retryModal}
          closeDisabled={retryModal !== "quota" && createSession.isPending}
          onClose={() => setRetryModal(null)}
        >
          {retryModal !== "quota" ? (
            <>
              <h2>{retryModal === "refine" ? t("新建咨询细化方向") : t("新建咨询后重试")}</h2>
              <p>
                {retryModal === "refine"
                  ? t("新建咨询会消耗一次咨询额度。创建成功后可继续细化方向。")
                  : t("新建咨询会消耗一次咨询额度。创建成功后才会离开当前终态页面。")}
              </p>
              <div className="v2-modal-actions">
                <button
                  type="button"
                  className="v2-btn primary"
                  disabled={createSession.isPending}
                  onClick={() => createSession.mutate()}
                >
                  {createSession.isPending ? t("创建中…") : t("确认新建咨询")}
                </button>
                <button
                  type="button"
                  className="v2-btn ghost"
                  disabled={createSession.isPending}
                  onClick={() => setRetryModal(null)}
                >
                  {t("保留当前页面")}
                </button>
              </div>
              {createSession.isError && !(createSession.error instanceof ApiError && createSession.error.status === 402) ? (
                <p className="v2-error">{t("新咨询暂时无法创建，请重试。")}</p>
              ) : null}
            </>
          ) : (
            <>
              <h2>{t("咨询额度已用完")}</h2>
              <p>{t("当前账户的咨询额度已用完。原终态页面已保留。")}</p>
              <button type="button" className="v2-btn ghost" onClick={() => setRetryModal(null)}>
                {t("返回当前页面")}
              </button>
            </>
          )}
        </FocusModal>
      ) : null}
    </section>
  );
}
