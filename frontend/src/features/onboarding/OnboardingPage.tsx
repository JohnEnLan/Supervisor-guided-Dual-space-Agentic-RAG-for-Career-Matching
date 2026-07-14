import {
  ArrowLeft,
  ArrowRight,
  BadgeCheck,
  BriefcaseBusiness,
  Building2,
  Database,
  FileText,
  Search,
  ShieldCheck,
  Sparkles,
  Target,
  Users,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

type ScreenKind = "evidence" | "agents" | "trust";

type IntroScreen = {
  eyebrow: string;
  title: string;
  description: string;
  kind: ScreenKind;
};

const SCREENS: readonly IntroScreen[] = [
  {
    eyebrow: "Evidence-grounded career matching",
    title: "让职业匹配成为有证据的职业决策",
    description:
      "系统从真实简历经历出发，对照岗位原文，给出可核查的推荐、能力缺口与下一步职业路径。",
    kind: "evidence",
  },
  {
    eyebrow: "Supervisor-guided agentic workflow",
    title: "三位 Agent 协作，Supervisor 守住边界",
    description:
      "Intent Agent 先确认目标，Matching Agent 检索岗位，Strategy Agent 规划行动；Supervisor 负责约束、证据与有界恢复。",
    kind: "agents",
  },
  {
    eyebrow: "Dual-space, explained",
    title: "每一条推荐都可信、可解释",
    description:
      "岗位证据与匿名案例证据分开呈现。案例只能重排已有候选，不能绕过地点、签证或岗位状态等硬约束。",
    kind: "trust",
  },
];

export function OnboardingPage() {
  const [step, setStep] = useState(0);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const screen = SCREENS[step];

  useEffect(() => {
    titleRef.current?.focus();
  }, [step]);

  return (
    <main className="onboarding-shell">
      <header className="onboarding-header">
        <span className="onboarding-brand">
          <span className="onboarding-brand-mark" aria-hidden="true">
            <BriefcaseBusiness size={20} />
          </span>
          <span>
            <strong>Career RAG</strong>
            <small>职业证据实验台</small>
          </span>
        </span>
        <Link className="button onboarding-skip" to="/workspace">
          跳过介绍
          <ArrowRight size={17} aria-hidden="true" />
        </Link>
      </header>

      <section className="onboarding-stage" data-step={step + 1}>
        <div className="onboarding-copy">
          <p className="onboarding-index" aria-hidden="true">
            0{step + 1} / 03
          </p>
          <p className="eyebrow">{screen.eyebrow}</p>
          <h1 ref={titleRef} tabIndex={-1}>
            {screen.title}
          </h1>
          <p className="onboarding-lead">{screen.description}</p>

          <div className="onboarding-actions">
            {step > 0 ? (
              <button
                className="secondary"
                type="button"
                onClick={() => setStep((current) => current - 1)}
              >
                <ArrowLeft size={18} aria-hidden="true" />
                上一页
              </button>
            ) : null}

            {step < SCREENS.length - 1 ? (
              <button
                className="primary"
                type="button"
                onClick={() => setStep((current) => current + 1)}
              >
                {step === 0 ? "了解它如何工作" : "继续了解"}
                <ArrowRight size={18} aria-hidden="true" />
              </button>
            ) : (
              <Link className="button primary" to="/workspace">
                进入职业匹配工作台
                <ArrowRight size={18} aria-hidden="true" />
              </Link>
            )}
          </div>
        </div>

        <OnboardingVisual kind={screen.kind} />
      </section>

      <footer className="onboarding-footer">
        <ol aria-label="介绍进度">
          {SCREENS.map((item, index) => (
            <li
              key={item.kind}
              aria-current={index === step ? "step" : undefined}
            >
              <span>0{index + 1}</span>
              {index === 0 ? "用途" : index === 1 ? "协作" : "可信"}
            </li>
          ))}
        </ol>
        <p className="onboarding-announcement" aria-live="polite">
          第 {step + 1} 页，共 {SCREENS.length} 页
        </p>
      </footer>
    </main>
  );
}

function OnboardingVisual({ kind }: { kind: ScreenKind }) {
  if (kind === "evidence") {
    return (
      <div
        className="intro-visual evidence-relay"
        role="img"
        aria-label="简历证据经过检索后连接到有依据的岗位推荐"
      >
        <article className="relay-card resume-card">
          <span className="visual-label">Resume evidence</span>
          <FileText aria-hidden="true" />
          <strong>Python · SQL</strong>
          <small>“Built a matching benchmark”</small>
        </article>
        <span className="relay-line line-one" aria-hidden="true" />
        <span className="relay-node search-node" aria-hidden="true">
          <Search />
        </span>
        <span className="relay-line line-two" aria-hidden="true" />
        <article className="relay-card result-card">
          <span className="visual-label">Verified recommendation</span>
          <BadgeCheck aria-hidden="true" />
          <strong>Data Analyst</strong>
          <small>JD evidence attached</small>
        </article>
      </div>
    );
  }

  if (kind === "agents") {
    return (
      <div
        className="intro-visual agent-orbit"
        role="img"
        aria-label="Intent、Matching 和 Strategy Agent 由 Supervisor 监督"
      >
        <article className="agent-node intent-node">
          <Target aria-hidden="true" />
          <strong>Intent</strong>
          <small>确认目标</small>
        </article>
        <article className="agent-node matching-node">
          <Search aria-hidden="true" />
          <strong>Matching</strong>
          <small>检索证据</small>
        </article>
        <article className="agent-node strategy-node">
          <Users aria-hidden="true" />
          <strong>Strategy</strong>
          <small>规划行动</small>
        </article>
        <article className="supervisor-node">
          <ShieldCheck aria-hidden="true" />
          <strong>Supervisor</strong>
          <small>核查边界</small>
        </article>
        <span className="orbit-ring" aria-hidden="true" />
      </div>
    );
  }

  return (
    <div
      className="intro-visual trust-ledger"
      role="img"
      aria-label="显式岗位空间与匿名案例空间经过硬约束门后生成可解释推荐"
    >
      <article className="space-card explicit-space">
        <Building2 aria-hidden="true" />
        <span>
          <small>显式岗位空间</small>
          <strong>JD + hard filters</strong>
        </span>
      </article>
      <article className="space-card implicit-space">
        <Database aria-hidden="true" />
        <span>
          <small>匿名案例空间</small>
          <strong>Case evidence</strong>
        </span>
      </article>
      <div className="trust-gate">
        <ShieldCheck aria-hidden="true" />
        <span>
          <small>Supervisor gate</small>
          <strong>约束通过 · 证据齐全</strong>
        </span>
      </div>
      <div className="trust-output">
        <Sparkles aria-hidden="true" />
        <span>
          <small>Public result</small>
          <strong>推荐理由可追溯</strong>
        </span>
      </div>
    </div>
  );
}
