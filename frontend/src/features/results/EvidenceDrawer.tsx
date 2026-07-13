import { FileCheck2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { EvidenceItem } from "../../api/queries";

type EvidenceDrawerProps = {
  title: string;
  evidence: EvidenceItem[];
  resumeEvidence: EvidenceItem[];
};

export function EvidenceDrawer({ title, evidence, resumeEvidence }: EvidenceDrawerProps) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);

  const close = () => {
    setOpen(false);
    trigger.current?.focus();
  };

  useEffect(() => {
    if (!open) return;
    closeButton.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open]);

  return (
    <>
      <button ref={trigger} className="secondary evidence-trigger" type="button" onClick={() => setOpen(true)}><FileCheck2 size={17} />查看证据</button>
      {open ? (
        <div className="drawer-backdrop" onMouseDown={(event) => { if (event.currentTarget === event.target) close(); }}>
          <section className="evidence-drawer" role="dialog" aria-modal="true" aria-labelledby="evidence-drawer-title">
            <header><div><p className="eyebrow">Evidence</p><h2 id="evidence-drawer-title">{title} 的匹配证据</h2></div><button ref={closeButton} className="icon-button" type="button" aria-label="关闭证据" onClick={close}><X /></button></header>
            <div className="drawer-content">
              <section><h3>岗位原文证据</h3>{evidence.length ? <ul className="evidence-list">{evidence.map((item) => <li key={item.evidence_span_id}><code>{item.evidence_span_id}</code><p>{item.content}</p>{item.field ? <span>{item.field}</span> : null}</li>)}</ul> : <p className="muted">没有可公开的 JD 证据；该岗位不应进入推荐。</p>}</section>
              <section><h3>简历事实证据</h3>{resumeEvidence.length ? <ul className="evidence-list">{resumeEvidence.map((item) => <li key={item.evidence_span_id}><code>{item.evidence_span_id}</code><p>{item.content}</p></li>)}</ul> : <p className="muted">当前解释没有额外展示简历片段。</p>}</section>
            </div>
          </section>
        </div>
      ) : null}
    </>
  );
}
