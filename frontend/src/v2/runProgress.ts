import type { RunStatus } from "../api/queries";

export const RUN_STAGE_ORDER = [
  "resume",
  "intent",
  "retrieval",
  "strategy",
  "verification",
  "finalization",
  "result",
] as const;

type RunStage = (typeof RUN_STAGE_ORDER)[number];
type SegmentState = "complete" | "current" | "pending" | "interrupted";
type ActiveActor = "system" | "pm" | "job_scout" | "strategist";

const COMPLETED_STATUSES = new Set(["completed", "completed_with_warnings"]);
const INTERRUPTED_STATUSES = new Set(["failed", "stale", "cancelled"]);

const STAGE_DETAIL: Record<RunStage, string> = {
  resume: "资料已就绪·系统处理",
  intent: "PM 正在复核小意已确认的需求",
  retrieval: "小检正在筛选岗位",
  strategy: "小策正在整理规划建议",
  verification: "PM 正在核查匹配结果",
  finalization: "系统正在整理发布材料",
  result: "PM 正在发布结果",
};

const STAGE_ACTOR: Record<RunStage, ActiveActor> = {
  resume: "system",
  intent: "pm",
  retrieval: "job_scout",
  strategy: "strategist",
  verification: "pm",
  finalization: "system",
  result: "pm",
};

const SEGMENTS = [
  { id: "intent", label: "小意 · 需求确认", stages: ["resume", "intent"] },
  { id: "retrieval", label: "小检 · 岗位筛选", stages: ["retrieval"] },
  { id: "strategy", label: "小策 · 规划建议", stages: ["strategy"] },
  {
    id: "verification",
    label: "PM · 核查发布",
    stages: ["verification", "finalization", "result"],
  },
] as const satisfies readonly {
  id: string;
  label: string;
  stages: readonly RunStage[];
}[];

export type ServiceProgressItem = {
  id: (typeof SEGMENTS)[number]["id"];
  label: string;
  state: SegmentState;
  detail: string;
  recovery: boolean;
  actor: ActiveActor | null;
  pulsing: boolean;
};

export type ServiceProgressView = {
  summary: string;
  items: ServiceProgressItem[];
};

function isRunStage(value: string | null | undefined): value is RunStage {
  return RUN_STAGE_ORDER.some((stage) => stage === value);
}

function runSummary(status: string | undefined, stage: string | null | undefined): string {
  if (status && COMPLETED_STATUSES.has(status)) return "已发布";
  if (status && INTERRUPTED_STATUSES.has(status)) {
    return stage == null || stage === "plan" ? "执行前中断" : "执行中断";
  }
  if (status === "draft" || status === "plan_ready") return "确认单已锁定，准备执行";
  if (status === "queued") return "已进入执行队列";
  if (status === "running" && stage == null) return "正在启动";
  if (status === "running" && isRunStage(stage)) return STAGE_DETAIL[stage];
  return "处理中";
}

export function deriveServiceProgress(
  data: Pick<RunStatus, "status" | "stage" | "completed_stages"> | undefined,
  hasRecovery: boolean,
): ServiceProgressView {
  const status = data?.status;
  const stage = data?.stage;
  const completedStages = new Set(data?.completed_stages ?? []);
  const completed = Boolean(status && COMPLETED_STATUSES.has(status));
  const interrupted = Boolean(status && INTERRUPTED_STATUSES.has(status));

  return {
    summary: runSummary(status, stage),
    items: SEGMENTS.map((segment) => {
      let state: SegmentState = "pending";
      if (completed || segment.stages.every((item) => completedStages.has(item))) {
        state = "complete";
      }
      if (isRunStage(stage) && segment.stages.some((item) => item === stage)) {
        if (interrupted) state = "interrupted";
        else if (!completed) state = "current";
      }

      const detail =
        state === "complete"
          ? "已完成"
          : state === "interrupted"
            ? "执行在此中断"
            : state === "current" && isRunStage(stage)
              ? STAGE_DETAIL[stage]
              : "等待交接";
      const actor = (state === "current" || state === "interrupted") && isRunStage(stage)
        ? STAGE_ACTOR[stage]
        : null;

      return {
        id: segment.id,
        label: segment.label,
        state,
        detail,
        recovery: segment.id === "verification" && hasRecovery,
        actor,
        pulsing: state === "current" && actor !== "system",
      };
    }),
  };
}
