import { FileCheck2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

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
  const trigger = useRef<HTMLButtonElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const drawer = useRef<HTMLElement>(null);

  const close = () => {
    setOpen(false);
    queueMicrotask(() => trigger.current?.focus());
  };

  useEffect(() => {
    if (!open) return;
    closeButton.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
      if (event.key !== "Tab") return;
      const focusable = Array.from(
        drawer.current?.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      );
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open]);

  return (
    <>
      <button ref={trigger} className="secondary evidence-trigger" type="button" onClick={() => setOpen(true)}><FileCheck2 size={17} />查看证据</button>
      {open ? (
        <div className="drawer-backdrop" onMouseDown={(event) => { if (event.currentTarget === event.target) close(); }}>
          <section ref={drawer} className="evidence-drawer" role="dialog" aria-modal="true" aria-labelledby="evidence-drawer-title">
            <header><div><p className="eyebrow">Evidence</p><h2 id="evidence-drawer-title">{title} 的匹配证据</h2></div><button ref={closeButton} className="icon-button" type="button" aria-label="关闭证据" onClick={close}><X /></button></header>
            <div className="drawer-content">
              <section><h3>Agent 匹配理由</h3>{agentMatchReasons.length ? <ul className="check-list">{agentMatchReasons.map((reason) => <li key={reason}>{reason}</li>)}</ul> : <p className="muted">没有额外的 Agent 匹配理由。当前 API 未投影独立的确定性 must-have 命中，因此这里不会把自由文本解释标记为规则命中。</p>}</section>
              <section><h3>岗位原文证据</h3>{evidence.length ? <ul className="evidence-list">{evidence.map((item) => <li key={item.evidence_span_id}><code>{item.evidence_span_id}</code><p>{item.content}</p>{item.field ? <span>{item.field}</span> : null}</li>)}</ul> : <p className="muted">没有可公开的 JD 证据；该岗位不应进入推荐。</p>}</section>
              <section><h3>简历事实证据</h3>{resumeEvidence.length ? <ul className="evidence-list">{resumeEvidence.map((item) => <li key={item.evidence_span_id}><code>{item.evidence_span_id}</code><p>{item.content}</p></li>)}</ul> : <p className="muted">当前解释没有额外展示简历片段。</p>}</section>
              <section><h3>相关技能缺口</h3>{skillGaps.length ? <ul>{skillGaps.map((gap) => <li key={`${gap.skill}-${gap.gap}`}><strong>{gap.skill}</strong>：{gap.gap}</li>)}</ul> : <p className="muted">没有投影额外技能缺口。</p>}</section>
            </div>
          </section>
        </div>
      ) : null}
    </>
  );
}
