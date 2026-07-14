import { useQuery } from "@tanstack/react-query";
import { Activity, BriefcaseBusiness, Gauge, ShieldCheck } from "lucide-react";
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { NavLink, Outlet } from "react-router-dom";

import { api } from "../api/queries";
import { ProgressBoard, type FlowStage } from "./ProgressBoard";

type ProgressState = {
  activeStage: FlowStage;
  completedStages: string[];
  totalStages: number;
};

type ProgressContextValue = ProgressState & {
  setProgress: (state: Partial<ProgressState>) => void;
};

const ProgressContext = createContext<ProgressContextValue | null>(null);

export function useFlowProgress(): ProgressContextValue {
  const context = useContext(ProgressContext);
  if (!context) {
    throw new Error("useFlowProgress must be used inside App.");
  }
  return context;
}

export function App() {
  const [progress, setProgressState] = useState<ProgressState>({
    activeStage: "resume",
    completedStages: [],
    totalStages: 7,
  });
  const setProgress = useCallback((next: Partial<ProgressState>) => {
    setProgressState((current) => {
      const merged = { ...current, ...next };
      const sameStages = merged.completedStages.length === current.completedStages.length
        && merged.completedStages.every((stage, index) => stage === current.completedStages[index]);
      return merged.activeStage === current.activeStage
        && merged.totalStages === current.totalStages
        && sameStages
        ? current
        : merged;
    });
  }, []);
  const capabilities = useQuery({ queryKey: ["capabilities"], queryFn: api.capabilities });
  const value = useMemo<ProgressContextValue>(
    () => ({
      ...progress,
      setProgress,
    }),
    [progress, setProgress],
  );

  return (
    <ProgressContext.Provider value={value}>
      <div className="app-shell">
        <header className="topbar">
          <NavLink className="brand" to="/" aria-label="Career RAG 工作台首页">
            <span className="brand-mark"><BriefcaseBusiness size={20} /></span>
            <span><strong>Career RAG</strong><small>双空间职业匹配工作台</small></span>
          </NavLink>
          <nav aria-label="主导航">
            <NavLink to="/workspace"><Gauge size={18} />开始匹配</NavLink>
            {capabilities.data?.monitoring_enabled ? (
              <NavLink to="/monitoring"><Activity size={18} />运行监控</NavLink>
            ) : null}
          </nav>
          <span className="system-state"><ShieldCheck size={16} />证据约束已启用</span>
        </header>
        <main className="workspace">
          <ProgressBoard
            completedStages={progress.completedStages}
            activeStage={progress.activeStage}
            totalStages={progress.totalStages}
          />
          <div className="page-surface"><Outlet /></div>
        </main>
        <footer>研究原型 · 推荐依据可追溯 · 不展示录用概率</footer>
      </div>
    </ProgressContext.Provider>
  );
}

export function RouteError() {
  return (
    <section className="empty-state" role="alert">
      <p className="eyebrow">页面恢复</p>
      <h1>这个页面暂时无法显示</h1>
      <p>请返回首页重新进入流程；已经保存到服务器的运行不会丢失。</p>
      <NavLink className="button primary" to="/">返回首页</NavLink>
    </section>
  );
}

export function PlaceholderPage({ title, children }: { title: string; children?: ReactNode }) {
  return <section><p className="eyebrow">Career RAG</p><h1>{title}</h1>{children}</section>;
}
