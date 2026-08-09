import { ChevronDown, FileCheck2 } from "lucide-react";
import { useId, useState } from "react";

import type { EvidenceItem, SkillGap } from "../../api/queries";
import { useLanguage } from "../../i18n";

type EvidenceDrawerProps = {
  title: string;
  evidence: EvidenceItem[];
  resumeEvidence: EvidenceItem[];
  agentMatchReasons?: string[];
  skillGaps?: SkillGap[];
};

function evidencePoints(content: string): string[] {
  return content
    .replace(/\r\n?/g, "\n")
    .replace(/(^|\n)\s*[-*•▪◦]\s*/g, "\n")
    .replace(/[。；;]/g, "$&\n")
    .replace(/([.!?])\s+/g, "$1\n")
    .split(/\n+/)
    .map((point) => point.trim())
    .filter(Boolean);
}

export function EvidenceDrawer({ title, evidence, resumeEvidence, agentMatchReasons = [], skillGaps = [] }: EvidenceDrawerProps) {
  const { t } = useLanguage();
  const [open, setOpen] = useState(false);
  const panelId = useId();

  return (
    <section className="v2-evidence-accordion" aria-label={t("{title} 的匹配证据", { title })}>
      <button
        className="v2-evidence-trigger"
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((current) => !current)}
      >
        <FileCheck2 size={17} />
        {t("查看证据")}
        <ChevronDown className="v2-evidence-chevron" size={16} aria-hidden="true" />
      </button>
      {open ? (
        <div className="v2-evidence-panel" id={panelId}>
          {agentMatchReasons.length ? (
            <section>
              <h3>{t("Agent 匹配理由")}</h3>
              <ul>{agentMatchReasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
            </section>
          ) : null}
          {evidence.length ? (
            <section>
              <h3>{t("岗位原文证据")}</h3>
              <div className="v2-evidence-list">
                {evidence.map((item) => (
                  <article className="v2-evidence-item" key={item.evidence_span_id}>
                    <span className="v2-evidence-source">{t("出自 JD 原文")}</span>
                    <code>{item.evidence_span_id}</code>
                    <ul className="v2-evidence-snippets">
                      {evidencePoints(item.content).map((point, index) => (
                        <li key={`${item.evidence_span_id}-${index}`}>{point}</li>
                      ))}
                    </ul>
                    {item.field ? <small>{item.field}</small> : null}
                  </article>
                ))}
              </div>
            </section>
          ) : null}
          {resumeEvidence.length ? (
            <section>
              <h3>{t("简历事实证据")}</h3>
              <ul className="v2-evidence-list">
                {resumeEvidence.map((item) => (
                  <li key={item.evidence_span_id}>
                    <code>{item.evidence_span_id}</code>
                    <p>{item.content}</p>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
          {skillGaps.length ? (
            <section>
              <h3>{t("相关技能缺口")}</h3>
              <ul>{skillGaps.map((gap) => <li key={`${gap.skill}-${gap.gap}`}><strong>{gap.skill}</strong>{t("：{gap}", { gap: gap.gap })}</li>)}</ul>
            </section>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
