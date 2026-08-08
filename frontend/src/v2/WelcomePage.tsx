import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/queries";
import { markIntroSeen } from "./introSeen";
import "./theme.css";
import "./marketing.css";

const TEAM = [
  {
    key: "intent",
    name: "需求顾问",
    duty: "听懂你的目标、底线与顾虑，把模糊的想法整理成清晰的方向。",
  },
  {
    key: "scout",
    name: "岗位顾问",
    duty: "在真实岗位库里检索与匹配，每条推荐都附 JD 原文证据。",
  },
  {
    key: "strategist",
    name: "职业规划师",
    duty: "分析差距，给出简历修改建议与可执行的成长路径。",
  },
  {
    key: "pm",
    name: "项目经理",
    duty: "把关每一步产出的质量与节奏，全程督导，不放任流程跑偏。",
  },
];

export function WelcomePage() {
  const navigate = useNavigate();
  const containerRef = useRef<HTMLDivElement>(null);

  // 已登录用户不看介绍，直接进工作台
  const me = useQuery({ queryKey: ["me"], queryFn: api.me, retry: false });
  useEffect(() => {
    if (me.data) navigate("/app", { replace: true });
  }, [me.data, navigate]);

  // 滚动渐显；环境不支持 IntersectionObserver 时全部直接可见
  useEffect(() => {
    const root = containerRef.current;
    if (!root) return;
    const targets = Array.from(root.querySelectorAll("[data-reveal]"));
    if (typeof IntersectionObserver === "undefined") {
      targets.forEach((target) => target.setAttribute("data-visible", "true"));
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          entry.target.setAttribute("data-visible", "true");
          observer.unobserve(entry.target);
        }
      },
      { threshold: 0.18 },
    );
    targets.forEach((target) => observer.observe(target));
    return () => observer.disconnect();
  }, []);

  const toLogin = () => {
    markIntroSeen();
    navigate("/login");
  };

  return (
    <div className="wl-page" ref={containerRef}>
      <nav className="wl-topbar">
        <span className="v2-wordmark">Career RAG</span>
        <button type="button" className="wl-skip" onClick={toLogin}>
          跳过介绍 →
        </button>
      </nav>

      <section className="wl-scene wl-ivory wl-opening">
        <div className="wl-inner" data-reveal>
          <p className="mk-eyebrow">欢迎来到 CAREER RAG</p>
          <h1>求职不该是一个人的事</h1>
          <p className="wl-lede">这里有一支为你组建的顾问团队。往下滑，先认识一下他们。</p>
        </div>
        <div className="wl-scroll-cue" aria-hidden>
          ↓
        </div>
      </section>

      <section className="wl-scene wl-dark">
        <div className="wl-inner">
          <p className="wl-chapter" data-reveal>
            01 · 你的团队
          </p>
          <h2 data-reveal>四位顾问，一间群聊</h2>
          <p className="wl-lede" data-reveal>
            不是一个黑盒 AI，而是四个分工明确的角色围绕你协作——他们的每句话都在群里，看得见。
          </p>
          <div className="wl-team-grid">
            {TEAM.map((member, index) => (
              <article
                key={member.key}
                className="wl-team-card"
                data-persona={member.key}
                data-reveal
                style={{ transitionDelay: `${index * 90}ms` }}
              >
                <h3>{member.name}</h3>
                <p>{member.duty}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="wl-scene wl-ivory">
        <div className="wl-inner">
          <p className="wl-chapter" data-reveal>
            02 · 证据先行
          </p>
          <h2 data-reveal>每一句建议，都指得回你的真实经历</h2>
          <p className="wl-lede" data-reveal>
            简历会被整理成结构化档案，同时逐句保留原文证据。顾问引用你的经历时标注出处，
            缺关键信息时会先向你确认——不编造、不脑补。
          </p>
          <figure className="wl-evidence" data-reveal>
            <blockquote>C001 · 「独立完成部门数据看板搭建，支撑三个业务组的日常决策」</blockquote>
            <figcaption>↳ 被引用于「数据分析师（Now Fit）」的匹配解释</figcaption>
          </figure>
        </div>
      </section>

      <section className="wl-scene wl-warm">
        <div className="wl-inner">
          <p className="wl-chapter" data-reveal>
            03 · 双空间检索
          </p>
          <h2 data-reveal>硬条件交给数据库，语义交给向量</h2>
          <p className="wl-lede" data-reveal>
            签证、地点、学历这类底线由数据库直接过滤；关键词与语义两路并行检索、融合重排，
            兼顾"写了什么"与"意味着什么"。
          </p>
          <div className="wl-tiers" data-reveal>
            <span data-tier="now">Now Fit · 现在就投</span>
            <span data-tier="stretch">Stretch Fit · 跳一跳够得着</span>
            <span data-tier="bridge">Bridge Role · 迂回积累</span>
          </div>
        </div>
      </section>

      <section className="wl-scene wl-dark">
        <div className="wl-inner">
          <p className="wl-chapter" data-reveal>
            04 · 全程督导
          </p>
          <h2 data-reveal>过程透明，质量有人把关</h2>
          <p className="wl-lede" data-reveal>
            项目经理核查每个阶段的产出：信息不足会追问、结果存疑会重查；重试有上限，进度看得见。
          </p>
        </div>
      </section>

      <section className="wl-scene wl-ivory wl-final">
        <div className="wl-inner" data-reveal>
          <h2>准备好了吗？</h2>
          <p className="wl-lede">验证码登录，首次登录自动创建账号。</p>
          <div className="mk-cta-row">
            <button type="button" className="v2-btn primary mk-cta" onClick={toLogin}>
              开始使用
            </button>
          </div>
          <p className="v2-footnote">此介绍只在首次进入时展示</p>
        </div>
      </section>
    </div>
  );
}
