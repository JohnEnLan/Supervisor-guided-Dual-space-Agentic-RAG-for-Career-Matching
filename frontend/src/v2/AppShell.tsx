import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LogOut, Menu, MessageSquarePlus, ShieldCheck, UserRound, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { ApiError, onUnauthorized } from "../api/client";
import { api } from "../api/queries";
import { LanguageToggle, useLanguage } from "../i18n";
import {
  clearUserScopedStorage,
  readSessionTitle,
  SESSION_TITLE_UPDATED_EVENT,
} from "./localRunStorage";
import { FocusModal } from "./FocusModal";
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
  const { lang, t } = useLanguage();
  const queryClient = useQueryClient();
  const [navigationOpen, setNavigationOpen] = useState(false);
  const navigationTriggerRef = useRef<HTMLButtonElement>(null);
  const navigationDrawerRef = useRef<HTMLElement>(null);
  const navigationCloseRef = useRef<HTMLButtonElement>(null);
  const closeNavigation = useCallback(() => setNavigationOpen(false), []);

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
      navigate("/login", { replace: true });
    });
    return () => onUnauthorized(null);
  }, [me.data?.user_id, navigate, queryClient]);

  useEffect(() => {
    if (me.isError) navigate("/login", { replace: true });
  }, [me.isError, navigate]);

  // 与 WorkbenchPage FocusModal 等价：打开即入焦、Tab 循环、Escape 关闭、关闭后还焦。
  useEffect(() => {
    if (!navigationOpen) return;

    const restoreTo =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : navigationTriggerRef.current;
    const previousBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    navigationCloseRef.current?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeNavigation();
        return;
      }
      if (event.key !== "Tab") return;

      const focusable = Array.from(
        navigationDrawerRef.current?.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      );
      if (!focusable.length) {
        event.preventDefault();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && (active === first || active === navigationDrawerRef.current)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousBodyOverflow;
      queueMicrotask(() => restoreTo?.focus());
    };
  }, [closeNavigation, navigationOpen]);

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
      navigate("/login", { replace: true });
    },
  });

  return (
    <div className="v2-shell">
      <header className="v2-mobile-nav">
        <button
          ref={navigationTriggerRef}
          type="button"
          className="v2-mobile-nav-trigger"
          aria-label={t("打开导航")}
          aria-expanded={navigationOpen}
          aria-controls="v2-primary-navigation"
          onClick={() => setNavigationOpen(true)}
        >
          <Menu size={20} />
        </button>
        <span className="v2-wordmark">Career Arbor</span>
        <LanguageToggle className="v2-lang-mobile" />
      </header>
      {navigationOpen ? (
        <button
          type="button"
          className="v2-drawer-backdrop"
          aria-label={t("关闭导航遮罩")}
          onClick={closeNavigation}
        />
      ) : null}
      <aside
        id="v2-primary-navigation"
        ref={navigationDrawerRef}
        className="v2-sidebar"
        data-open={String(navigationOpen)}
        role={navigationOpen ? "dialog" : undefined}
        aria-modal={navigationOpen ? "true" : undefined}
        aria-label={navigationOpen ? t("主导航") : undefined}
      >
        <div className="v2-sidebar-heading">
          <span className="v2-wordmark">Career Arbor</span>
          <button
            ref={navigationCloseRef}
            type="button"
            className="v2-sidebar-close"
            aria-label={t("关闭导航")}
            onClick={closeNavigation}
          >
            <X size={20} />
          </button>
        </div>
        <button
          type="button"
          className="v2-btn primary v2-new-chat"
          disabled={createSession.isPending}
          onClick={() => {
            closeNavigation();
            createSession.mutate();
          }}
        >
          <MessageSquarePlus size={17} />
          {t("新的咨询")}
        </button>
        <ul className="v2-session-list" aria-label={t("历史会话")}>
          {(sessions.data?.sessions ?? []).map((item) => {
            const fallbackTitle = t("咨询 · {date}", {
              date: sessionDateLabel(item.updated_at),
            });
            return (
              <li key={item.session_id}>
                <NavLink
                  to={`/app/sessions/${item.session_id}`}
                  className={({ isActive }) => (isActive ? "active" : "")}
                  onClick={closeNavigation}
                >
                  {me.data?.user_id
                    ? readSessionTitle(me.data.user_id, item.session_id) ?? fallbackTitle
                    : fallbackTitle}
                  <span className="v2-session-meta">
                    {item.status} · {sessionDateLabel(item.updated_at)}
                  </span>
                </NavLink>
              </li>
            );
          })}
        </ul>
        {sessions.data ? (
          <p className="v2-quota-usage" aria-label={t("咨询使用情况")}>
            {t(
              sessions.data.has_more
                ? "已创建至少 {count} 次咨询"
                : "已创建 {count} 次咨询",
              { count: sessions.data.sessions?.length ?? 0 },
            )}
          </p>
        ) : null}
        <div className="v2-sidebar-footer">
          <NavLink to="/app/profile" onClick={closeNavigation}>
            <UserRound size={16} />
            {me.data?.display_name || t("我的档案")}
          </NavLink>
          {me.data?.is_admin === true ? (
            <NavLink to="/admin" onClick={closeNavigation}>
              <ShieldCheck size={16} />
              {t("管理控制台")}
            </NavLink>
          ) : null}
          <button
            type="button"
            onClick={() => {
              closeNavigation();
              logout.mutate();
            }}
          >
            <LogOut size={16} />
            {t("退出登录")}
          </button>
        </div>
      </aside>
      <main className="v2-main">
        <LanguageToggle className="v2-lang-float" />
        {lang === "en" ? (
          <p className="v2-notice v2-lang-notice">
            {t("Some generated or data-dependent conversation content may remain in Chinese.")}
          </p>
        ) : null}
        <Outlet
          context={{
            startNewConsultation: () => createSession.mutate(),
            isCreatingConsultation: createSession.isPending,
          } satisfies AppShellOutletContext}
        />
      </main>
      {quotaOpen ? (
        <FocusModal label={t("额度已用完")} onClose={() => setQuotaOpen(false)}>
          <h2>{t("咨询额度已用完")}</h2>
          <p>{t("当前账户的咨询额度已用完。")}</p>
          <button type="button" className="v2-btn ghost" onClick={() => setQuotaOpen(false)}>
            {t("知道了")}
          </button>
        </FocusModal>
      ) : null}
    </div>
  );
}
