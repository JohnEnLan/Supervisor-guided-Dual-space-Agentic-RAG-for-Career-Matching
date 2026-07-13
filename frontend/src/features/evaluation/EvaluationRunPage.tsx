import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, FlaskConical } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { api } from "../../api/queries";

export function ExplainUnavailable({ runId }: { runId?: string }) {
  return <section className="empty-state"><p className="eyebrow">Examiner View</p><h1>评估解释未开启</h1><p>此部署未开放论文评估视图。产品推荐与岗位证据仍可正常查看。</p>{runId ? <Link className="button secondary" to={`/runs/${runId}/results`}>返回产品结果</Link> : null}</section>;
}

export function EvaluationRunPage() {
  const { runId = "" } = useParams();
  const capabilities = useQuery({ queryKey: ["capabilities"], queryFn: api.capabilities });
  const explain = useQuery({ queryKey: ["run-explain", runId], queryFn: () => api.runExplain(runId), enabled: capabilities.data?.explain_enabled === true && Boolean(runId), retry: false });
  if (capabilities.isPending) return <section className="loading-state"><h1>正在读取评估能力</h1></section>;
  if (!capabilities.data?.explain_enabled) return <ExplainUnavailable runId={runId} />;
  if (explain.isPending) return <section className="loading-state"><h1>正在读取融合解释</h1></section>;
  if (explain.isError) return <section className="notice error"><AlertTriangle /><div><h1>解释暂时不可用</h1><p>公开结果不会因此失效。</p></div></section>;
  return (
    <section>
      <header className="results-header"><div><p className="eyebrow">Examiner View</p><h1>双空间检索与恢复轨迹</h1><p>仅展示允许公开的排序、匿名案例标识、融合参数与阶段耗时。</p></div><Link className="button secondary" to={`/runs/${runId}/results`}>返回产品结果</Link></header>
      <div className="metric-strip"><article><span>隐式最大权重</span><strong>{explain.data.fusion.implicit_max_weight.toFixed(2)}</strong></article><article><span>排序记录</span><strong>{explain.data.rank_trace?.length ?? 0}</strong></article><article><span>有界恢复</span><strong>{explain.data.recovery_events?.length ?? 0}</strong></article></div>
      <section className="table-section"><h2><FlaskConical size={19} />候选排序轨迹</h2><div className="table-scroll"><table><thead><tr><th>岗位 ID</th><th>显式排名</th><th>隐式排名</th><th>最终排名</th><th>隐式权重</th><th>匿名案例证据</th></tr></thead><tbody>{explain.data.rank_trace?.map((row) => <tr key={row.job_id}><td><code>{row.job_id}</code></td><td>{row.explicit_rank ?? "—"}</td><td>{row.implicit_rank ?? "—"}</td><td>{row.final_rank}</td><td>{row.implicit_weight.toFixed(3)}</td><td>{row.case_evidence?.length ? row.case_evidence.map((item) => <span className="case-chip" key={item.case_id}>{item.case_id} · {item.highest_stage} · {item.confidence?.toFixed(2) ?? "—"}</span>) : "无"}</td></tr>)}</tbody></table></div></section>
      <div className="strategy-grid"><section><h2>阶段耗时</h2><dl className="duration-list">{Object.entries(explain.data.stage_durations_ms ?? {}).map(([stage, duration]) => <div key={stage}><dt>{stage}</dt><dd>{duration} ms</dd></div>)}</dl></section><section><h2>有界恢复事件</h2>{explain.data.recovery_events?.length ? <ol>{explain.data.recovery_events.map((event, index) => <li key={`${event.stage}-${index}`}>{event.stage}：{event.reason}（{event.attempt}/{event.max_attempts}）</li>)}</ol> : <p className="muted">本次运行未触发恢复循环。</p>}</section></div>
    </section>
  );
}
