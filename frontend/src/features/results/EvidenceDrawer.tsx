import { ChevronDown, FileCheck2 } from "lucide-react";
import { useId, useState } from "react";

import type { EvidenceItem, SkillGap } from "../../api/queries";

type EvidenceDrawerProps = {
  title: string;
  evidence: EvidenceItem[];
  resumeEvidence: EvidenceItem[];
  agentMatchReasons?: string[];
  skillGaps?: SkillGap[];
};

export function EvidenceDrawer({ title, evidence, resumeEvidence, agentMatchReasons = [], skillGaps = [] }: EvidenceDrawerProps) {
  const [open, setOpen] = useState(false);
  const panelId = useId();

  return (
    <section className="v2-evidence-accordion" aria-label={`${title} 的匹配证据`}>
      <button
        className="v2-evidence-trigger"
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((current) => !current)}
      >
        <FileCheck2 size={17} />
        查看证据
        <ChevronDown className="v2-evidence-chevron" size={16} aria-hidden="true" />
      </button>
      {open ? (
        <div className="v2-evidence-panel" id={panelId}>
          <section>
            <h3>Agent 匹配理由</h3>
            {agentMatchReasons.length ? (
              <ul>{agentMatchReasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
            ) : (
              <p>没有额外的 Agent 匹配理由。当前 API 未投影独立的确定性 must-have 命中，因此不会把自由文本解释标记为规则命中。</p>
            )}
          </section>
          <section>
            <h3>岗位原文证据</h3>
            {evidence.length ? (
              <ul className="v2-evidence-list">
                {evidence.map((item) => (
                  <li key={item.evidence_span_id}>
                    <span className="v2-evidence-source">出自 JD 原文</span>
                    <code>{item.evidence_span_id}</code>
                    <p>{item.content}</p>
                    {item.field ? <small>{item.field}</small> : null}
                  </li>
                ))}
              </ul>
            ) : (
              <p>没有可公开的 JD 证据；该岗位不应进入推荐。</p>
            )}
          </section>
          <section>
            <h3>简历事实证据</h3>
            {resumeEvidence.length ? (
              <ul className="v2-evidence-list">
                {resumeEvidence.map((item) => (
                  <li key={item.evidence_span_id}>
                    <code>{item.evidence_span_id}</code>
                    <p>{item.content}</p>
                  </li>
                ))}
              </ul>
            ) : (
              <p>当前解释没有额外展示简历片段。</p>
            )}
          </section>
          <section>
            <h3>相关技能缺口</h3>
            {skillGaps.length ? (
              <ul>{skillGaps.map((gap) => <li key={`${gap.skill}-${gap.gap}`}><strong>{gap.skill}</strong>：{gap.gap}</li>)}</ul>
            ) : (
              <p>没有投影额外技能缺口。</p>
            )}
          </section>
        </div>
      ) : null}
    </section>
  );
}
