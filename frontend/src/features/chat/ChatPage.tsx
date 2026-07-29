import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, LoaderCircle, RefreshCw, Users } from "lucide-react";
import { useEffect, useRef } from "react";
import { Link, useParams } from "react-router-dom";

import { api, type ConversationMessage, type RunConversation } from "../../api/queries";

const TERMINAL_STATUSES = new Set(["completed", "completed_with_warnings", "failed", "stale"]);

export function conversationRefetchInterval(
  data: Pick<RunConversation, "status" | "next_poll_ms"> | undefined,
): number | false {
  if (!data || TERMINAL_STATUSES.has(data.status) || data.next_poll_ms == null) return false;
  return data.next_poll_ms;
}

export const PERSONA_META: Record<string, { short: string; roleLabel: string }> = {
  intent_consultant: { short: "意", roleLabel: "需求对接" },
  job_scout: { short: "检", roleLabel: "岗位筛选" },
  strategist: { short: "策", roleLabel: "职业规划" },
  pm: { short: "PM", roleLabel: "监督 · A2A" },
};

function MessageBubble({ message }: { message: ConversationMessage }) {
  const meta = PERSONA_META[message.persona] ?? { short: "?", roleLabel: "成员" };
  const attention = message.kind === "recovery" || message.kind === "warning" || message.kind === "error";
  return (
    <li className="chat-message" data-persona={message.persona} data-kind={message.kind}>
      <span className="chat-avatar" aria-hidden="true">{meta.short}</span>
      <div className="chat-body">
        <header>
          <strong>{message.display_name}</strong>
          <span className="chat-role">{meta.roleLabel}</span>
        </header>
        <p className={attention ? "chat-text attention" : "chat-text"}>
          {attention ? <AlertTriangle size={15} aria-hidden="true" /> : null}
          {message.text}
        </p>
      </div>
    </li>
  );
}

export function ChatPage() {
  const { runId = "" } = useParams();
  const conversation = useQuery({
    queryKey: ["run-conversation", runId],
    queryFn: () => api.runConversation(runId),
    enabled: Boolean(runId),
    refetchInterval: (query) => conversationRefetchInterval(query.state.data),
  });
  const timelineRef = useRef<HTMLOListElement>(null);
  const messageCount = conversation.data?.messages?.length ?? 0;

  useEffect(() => {
    const timeline = timelineRef.current;
    if (timeline) timeline.scrollTop = timeline.scrollHeight;
  }, [messageCount]);

  if (conversation.isPending) {
    return (
      <section className="loading-state">
        <LoaderCircle className="spin" />
        <h1>正在进入服务群</h1>
      </section>
    );
  }
  if (conversation.isError) {
    return (
      <section className="notice error" role="alert">
        <AlertTriangle />
        <div>
          <h1>暂时无法读取群聊</h1>
          <p>运行编号仍保留在地址中，请检查服务后重试。</p>
          <button className="secondary" onClick={() => void conversation.refetch()}>
            <RefreshCw size={17} />
            重新连接
          </button>
        </div>
      </section>
    );
  }

  const data = conversation.data;
  const live = !TERMINAL_STATUSES.has(data.status);
  const completed = data.status === "completed" || data.status === "completed_with_warnings";

  return (
    <section className="chat-room">
      <header className="chat-header">
        <div className="chat-title">
          <Users size={20} aria-hidden="true" />
          <div>
            <h1>职业规划服务群</h1>
            <p>
              Run {runId.slice(0, 8)} · 4 位服务成员 ·
              {live ? " 服务进行中" : completed ? " 服务已完成" : " 服务已结束"}
            </p>
          </div>
        </div>
        <ul className="chat-members" aria-label="服务成员">
          {Object.entries(PERSONA_META).map(([persona, meta]) => (
            <li key={persona} data-persona={persona}>
              <span className="chat-avatar" aria-hidden="true">{meta.short}</span>
              {meta.roleLabel}
            </li>
          ))}
        </ul>
      </header>

      <ol className="chat-timeline" ref={timelineRef} aria-live="polite">
        {(data.messages ?? []).map((message) => (
          <MessageBubble key={message.seq} message={message} />
        ))}
        {live ? (
          <li className="chat-typing" aria-label="团队正在工作">
            <LoaderCircle className="spin" size={15} />
            团队正在处理下一阶段…
          </li>
        ) : null}
      </ol>

      <footer className="chat-footer">
        {completed ? (
          <Link className="button primary" to={`/runs/${runId}/results`}>
            查看完整结果与证据
            <ArrowRight size={18} />
          </Link>
        ) : (
          <Link className="button secondary" to={`/runs/${runId}`}>
            切换到进度视图
          </Link>
        )}
      </footer>
    </section>
  );
}
