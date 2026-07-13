import { useMutation } from "@tanstack/react-query";
import { CheckCircle2, Send } from "lucide-react";
import { useState, type FormEvent } from "react";

import { api } from "../../api/queries";

export function ReactionNotice() {
  return <p className="feedback-note">反馈会先保存在私有记录中，不会自动发布为匿名案例。</p>;
}

export function ReactionForm({ runId, jobId }: { runId: string; jobId: string }) {
  const [outcome, setOutcome] = useState("helpful");
  const [rating, setRating] = useState(4);
  const [reason, setReason] = useState("");
  const reaction = useMutation({
    mutationFn: () => api.addReaction(runId, { job_id: jobId, outcome, user_rating: rating, reason: reason.trim() || null, idempotency_key: crypto.randomUUID() }),
  });
  const submit = (event: FormEvent) => { event.preventDefault(); reaction.mutate(); };
  if (reaction.isSuccess) return <div className="feedback-success"><CheckCircle2 /><span>反馈已记录，谢谢你的判断。</span></div>;
  return (
    <form className="reaction-form" onSubmit={submit}>
      <h3>这个推荐有帮助吗？</h3>
      <div className="form-grid">
        <label>反馈结果<select value={outcome} onChange={(event) => setOutcome(event.target.value)}><option value="helpful">有帮助</option><option value="not_relevant">不相关</option><option value="applied">已投递</option><option value="interview">获得面试</option></select></label>
        <label>评分<select value={rating} onChange={(event) => setRating(Number(event.target.value))}>{[1, 2, 3, 4, 5].map((value) => <option value={value} key={value}>{value} / 5</option>)}</select></label>
        <label className="wide">原因（可选）<textarea rows={2} value={reason} onChange={(event) => setReason(event.target.value)} /></label>
      </div>
      <ReactionNotice />
      {reaction.isError ? <p className="inline-error">反馈暂时未保存，请重试。</p> : null}
      <button className="secondary" disabled={reaction.isPending}><Send size={17} />{reaction.isPending ? "正在提交…" : "提交反馈"}</button>
    </form>
  );
}
