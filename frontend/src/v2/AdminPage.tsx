import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, ArrowLeft, LayoutDashboard, ShieldCheck, UsersRound } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { api, type Me } from "../api/queries";
import { useLanguage } from "../i18n";
import { AdminDashboard } from "./admin/AdminDashboard";
import { AdminOperations } from "./admin/AdminOperations";
import type { GuardedAdminRequest } from "./admin/types";
import { AdminUsers } from "./admin/AdminUsers";
import "./theme.css";

type AdminSection = "dashboard" | "users" | "evaluation" | "monitoring";

function activeSection(value: string | null): AdminSection {
  if (value === "users" || value === "evaluation" || value === "monitoring") return value;
  return "dashboard";
}

function AdminWorkspace({ me }: { me: Me }) {
  const { t } = useLanguage();
  const [searchParams, setSearchParams] = useSearchParams();
  const section = activeSection(searchParams.get("tab"));
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const guardedRequest: GuardedAdminRequest = useCallback(
    async <T,>(request: () => Promise<T>): Promise<T> => {
      try {
        return await request();
      } catch (error) {
        if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
          queryClient.removeQueries({ queryKey: ["admin"] });
          if (error.status === 401) queryClient.removeQueries({ queryKey: ["me"] });
          navigate(error.status === 401 ? "/login" : "/app", { replace: true });
        }
        throw error;
      }
    },
    [navigate, queryClient],
  );

  const selectSection = (next: AdminSection) => {
    const runId = searchParams.get("runId");
    setSearchParams(
      next === "dashboard"
        ? {}
        : { tab: next, ...(next === "evaluation" && runId ? { runId } : {}) },
    );
  };

  return (
    <div className="v2-admin-shell">
      <header className="v2-admin-header">
        <div>
          <p className="v2-admin-kicker"><ShieldCheck size={15} /> Restricted operations</p>
          <h1>{t("管理控制台")}</h1>
          <p>{t("用量、用户与运行证据的受限管理入口。")}</p>
        </div>
        <div className="v2-admin-identity">
          <span>{me.display_name || t("管理员")}</span>
          <Link to="/app"><ArrowLeft size={15} />{t("返回工作台")}</Link>
        </div>
      </header>
      <nav className="v2-admin-tabs" aria-label={t("管理控制台栏目")}>
        <button type="button" aria-current={section === "dashboard" ? "page" : undefined} onClick={() => selectSection("dashboard")}>
          <LayoutDashboard size={17} />Dashboard
        </button>
        <button type="button" aria-current={section === "users" ? "page" : undefined} onClick={() => selectSection("users")}>
          <UsersRound size={17} />{t("用户")}
        </button>
        <button type="button" aria-current={section === "evaluation" || section === "monitoring" ? "page" : undefined} onClick={() => selectSection("evaluation")}>
          <Activity size={17} />{t("评估与监控")}
        </button>
      </nav>
      <main className="v2-admin-main">
        {section === "dashboard" ? <AdminDashboard request={guardedRequest} /> : null}
        {section === "users" ? <AdminUsers request={guardedRequest} /> : null}
        {section === "evaluation" || section === "monitoring" ? (
          <AdminOperations
            mode={section}
            request={guardedRequest}
            runIdFromUrl={searchParams.get("runId") ?? ""}
            onModeChange={(mode) => {
              const runId = searchParams.get("runId");
              setSearchParams({ tab: mode, ...(runId ? { runId } : {}) });
            }}
            onRunIdChange={(runId) => setSearchParams({ tab: "evaluation", runId })}
          />
        ) : null}
      </main>
    </div>
  );
}

function FreshAdminWorkspace({ me }: { me: Me }) {
  const { t } = useLanguage();
  const queryClient = useQueryClient();
  const [cacheEvicted, setCacheEvicted] = useState(false);

  useEffect(() => {
    queryClient.removeQueries({ queryKey: ["admin"] });
    setCacheEvicted(true);
  }, [queryClient]);

  if (!cacheEvicted) {
    return (
      <main className="v2-admin-gate" role="status" aria-label={t("正在准备管理工作区")}>
        <ShieldCheck size={22} />
        <span>{t("正在准备管理工作区")}</span>
      </main>
    );
  }
  return <AdminWorkspace me={me} />;
}

export function AdminPage() {
  const { t } = useLanguage();
  const me = useQuery({
    queryKey: ["me"],
    queryFn: api.me,
    retry: false,
    staleTime: 0,
    refetchOnMount: "always",
    refetchOnWindowFocus: false,
  });

  if (me.isPending || me.isFetching) {
    return (
      <main className="v2-admin-gate" role="status" aria-label={t("正在验证管理权限")}>
        <ShieldCheck size={22} />
        <span>{t("正在验证管理权限")}</span>
      </main>
    );
  }
  if (me.isError || !me.data) return <Navigate replace to="/login" />;
  if (me.data.is_admin !== true) return <Navigate replace to="/app" />;
  return <FreshAdminWorkspace me={me.data} />;
}
