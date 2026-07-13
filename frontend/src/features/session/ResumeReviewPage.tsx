import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertTriangle, Check, GraduationCap, Lightbulb, LoaderCircle, Wrench } from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";

import { ApiError, recoveryMessage } from "../../api/client";
import { api, type ResumePreview } from "../../api/queries";

type ResumePreviewContentProps = {
  preview: ResumePreview;
  onConfirm: () => void;
  isConfirming: boolean;
};

export function ResumePreviewContent({ preview, onConfirm, isConfirming }: ResumePreviewContentProps) {
  return (
    <>
      {preview.resume_quality_issues?.length ? (
        <section className="notice warning" aria-labelledby="quality-title">
          <AlertTriangle size={20} />
          <div><h2 id="quality-title">排版与内容提醒</h2><ul>{preview.resume_quality_issues.map((issue) => <li key={issue}>{issue}</li>)}</ul></div>
        </section>
      ) : null}
      <div className="review-grid">
        <section className="content-section wide">
          <h2><Wrench size={19} />技能</h2>
          <div className="tag-list">{preview.skills?.map((skill) => <span className="tag" key={skill}>{skill}</span>)}</div>
        </section>
        <section className="content-section">
          <h2>工作经历</h2>
          {preview.experience?.length ? preview.experience.map((item, index) => (
            <article className="timeline-item" key={`${item.organization}-${index}`}>
              <h3>{item.title}</h3><p>{item.organization} · {item.location} · {item.dates}</p>
              <ul>{[...(item.achievements ?? []), ...(item.responsibilities ?? [])].map((line) => <li key={line}>{line}</li>)}</ul>
            </article>
          )) : <p className="muted">未提取到工作经历。</p>}
        </section>
        <section className="content-section">
          <h2><GraduationCap size={19} />教育经历</h2>
          {preview.education?.map((item, index) => (
            <article key={`${item.institution}-${index}`}><h3>{item.degree} · {item.field}</h3><p>{item.institution} · {item.dates}</p></article>
          ))}
        </section>
        <section className="content-section wide">
          <h2><Lightbulb size={19} />项目经历</h2>
          {preview.projects?.length ? preview.projects.map((item, index) => (
            <article key={`${item.name}-${index}`}><h3>{item.name}</h3><p>{item.summary}</p><ul>{item.outcomes?.map((line) => <li key={line}>{line}</li>)}</ul></article>
          )) : <p className="muted">未提取到独立项目。</p>}
        </section>
      </div>
      {preview.evidence?.length ? (
        <details className="evidence-preview"><summary>查看提取依据（{preview.evidence.length} 条）</summary><ul>{preview.evidence.map((item) => <li key={item.evidence_span_id}><code>{item.evidence_span_id}</code> {item.content}</li>)}</ul></details>
      ) : null}
      <div className="action-bar">
        <p>请核对结构化信息。确认后将进入目标职业与目标公司的咨询。</p>
        <button className="primary" type="button" onClick={onConfirm} disabled={isConfirming || preview.confirmed}>
          <Check size={18} />{preview.confirmed ? "简历已确认" : isConfirming ? "正在确认…" : "确认简历"}
        </button>
      </div>
    </>
  );
}

export function ResumeReviewPage() {
  const { sessionId = "" } = useParams();
  const navigate = useNavigate();
  const preview = useQuery({
    queryKey: ["resume-preview", sessionId],
    queryFn: () => api.resumePreview(sessionId),
    enabled: Boolean(sessionId),
    retry: (count, error) => error instanceof ApiError && error.status === 409 && count < 6,
    retryDelay: 1200,
  });
  const confirm = useMutation({
    mutationFn: () => api.confirmResume(sessionId),
    onSuccess: () => navigate(`/sessions/${sessionId}/brief`),
  });

  if (preview.isPending) return <section className="loading-state"><LoaderCircle className="spin" /><h1>正在提取简历信息</h1><p>完成后会自动显示结构化预览。</p></section>;
  if (preview.isError) return <section className="notice error" role="alert"><AlertTriangle /><div><h1>暂时无法读取简历预览</h1><p>{preview.error instanceof ApiError ? recoveryMessage(preview.error) : "请稍后重试。"}</p><button className="secondary" onClick={() => void preview.refetch()}>重新读取</button></div></section>;

  return (
    <section>
      <p className="eyebrow">Stage 0 · Resume Intake</p>
      <h1>确认系统理解的简历事实</h1>
      <p className="lead">这里只显示结构化字段与必要的原文证据，不展示或传递完整归一化简历。</p>
      <ResumePreviewContent preview={preview.data} onConfirm={() => confirm.mutate()} isConfirming={confirm.isPending} />
      {confirm.isError ? <p className="inline-error" role="alert">确认失败，请重试。</p> : null}
    </section>
  );
}
