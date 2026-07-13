import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, CheckCircle2, LoaderCircle, RefreshCw } from "lucide-react";
import { useEffect, useRef } from "react";
import { Link, useParams } from "react-router-dom";

import { ApiError } from "../../api/client";
import { api, type RunStatus } from "../../api/queries";
import { useFlowProgress } from "../../app/App";
import { FLOW_STAGES, type FlowStage } from "../../app/ProgressBoard";

const TERMINAL_STATUSES = new Set(["completed", "completed_with_warnings", "failed", "stale"]);

export function runStatusRefetchInterval(status: Pick<RunStatus, "status" | "retry_after_ms"> | undefined): number | false {
  if (!status || TERMINAL_STATUSES.has(status.status) || status.retry_after_ms == null) return false;
  return status.retry_after_ms;
}

function toFlowStage(stage: string | null | undefined): FlowStage {
  return FLOW_STAGES.some((item) => item.key === stage) ? stage as FlowStage : "retrieval";
}

const stageCopy: Record<string, { title: string; description: string }> = {
  plan_ready: { title: "匹配计划已批准", description: "正在提交执行；同一运行只会启动一次。" },
  intent: { title: "读取已确认的职业目标", description: "Supervisor 正在核对目标与硬约束快照。" },
  retrieval: { title: "正在检索和融合岗位证据", description: "Metadata、BM25 与 Dense 并行检索，隐式案例只重排已有候选。" },
  strategy: { title: "正在生成简历与职业策略", description: "建议只能引用已确认的简历事实和岗位证据。" },
  verification: { title: "Supervisor 正在最终核查", description: "检查硬约束、证据完整性和不当结论。" },
  finalization: { title: "正在整理统一结果", description: "把推荐、技能缺口和解释投影为公开结果。" },
};

export function RunPage() {
  const { runId = "" } = useParams();
  const { setProgress } = useFlowProgress();
  const executeAttempted = useRef(false);
  const status = useQuery({
    queryKey: ["run-status", runId],
    queryFn: () => api.runStatus(runId),
    enabled: Boolean(runId),
    refetchInterval: (query) => runStatusRefetchInterval(query.state.data),
  });
  const execute = useMutation({
    mutationFn: ({ plan_version, plan_hash }: { plan_version: number; plan_hash: string }) => api.executeRun(runId, { plan_version, plan_hash }),
    onSuccess: () => void status.refetch(),
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) void status.refetch();
    },
  });
  const executeRun = execute.mutate;

  useEffect(() => {
    const data = status.data;
    if (!data) return;
    setProgress({
      activeStage: toFlowStage(data.result_ready ? "result" : data.stage),
      completedStages: data.completed_stages ?? [],
      totalStages: data.total_stages,
    });
  }, [setProgress, status.data]);

  useEffect(() => {
    const data = status.data;
    if (!data) return;
    if (data.status === "plan_ready" && data.plan_hash && !executeAttempted.current) {
      executeAttempted.current = true;
      executeRun({ plan_version: data.plan_version, plan_hash: data.plan_hash });
    }
  }, [executeRun, status.data]);

  if (status.isPending) return <section className="loading-state"><LoaderCircle className="spin" /><h1>正在读取运行状态</h1></section>;
  if (status.isError) return <section className="notice error" role="alert"><AlertTriangle /><div><h1>暂时无法连接运行</h1><p>运行编号仍保留在地址中，请检查服务后重试。</p><button className="secondary" onClick={() => void status.refetch()}><RefreshCw size={17} />重新连接</button></div></section>;

  const data = status.data;
  const isComplete = data.status === "completed" || data.status === "completed_with_warnings";
  const isFailed = data.status === "failed" || data.status === "stale";
  const copy = stageCopy[data.stage ?? data.status] ?? { title: "职业匹配正在运行", description: "服务器会给出下一次安全轮询时间，刷新页面也可恢复。" };

  if (isComplete) return (
    <section className="run-complete">
      <CheckCircle2 size={48} />
      <p className="eyebrow">运行已完成</p><h1>推荐与证据已经准备好</h1>
      {data.warning_codes?.length ? <div className="notice warning"><AlertTriangle /><span>结果可查看，但包含提醒：{data.warning_codes.join("、")}</span></div> : null}
      <Link className="button primary" to={`/runs/${runId}/results`}>查看完整结果<ArrowRight size={18} /></Link>
    </section>
  );
  if (isFailed) return (
    <section className="run-failed"><p className="eyebrow">需要恢复</p><h1>这次运行没有完成</h1><p>安全错误码：<code>{data.error_code ?? "RUN_FAILED"}</code></p><div className="button-row"><Link className="button secondary" to={`/sessions/${data.session_id}/brief`}>返回 Match Brief</Link><Link className="button primary" to="/">创建新任务</Link></div></section>
  );

  return (
    <section className="run-live" aria-live="polite">
      <div className="run-orbit"><span /><LoaderCircle className="spin" size={40} /></div>
      <p className="eyebrow">Run {runId.slice(0, 8)}</p>
      <h1>{copy.title}</h1><p className="lead">{copy.description}</p>
      <dl className="run-facts"><div><dt>当前阶段</dt><dd>{data.stage ?? data.status}</dd></div><div><dt>已完成阶段</dt><dd>{data.completed_stages?.length ?? 0} / {data.total_stages}</dd></div><div><dt>状态恢复</dt><dd>可安全刷新</dd></div></dl>
      {execute.isError && !(execute.error instanceof ApiError && execute.error.status === 409) ? <p className="inline-error">执行请求失败，正在保留当前运行。</p> : null}
    </section>
  );
}
