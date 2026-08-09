import { useQuery } from "@tanstack/react-query";
import { Activity, AlertTriangle, FlaskConical, Search } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

import { MonitoringContent } from "../../features/monitoring/MonitoringPage";
import { api } from "../../api/queries";
import type { GuardedAdminRequest } from "./types";

type OperationsMode = "evaluation" | "monitoring";

function EvaluationPanel({
  initialRunId,
  request,
  onRunIdChange,
}: {
  initialRunId: string;
  request: GuardedAdminRequest;
  onRunIdChange: (runId: string) => void;
}) {
  const [input, setInput] = useState(initialRunId);
  useEffect(() => setInput(initialRunId), [initialRunId]);
  const explain = useQuery({
    queryKey: ["admin", "run-explain", initialRunId],
    queryFn: () => request(() => api.adminRunExplain(initialRunId)),
    enabled: Boolean(initialRunId),
    retry: false,
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const next = input.trim();
    if (!next) return;
    onRunIdChange(next);
  };
  return (
    <section aria-labelledby="admin-evaluation-title">
      <header className="v2-admin-subheading"><div><p>CROSS-USER TRACE</p><h3 id="admin-evaluation-title">评估解释</h3></div><span>不受 evaluation capability 门控</span></header>
      <form className="v2-admin-run-search" onSubmit={submit}>
        <label htmlFor="admin-run-id">Run ID</label>
        <input id="admin-run-id" value={input} onChange={(event) => setInput(event.target.value)} placeholder="输入 run_id" />
        <button type="submit"><Search size={16} />查看解释</button>
      </form>
      {!initialRunId ? <p className="v2-admin-empty">输入 run_id 查看跨用户检索与恢复轨迹。</p> : null}
      {explain.isPending && initialRunId ? <p className="v2-admin-inline-state" role="status">正在读取运行解释</p> : null}
      {explain.isError ? <p className="v2-admin-error" role="alert"><AlertTriangle size={17} />运行不存在、尚未终结或 trace 不可用。</p> : null}
      {explain.data ? (
        <div className="v2-admin-explain">
          <div className="v2-admin-explain-metrics">
            <article><span>隐式最大权重</span><strong>{explain.data.fusion.implicit_max_weight.toFixed(2)}</strong></article>
            <article><span>排序记录</span><strong>{explain.data.rank_trace?.length ?? 0}</strong></article>
            <article><span>恢复事件</span><strong>{explain.data.recovery_events?.length ?? 0}</strong></article>
          </div>
          <div className="v2-admin-table-scroll">
            <table><thead><tr><th>岗位 ID</th><th>显式排名</th><th>隐式排名</th><th>最终排名</th><th>隐式权重</th></tr></thead>
              <tbody>{explain.data.rank_trace?.length ? explain.data.rank_trace.map((row) => (
                <tr key={row.job_id}><td><code>{row.job_id}</code></td><td>{row.explicit_rank ?? "—"}</td><td>{row.implicit_rank ?? "—"}</td><td>{row.final_rank}</td><td>{row.implicit_weight.toFixed(3)}</td></tr>
              )) : <tr><td colSpan={5}>暂无排序记录</td></tr>}</tbody>
            </table>
          </div>
          <details><summary>阶段耗时与恢复事件</summary><pre>{JSON.stringify({ stage_durations_ms: explain.data.stage_durations_ms, recovery_events: explain.data.recovery_events }, null, 2)}</pre></details>
        </div>
      ) : null}
    </section>
  );
}

function MonitoringPanel({ request }: { request: GuardedAdminRequest }) {
  const [windowHours, setWindowHours] = useState(24);
  const overview = useQuery({
    queryKey: ["admin", "monitoring-overview", windowHours],
    queryFn: () => request(() => api.monitoringOverview(windowHours)),
    retry: false,
  });
  const runs = useQuery({
    queryKey: ["admin", "monitoring-runs", windowHours],
    queryFn: () => request(() => api.monitoringRuns(windowHours, 20)),
    retry: false,
  });
  const hasData = overview.data && runs.data;
  return (
    <section aria-labelledby="admin-monitoring-title">
      <header className="v2-admin-subheading"><div><p>READ-ONLY OPERATIONS</p><h3 id="admin-monitoring-title">运行监控</h3></div>
        <label>时间窗口<select value={windowHours} onChange={(event) => setWindowHours(Number(event.target.value))}><option value={1}>最近 1 小时</option><option value={24}>最近 24 小时</option><option value={168}>最近 7 天</option></select></label>
      </header>
      {!hasData && (overview.isPending || runs.isPending) ? <p className="v2-admin-inline-state" role="status">正在汇总运行指标</p> : null}
      {!hasData && (overview.isError || runs.isError) ? <p className="v2-admin-error" role="alert"><AlertTriangle size={17} />监控数据暂时不可用。</p> : null}
      {hasData ? <MonitoringContent overview={overview.data} runs={runs.data} /> : null}
    </section>
  );
}

export function AdminOperations({
  mode,
  request,
  runIdFromUrl,
  onModeChange,
  onRunIdChange,
}: {
  mode: OperationsMode;
  request: GuardedAdminRequest;
  runIdFromUrl: string;
  onModeChange: (mode: OperationsMode) => void;
  onRunIdChange: (runId: string) => void;
}) {
  return (
    <section aria-labelledby="admin-operations-title">
      <header className="v2-admin-section-heading"><div><p>EXAMINER & OPS</p><h2 id="admin-operations-title">评估与监控</h2></div><span>管理员专用</span></header>
      <nav className="v2-admin-subtabs" aria-label="评估与监控视图">
        <button type="button" aria-current={mode === "evaluation" ? "page" : undefined} onClick={() => onModeChange("evaluation")}><FlaskConical size={16} />评估解释</button>
        <button type="button" aria-current={mode === "monitoring" ? "page" : undefined} onClick={() => onModeChange("monitoring")}><Activity size={16} />运行监控</button>
      </nav>
      {mode === "evaluation" ? <EvaluationPanel initialRunId={runIdFromUrl} request={request} onRunIdChange={onRunIdChange} /> : null}
      {mode === "monitoring" ? <MonitoringPanel request={request} /> : null}
    </section>
  );
}
