import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BarChart3, LogOut, MessageSquarePlus, ScrollText, UserRound } from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { ApiError, onUnauthorized } from "../api/client";
import { api } from "../api/queries";
import {
  clearUserScopedStorage,
  readSessionTitle,
  SESSION_TITLE_UPDATED_EVENT,
} from "./localRunStorage";
import "./theme.css";

export type AppShellOutletContext = {
  startNewConsultation: () => void;
  isCreatingConsultation: boolean;
};

function sessionDateLabel(updatedAt: string): string {
  const match = /^(?:\d{4})-(\d{2})-(\d{2})/.exec(updatedAt);
  return match ? `${match[1]}-${match[2]}` : "-- --";
}

export function AppShell() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const me = useQuery({ queryKey: ["me"], queryFn: api.me, retry: false });
  const sessions = useQuery({
    queryKey: ["me-sessions"],
    queryFn: () => api.meSessions(1, 30),
    enabled: Boolean(me.data),
  });

  // 任意请求 401 → 清缓存回登录页（会话过期的统一出口）
  useEffect(() => {
    onUnauthorized(() => {
      clearUserScopedStorage(me.data?.user_id);
      queryClient.clear();
      navigate("/", { replace: true });
    });
    return () => onUnauthorized(null);
  }, [me.data?.user_id, navigate, queryClient]);

  useEffect(() => {
    if (me.isError) navigate("/", { replace: true });
  }, [me.isError, navigate]);

  const [quotaOpen, setQuotaOpen] = useState(false);
  const [, refreshSessionTitles] = useState(0);
  useEffect(() => {
    const onTitleUpdated = () => refreshSessionTitles((version) => version + 1);
    window.addEventListener(SESSION_TITLE_UPDATED_EVENT, onTitleUpdated);
    return () => window.removeEventListener(SESSION_TITLE_UPDATED_EVENT, onTitleUpdated);
  }, []);

  const createSession = useMutation({
    mutationFn: () => api.createSession({}),
    onSuccess: (session) => {
      void queryClient.invalidateQueries({ queryKey: ["me-sessions"] });
      navigate(`/app/sessions/${session.session_id}`);
    },
    onError: (error) => {
      // 402 = 会话额度用完 → 付费墙弹窗（支付暂未接入）
      if (error instanceof ApiError && error.status === 402) setQuotaOpen(true);
    },
  });

  const logout = useMutation({
    mutationFn: api.logout,
    onSettled: () => {
      clearUserScopedStorage(me.data?.user_id);
      queryClient.clear();
      navigate("/", { replace: true });
    },
  });

  return (
    <div className="v2-shell">
      <aside className="v2-sidebar">
        <span className="v2-wordmark">Career RAG</span>
        <button
          type="button"
          className="v2-btn primary v2-new-chat"
          disabled={createSession.isPending}
          onClick={() => createSession.mutate()}
        >
          <MessageSquarePlus size={17} />
          新的咨询
        </button>
        <ul className="v2-session-list" aria-label="历史会话">
          {(sessions.data?.sessions ?? []).map((item) => (
            <li key={item.session_id}>
              <NavLink
                to={`/app/sessions/${item.session_id}`}
                className={({ isActive }) => (isActive ? "active" : "")}
              >
                {me.data?.user_id
                  ? readSessionTitle(me.data.user_id, item.session_id) ?? `咨询 · ${sessionDateLabel(item.updated_at)}`
                  : `咨询 · ${sessionDateLabel(item.updated_at)}`}
                <span className="v2-session-meta">
                  {item.status} · {sessionDateLabel(item.updated_at)}
                </span>
              </NavLink>
            </li>
          ))}
        </ul>
        {sessions.data ? (
          <p className="v2-quota-usage" aria-label="咨询使用情况">
            已创建{sessions.data.has_more ? "至少 " : " "}{sessions.data.sessions?.length ?? 0} 次咨询
          </p>
        ) : null}
        <div className="v2-sidebar-footer">
          <NavLink to="/app/profile">
            <UserRound size={16} />
            {me.data?.display_name || "我的档案"}
          </NavLink>
          <NavLink to="/app/settings/evaluation">
            <ScrollText size={16} />
            评估（答辩）
          </NavLink>
          <NavLink to="/app/settings/monitoring">
            <BarChart3 size={16} />
            监控（答辩）
          </NavLink>
          <button type="button" onClick={() => logout.mutate()}>
            <LogOut size={16} />
            退出登录
          </button>
        </div>
      </aside>
      <main className="v2-main">
        <Outlet
          context={{
            startNewConsultation: () => createSession.mutate(),
            isCreatingConsultation: createSession.isPending,
          } satisfies AppShellOutletContext}
        />
      </main>
      {quotaOpen ? (
        <div className="v2-modal-backdrop" role="dialog" aria-modal="true" aria-label="额度已用完">
          <div className="v2-modal">
            <h2>咨询额度已用完</h2>
            <p>当前账户的咨询额度已用完。</p>
            <button type="button" className="v2-btn ghost" onClick={() => setQuotaOpen(false)}>
              知道了
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
