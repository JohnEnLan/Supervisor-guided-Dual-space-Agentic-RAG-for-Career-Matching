import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BarChart3, LogOut, MessageSquarePlus, ScrollText, Sparkles, UserRound } from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { ApiError, onUnauthorized } from "../api/client";
import { api } from "../api/queries";
import { clearLastRuns } from "./localRunStorage";
import "./theme.css";

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
      clearLastRuns(me.data?.user_id);
      queryClient.clear();
      navigate("/", { replace: true });
    });
    return () => onUnauthorized(null);
  }, [me.data?.user_id, navigate, queryClient]);

  useEffect(() => {
    if (me.isError) navigate("/", { replace: true });
  }, [me.isError, navigate]);

  const [quotaOpen, setQuotaOpen] = useState(false);
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
      clearLastRuns(me.data?.user_id);
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
                {`会话 ${item.session_id.slice(0, 8)}`}
                <span className="v2-session-meta">
                  {item.status} · {new Date(item.updated_at).toLocaleDateString()}
                </span>
              </NavLink>
            </li>
          ))}
        </ul>
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
        <Outlet />
      </main>
      {quotaOpen ? (
        <div className="v2-modal-backdrop" role="dialog" aria-modal="true" aria-label="额度已用完">
          <div className="v2-modal">
            <h2>咨询额度已用完</h2>
            <p>
              每个账号包含 3 次完整咨询。你的额度已全部使用，升级后可继续创建新的咨询会话。
            </p>
            <div className="v2-modal-actions">
              <button
                type="button"
                className="v2-btn primary"
                onClick={() => {
                  /* 支付流程尚未接入：按钮先占位 */
                }}
              >
                <Sparkles size={16} />
                升级额度（¥9.9 起）
              </button>
              <button type="button" className="v2-btn ghost" onClick={() => setQuotaOpen(false)}>
                稍后再说
              </button>
            </div>
            <p className="v2-footnote">支付功能即将上线，目前仅为演示占位。</p>
          </div>
        </div>
      ) : null}
    </div>
  );
}
