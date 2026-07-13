import { useQuery } from "@tanstack/react-query";
import { Activity, AlertTriangle, Clock3, Database, RefreshCw, ShieldCheck } from "lucide-react";
import { useState } from "react";

import { api, type MonitoringOverview, type RecentRuns } from "../../api/queries";

const percent = (value: number): string => `${(value * 100).toFixed(1)}%`;
const duration = (value: number | null | undefined): string => value == null ? "—" : value < 1000 ? `${Math.round(value)} ms` : `${(value / 1000).toFixed(1)} s`;
const time = (value: string | null | undefined): string => value ? new Intl.DateTimeFormat("zh-CN", { dateStyle: "short", timeStyle: "medium" }).format(new Date(value)) : "—";

export function MonitoringUnavailable() {
  return <section className="empty-state"><p className="eyebrow">Operations</p><h1>运行监控未开启</h1><p>设置 <code>MONITORING_ENABLED=true</code> 并重启后端即可启用只读监控。匹配主流程不受影响。</p></section>;
}

export function MonitoringContent({ overview, runs }: { overview: MonitoringOverview; runs: RecentRuns }) {
  const metrics = [
    ["运行总量", String(overview.total_runs), "窗口内创建的运行"],
    ["完成率", percent(overview.completion_rate), `失败率 ${percent(overview.failure_rate)}`],
    ["P95 总耗时", duration(overview.duration_p95_ms), `P50 ${duration(overview.duration_p50_ms)}`],
    ["平均推荐数", overview.average_recommendation_count.toFixed(1), "每个已投影结果"],
    ["JD 证据覆盖率", percent(overview.jd_evidence_coverage_rate), "公开推荐证据门"],
    ["双空间重排", String(overview.reordered_run_count), `隐式使用率 ${percent(overview.implicit_usage_rate)}`],
  ];
  return (
    <>
      <div className="monitor-metrics">{metrics.map(([label, value, note]) => <article key={label}><span>{label}</span><strong>{value}</strong><small>{note}</small></article>)}</div>
      <div className="monitor-grid">
        <section className="table-section"><h2><Clock3 size={19} />各阶段耗时</h2><div className="table-scroll"><table><thead><tr><th>阶段</th><th>P50</th><th>P95</th></tr></thead><tbody>{overview.stage_latencies?.length ? overview.stage_latencies.map((item) => <tr key={item.stage}><td>{item.stage}</td><td>{duration(item.p50_ms)}</td><td>{duration(item.p95_ms)}</td></tr>) : <tr><td colSpan={3}>暂无完成运行的耗时数据</td></tr>}</tbody></table></div></section>
        <section><h2><Activity size={19} />状态分布</h2><dl className="status-list">{Object.entries(overview.status_counts ?? {}).map(([status, count]) => <div key={status}><dt>{status}</dt><dd>{count}</dd></div>)}</dl><p className="monitor-note">警告率 {percent(overview.warning_rate)}。监控只读取持久化的 allow-list 指标。</p></section>
      </div>
      <section className="table-section recent-runs"><h2><Database size={19} />最近运行</h2><div className="table-scroll"><table><thead><tr><th>运行 ID</th><th>状态</th><th>阶段</th><th>推荐数</th><th>总耗时</th><th>警告/错误</th><th>更新时间</th></tr></thead><tbody>{runs.runs?.length ? runs.runs.map((run) => <tr key={run.run_id}><td><code>{run.run_id.slice(0, 12)}</code></td><td><span className={`status-pill ${run.status}`}>{run.status}</span></td><td>{run.stage ?? "—"}</td><td>{run.recommendation_count}</td><td>{duration(run.duration_ms)}</td><td>{run.error_code ?? run.warning_codes?.join("、") ?? "—"}</td><td>{time(run.updated_at)}</td></tr>) : <tr><td colSpan={7}>当前时间窗口暂无运行</td></tr>}</tbody></table></div></section>
    </>
  );
}

export function MonitoringPage() {
  const [windowHours, setWindowHours] = useState(24);
  const capabilities = useQuery({ queryKey: ["capabilities"], queryFn: api.capabilities });
  const enabled = capabilities.data?.monitoring_enabled === true;
  const overview = useQuery({ queryKey: ["monitoring-overview", windowHours], queryFn: () => api.monitoringOverview(windowHours), enabled, refetchInterval: enabled ? 5000 : false });
  const runs = useQuery({ queryKey: ["monitoring-runs", windowHours], queryFn: () => api.monitoringRuns(windowHours, 20), enabled, refetchInterval: enabled ? 5000 : false });

  if (capabilities.isPending) return <section className="loading-state"><h1>正在读取监控能力</h1></section>;
  if (!enabled) return <MonitoringUnavailable />;
  const hasData = overview.data && runs.data;
  return (
    <section>
      <header className="monitor-header"><div><p className="eyebrow">Read-only Operations</p><h1>运行效果与工作量监控</h1><p><ShieldCheck size={16} />不包含用户身份、完整简历、提示词或供应商错误详情。</p></div><label>时间窗口<select value={windowHours} onChange={(event) => setWindowHours(Number(event.target.value))}><option value={1}>最近 1 小时</option><option value={24}>最近 24 小时</option><option value={168}>最近 7 天</option></select></label></header>
      {(overview.isError || runs.isError) && hasData ? <div className="notice warning"><AlertTriangle /><div><strong>自动刷新暂时失败</strong><p>正在保留上一次成功数据（{time(overview.data.generated_at)}）。</p><button className="secondary" onClick={() => { void overview.refetch(); void runs.refetch(); }}><RefreshCw size={16} />立即重试</button></div></div> : null}
      {!hasData && (overview.isPending || runs.isPending) ? <section className="loading-state"><h1>正在汇总运行指标</h1></section> : null}
      {!hasData && (overview.isError || runs.isError) ? <section className="notice error"><AlertTriangle /><div><h2>监控数据暂时不可用</h2><button className="secondary" onClick={() => { void overview.refetch(); void runs.refetch(); }}>重试</button></div></section> : null}
      {hasData ? <><p className="last-updated">每 5 秒刷新 · 数据时间 {time(overview.data.generated_at)}</p><MonitoringContent overview={overview.data} runs={runs.data} /></> : null}
    </section>
  );
}
