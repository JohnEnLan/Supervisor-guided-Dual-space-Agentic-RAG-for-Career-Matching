import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BarChart3, LogOut, MessageSquarePlus, ScrollText, UserRound } from "lucide-react";
import { useEffect } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { onUnauthorized } from "../api/client";
import { api } from "../api/queries";
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
      queryClient.clear();
      navigate("/", { replace: true });
    });
    return () => onUnauthorized(null);
  }, [navigate, queryClient]);

  useEffect(() => {
    if (me.isError) navigate("/", { replace: true });
  }, [me.isError, navigate]);

  const createSession = useMutation({
    mutationFn: () => api.createSession({}),
    onSuccess: (session) => {
      void queryClient.invalidateQueries({ queryKey: ["me-sessions"] });
      navigate(`/app/sessions/${session.session_id}`);
    },
  });

  const logout = useMutation({
    mutationFn: api.logout,
    onSettled: () => {
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
    </div>
  );
}
