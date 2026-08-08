import { useQuery } from "@tanstack/react-query";
import { Database, FileSearch, Layers, MessageSquare, Route, ShieldCheck } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/queries";
import { hasSeenIntro } from "./introSeen";
import "./theme.css";
import "./marketing.css";

const FEATURES = [
  {
    icon: MessageSquare,
    title: "群聊式顾问团队",
    text: "需求顾问、岗位顾问、规划师与项目经理在同一间群聊里协作，过程全程可见。",
  },
  {
    icon: FileSearch,
    title: "简历证据化",
    text: "归一化时逐句保留原文证据片段，每条建议都能指回你的真实经历。",
  },
  {
    icon: Database,
    title: "硬条件数据库过滤",
    text: "已支持的硬条件（地点、签证担保要求、学历、经验等）由数据库过滤；其余偏好参与检索排序。",
  },
  {
    icon: Layers,
    title: "三分层岗位推荐",
    text: "Now Fit 现在就投、Stretch Fit 跳一跳够得着、Bridge Role 迂回积累，各有解释与证据。",
  },
  {
    icon: Route,
    title: "缺口分析与路径规划",
    text: "指出目标岗位与现状之间的差距，给出可执行的技能与经历补齐路线。",
  },
  {
    icon: ShieldCheck,
    title: "项目经理全程督导",
    text: "PM 核查每个阶段的产出质量，信息不足会追问、结果存疑会有界重试。",
  },
];

export function HomePage() {
  const navigate = useNavigate();
  const me = useQuery({ queryKey: ["me"], queryFn: api.me, retry: false });
  const loggedIn = Boolean(me.data);

  // 已登录直达工作台；未登录首次访问先看介绍，看过则直接去登录
  const enterApp = () => {
    if (loggedIn) navigate("/app");
    else if (hasSeenIntro()) navigate("/login");
    else navigate("/welcome");
  };

  return (
    <div className="mk-page">
      <nav className="v2-topnav">
        <span className="v2-wordmark">Career RAG</span>
        <button
          type="button"
          className="v2-btn ghost"
          onClick={() => navigate(loggedIn ? "/app" : "/login")}
        >
          {loggedIn ? "进入工作台" : "登录"}
        </button>
      </nav>

      <header className="mk-hero">
        <p className="mk-eyebrow">SUPERVISOR-GUIDED AGENTIC RAG</p>
        <h1>
          把求职这件事，
          <br />
          交给一支为你服务的团队
        </h1>
        <p className="mk-lede">
          上传简历，和 AI 顾问团队聊清方向，拿到有证据、分层次、可执行的岗位推荐与行动方案。
        </p>
        <div className="mk-cta-row">
          <button type="button" className="v2-btn primary mk-cta" onClick={enterApp}>
            进入应用
          </button>
          <button type="button" className="v2-btn ghost" onClick={() => navigate("/welcome")}>
            了解它如何工作
          </button>
        </div>
      </header>

      <section className="mk-features" aria-label="功能陈列">
        <h2>一套认真对待求职的系统</h2>
        <div className="mk-feature-grid">
          {FEATURES.map(({ icon: Icon, title, text }) => (
            <article key={title} className="mk-feature-card">
              <Icon size={22} aria-hidden />
              <h3>{title}</h3>
              <p>{text}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="mk-steps" aria-label="使用步骤">
        <h2>三步拿到结果</h2>
        <ol>
          <li>
            <strong>上传简历</strong>
            <span>整理经历并保留原文证据</span>
          </li>
          <li>
            <strong>聊清方向</strong>
            <span>确认目标、地点与签证条件</span>
          </li>
          <li>
            <strong>查看结果</strong>
            <span>分层岗位、证据解释与行动建议</span>
          </li>
        </ol>
        <button type="button" className="v2-btn primary mk-cta" onClick={enterApp}>
          进入应用
        </button>
      </section>

      <p className="v2-footnote">毕业设计演示系统 · 演示环境 · 岗位数据含合成演示语料 · 不构成任何求职承诺</p>
    </div>
  );
}
