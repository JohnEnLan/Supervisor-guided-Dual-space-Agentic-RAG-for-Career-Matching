import { ChevronDown, Paperclip } from "lucide-react";
import { useId, useState } from "react";

import type { ResumePreview } from "../api/queries";

type ResumeProfileAccordionProps = {
  preview: ResumePreview;
  reuploading: boolean;
  onReupload: (file: File) => void;
};

export function ResumeProfileAccordion({
  preview,
  reuploading,
  onReupload,
}: ResumeProfileAccordionProps) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const education = preview.education ?? [];
  const experience = preview.experience ?? [];
  const projects = preview.projects ?? [];
  const skills = preview.skills ?? [];
  const qualityIssues = preview.resume_quality_issues ?? [];
  const evidence = preview.evidence ?? [];

  return (
    <div className="v2-resume-profile">
      <div className="v2-resume-profile-actions">
        <button
          type="button"
          className="v2-resume-profile-trigger"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => setOpen((current) => !current)}
        >
          查看完整档案
          <ChevronDown size={16} aria-hidden="true" />
        </button>
        <label className="v2-resume-reupload">
          <Paperclip size={15} aria-hidden="true" />
          {reuploading ? "重新上传中…" : "重新上传"}
          <input
            type="file"
            accept=".pdf,.docx,.txt"
            aria-label="重新上传简历"
            disabled={reuploading}
            hidden
            onChange={(event) => {
              const file = event.currentTarget.files?.[0];
              if (file) onReupload(file);
              event.currentTarget.value = "";
            }}
          />
        </label>
      </div>

      {open ? (
        <section className="v2-resume-profile-panel" id={panelId} role="region" aria-label="完整简历档案">
          <section>
            <h3>教育经历</h3>
            {education.length ? (
              <div className="v2-resume-records">
                {education.map((item, index) => (
                  <article key={`${item.institution}-${item.dates}-${index}`}>
                    <strong>{item.institution}</strong>
                    <p>{[item.degree, item.field].filter(Boolean).join(" · ") || "未标注学位与专业"}</p>
                    <small>{item.dates || "未标注时间"}</small>
                    {item.details?.length ? <ul>{item.details.map((detail) => <li key={detail}>{detail}</li>)}</ul> : null}
                    {item.evidence_span_ids?.length ? <small>证据片段：{item.evidence_span_ids.join("、")}</small> : null}
                  </article>
                ))}
              </div>
            ) : <p className="v2-resume-empty">未识别到教育经历。</p>}
          </section>

          <section>
            <h3>工作经历</h3>
            {experience.length ? (
              <div className="v2-resume-records">
                {experience.map((item, index) => (
                  <article key={`${item.organization}-${item.title}-${item.dates}-${index}`}>
                    <strong>{item.organization}</strong>
                    <p>{[item.title, item.location].filter(Boolean).join(" · ") || "未标注职位与地点"}</p>
                    <small>{item.dates || "未标注时间"}</small>
                    {item.responsibilities?.length ? <ul>{item.responsibilities.map((detail) => <li key={detail}>{detail}</li>)}</ul> : null}
                    {item.achievements?.length ? <ul>{item.achievements.map((detail) => <li key={detail}>{detail}</li>)}</ul> : null}
                    {item.technologies?.length ? <p>技术：{item.technologies.join("、")}</p> : null}
                    {item.evidence_span_ids?.length ? <small>证据片段：{item.evidence_span_ids.join("、")}</small> : null}
                  </article>
                ))}
              </div>
            ) : <p className="v2-resume-empty">未识别到工作经历。</p>}
          </section>

          <section>
            <h3>项目经历</h3>
            {projects.length ? (
              <div className="v2-resume-records">
                {projects.map((item, index) => (
                  <article key={`${item.name}-${item.dates}-${index}`}>
                    <strong>{item.name}</strong>
                    <p>{item.summary || "未标注项目简介"}</p>
                    <small>{item.dates || "未标注时间"}</small>
                    {item.actions?.length ? <ul>{item.actions.map((detail) => <li key={detail}>{detail}</li>)}</ul> : null}
                    {item.outcomes?.length ? <ul>{item.outcomes.map((detail) => <li key={detail}>{detail}</li>)}</ul> : null}
                    {item.technologies?.length ? <p>技术：{item.technologies.join("、")}</p> : null}
                    {item.evidence_span_ids?.length ? <small>证据片段：{item.evidence_span_ids.join("、")}</small> : null}
                  </article>
                ))}
              </div>
            ) : <p className="v2-resume-empty">未识别到项目经历。</p>}
          </section>

          <section>
            <h3>技能</h3>
            {skills.length ? (
              <ul className="v2-resume-chips">{skills.map((skill) => <li key={skill}>{skill}</li>)}</ul>
            ) : <p className="v2-resume-empty">未识别到技能。</p>}
          </section>

          <section>
            <h3>档案质量提示</h3>
            {qualityIssues.length ? (
              <ul>{qualityIssues.map((issue) => <li key={issue}>{issue}</li>)}</ul>
            ) : <p className="v2-resume-empty">未发现需要提示的档案质量问题。</p>}
          </section>

          <section>
            <h3>原文证据</h3>
            {evidence.length ? (
              <ul className="v2-resume-evidence">
                {evidence.map((item) => (
                  <li key={item.evidence_span_id}>
                    <code>{item.evidence_span_id}</code>
                    <p>{item.content}</p>
                  </li>
                ))}
              </ul>
            ) : <p className="v2-resume-empty">没有可展示的原文证据。</p>}
          </section>
        </section>
      ) : null}
    </div>
  );
}
