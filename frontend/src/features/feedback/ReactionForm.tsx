import { useMutation } from "@tanstack/react-query";
import { CheckCircle2, Send } from "lucide-react";
import { useId, useRef, useState, type FormEvent } from "react";

import { api } from "../../api/queries";

const OUTCOMES = [
  { label: "被拒", value: "rejected" },
  { label: "过筛", value: "passed_screen" },
  { label: "面试", value: "interview" },
  { label: "Offer", value: "offer" },
] as const;

export function ReactionNotice() {
  return <p className="feedback-note">反馈会先保存在私有记录中，不会自动发布为匿名案例。</p>;
}

export function ReactionForm({ runId, jobId }: { runId: string; jobId: string }) {
  const [outcome, setOutcome] = useState<string | null>(null);
  const [notesOpen, setNotesOpen] = useState(false);
  const notesId = useId();
  const [reason, setReason] = useState("");
  const idempotencyKey = useRef(crypto.randomUUID());
  const reaction = useMutation({
    mutationFn: () => {
      if (!outcome) throw new Error("outcome missing");
      return api.addReaction(runId, {
        job_id: jobId,
        outcome,
        user_rating: null,
        reason: reason.trim() || null,
        idempotency_key: idempotencyKey.current,
      });
    },
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (outcome) reaction.mutate();
  };
  if (reaction.isSuccess)
    return (
      <div className="feedback-success">
        <CheckCircle2 />
        <span>进展已记录，谢谢你回来更新。</span>
      </div>
    );
  return (
    <form className="reaction-form" onSubmit={submit}>
      <h3>投递后回来告诉我们进展</h3>
      <div className="reaction-outcomes" aria-label="申请进展">
        {OUTCOMES.map((item) => (
          <button
            key={item.value}
            type="button"
            value={item.value}
            aria-pressed={outcome === item.value}
            onClick={() => setOutcome(item.value)}
          >
            {item.label}
          </button>
        ))}
      </div>
      <button
        type="button"
        className="reaction-notes-toggle"
        aria-expanded={notesOpen}
        aria-controls={notesOpen ? notesId : undefined}
        onClick={() => setNotesOpen((open) => !open)}
      >
        {notesOpen ? "收起备注" : "添加备注"}
      </button>
      {notesOpen ? (
        <label className="reaction-notes" id={notesId}>
          备注（可选）
          <textarea rows={2} value={reason} onChange={(event) => setReason(event.target.value)} />
        </label>
      ) : null}
      <ReactionNotice />
      {reaction.isError ? <p className="inline-error">进展暂时未保存，请重试。</p> : null}
      <button className="secondary" disabled={!outcome || reaction.isPending}>
        <Send size={17} />
        {reaction.isPending ? "正在提交…" : "提交进展"}
      </button>
    </form>
  );
}
