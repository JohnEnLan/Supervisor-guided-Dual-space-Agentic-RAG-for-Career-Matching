import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowUpRight, Briefcase, CheckCircle2, MapPin } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, type RunResult } from "../../api/queries";
import { useFlowProgress } from "../../app/App";
import { ReactionForm } from "../feedback/ReactionForm";
import { EvidenceDrawer } from "./EvidenceDrawer";

const tierLabel = { now_fit: "Now Fit", stretch_fit: "Stretch Fit", bridge_role: "Bridge Role" } as const;

export function ResultsContent({ data, runId }: { data: RunResult; runId: string }) {
  const roles = data.result.recommended_roles ?? [];
  const [selectedId, setSelectedId] = useState(roles[0]?.job_id ?? "");
  const selected = roles.find((role) => role.job_id === selectedId) ?? roles[0];
  if (!selected) return <section className="empty-state"><h1>没有通过证据门的推荐</h1><p>没有岗位同时满足硬约束与 JD 证据要求。建议返回 Match Brief 放宽条件。</p></section>;
  return (
    <>
      <header className="results-header"><div><p className="eyebrow">统一推荐结果</p><h1>{data.result.summary}</h1><p>共 {roles.length} 个有 JD 证据的岗位；列表不代表录用承诺。</p></div><Link className="button secondary" to={`/runs/${runId}/explain`}>查看评估解释<ArrowUpRight size={17} /></Link></header>
      {data.result.warnings?.length ? <div className="notice warning"><AlertTriangle /><ul>{data.result.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div> : null}
      <div className="results-layout">
        <nav className="role-list" aria-label="推荐岗位">{roles.map((role, index) => <button type="button" key={role.job_id} className={role.job_id === selected.job_id ? "selected" : ""} onClick={() => setSelectedId(role.job_id)}><span className={`tier ${role.tier}`}>{tierLabel[role.tier]}</span><strong>{index + 1}. {role.title ?? "未命名岗位"}</strong><small>{role.company ?? "公司未公开"} · {role.location ?? "地点未公开"}</small></button>)}</nav>
        <article className="role-detail">
          <header><div><span className={`tier ${selected.tier}`}>{tierLabel[selected.tier]}</span><h2>{selected.title ?? "未命名岗位"}</h2><p><Briefcase size={16} />{selected.company ?? "公司未公开"} <MapPin size={16} />{selected.location ?? "地点未公开"}</p></div>{selected.source_url ? <a className="button secondary" href={selected.source_url} target="_blank" rel="noreferrer">岗位来源<ArrowUpRight size={16} /></a> : <span className="source-badge">离线数据集岗位</span>}</header>
          <section><h3>为什么推荐</h3><p>{selected.concise_explanation}</p><ul className="check-list">{selected.why_this_match?.map((reason) => <li key={reason}><CheckCircle2 size={16} />{reason}</li>)}</ul></section>
          <section><h3>JD 证据</h3><ul className="evidence-inline">{selected.evidence?.map((item) => <li key={item.evidence_span_id}><code>{item.evidence_span_id}</code>{item.content}</li>)}</ul><EvidenceDrawer title={selected.title ?? selected.job_id} evidence={selected.evidence ?? []} resumeEvidence={selected.resume_evidence ?? []} /></section>
          {data.result.skill_gaps?.length ? <section><h3>技能缺口</h3><div className="gap-list">{data.result.skill_gaps.map((gap) => <article key={`${gap.skill}-${gap.gap}`}><span className={`priority ${gap.priority || "low"}`}>{gap.priority || "待评估"}</span><strong>{gap.skill}</strong><p>{gap.gap}</p></article>)}</div></section> : null}
          <ReactionForm runId={runId} jobId={selected.job_id} />
        </article>
      </div>
      <div className="strategy-grid">
        <section><h2>简历策略</h2>{data.result.resume_strategy?.length ? <ol>{data.result.resume_strategy.map((item) => <li key={`${item.section}-${item.suggestion}`}><strong>{item.section}</strong><p>{item.suggestion}</p></li>)}</ol> : <p className="muted">暂无额外简历建议。</p>}</section>
        <section><h2>职业路径</h2>{data.result.career_path?.length ? <ol>{data.result.career_path.map((item) => <li key={`${item.horizon}-${item.action}`}><span>{item.horizon}</span><p>{item.action}</p></li>)}</ol> : <p className="muted">暂无额外路径建议。</p>}</section>
      </div>
    </>
  );
}

export function ResultsPage() {
  const { runId = "" } = useParams();
  const { setProgress } = useFlowProgress();
  const result = useQuery({ queryKey: ["run-result", runId], queryFn: () => api.runResult(runId), enabled: Boolean(runId), retry: false });
  useEffect(() => { setProgress({ activeStage: "result", completedStages: ["resume", "intent", "retrieval", "strategy", "verification", "finalization"] }); }, [setProgress]);
  if (result.isPending) return <section className="loading-state"><h1>正在读取结果</h1></section>;
  if (result.isError) return <section className="notice error" role="alert"><AlertTriangle /><div><h1>结果尚未可读</h1><p>运行可能仍在处理，返回进度页继续等待。</p><Link className="button secondary" to={`/runs/${runId}`}>返回运行</Link></div></section>;
  return <ResultsContent data={result.data} runId={runId} />;
}
