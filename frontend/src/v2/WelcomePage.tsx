import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/queries";
import { LanguageToggle, useLanguage } from "../i18n";
import { BrandHomeLink } from "./BrandHomeLink";
import { hasSeenIntro, markIntroSeen } from "./introSeen";
import "./theme.css";
import "./marketing.css";

const SUPERVISOR = {
  key: "pm",
  name: "项目经理",
  layer: "监督层",
  duty: "全程规划、质量核查与有界纠偏",
};

const BUSINESS_TEAM = [
  {
    key: "intent",
    name: "需求顾问",
    stage: "需求确认",
    duty: "听懂你的目标、底线与顾虑，把模糊的想法整理成清晰的方向。",
  },
  {
    key: "scout",
    name: "岗位顾问",
    stage: "岗位检索",
    duty: "在真实岗位库里检索与匹配，每条推荐都附 JD 原文证据。",
  },
  {
    key: "strategist",
    name: "职业规划师",
    stage: "策略规划",
    duty: "分析差距，给出简历修改建议与可执行的成长路径。",
  },
];

export function WelcomePage() {
  const navigate = useNavigate();
  const { t } = useLanguage();
  const containerRef = useRef<HTMLDivElement>(null);

  // A signed-in user without the marker predates the introduction. Backfill it
  // and continue to the workbench; signed-in users who visit explicitly can watch.
  const me = useQuery({ queryKey: ["me"], queryFn: api.me, retry: false });
  useEffect(() => {
    if (me.data && !hasSeenIntro()) {
      markIntroSeen();
      navigate("/app", { replace: true });
    }
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

  // Completing or skipping acknowledges the gate and replaces the history entry.
  // Module memory keeps HomeGate open for this session if localStorage fails.
  const exitIntro = () => {
    markIntroSeen();
    navigate("/", { replace: true });
  };

  return (
    <div className="wl-page" ref={containerRef}>
      <nav className="wl-topbar">
        <BrandHomeLink />
        <div className="wl-topbar-actions">
          <LanguageToggle />
          <button type="button" className="wl-skip" onClick={exitIntro}>
            {t("跳过介绍 →")}
          </button>
        </div>
      </nav>

      <section className="wl-scene wl-ivory wl-opening">
        <div className="wl-inner" data-reveal>
          <p className="mk-eyebrow">{t("欢迎来到枝涯 CAREER ARBOR")}</p>
          <h1>{t("求职不该是一个人的事")}</h1>
          <p className="wl-lede">
            {t("这里有一支为你组建的顾问团队。往下滑，先认识一下他们。")}
          </p>
        </div>
        <div className="wl-scroll-cue" aria-hidden>
          ↓
        </div>
      </section>

      <section className="wl-scene wl-dark">
        <div className="wl-inner">
          <p className="wl-chapter" data-reveal>
            {t("01 · 你的团队")}
          </p>
          <h2 data-reveal>{t("四位顾问，一间群聊")}</h2>
          <p className="wl-lede" data-reveal>
            {t(
              "不是一个黑盒 AI，而是四个分工明确的角色围绕你协作——他们的每句话都在群里，看得见。",
            )}
          </p>
          <div
            className="wl-advisor-system"
            role="group"
            aria-label={t("项目经理监督需求确认、岗位检索与策略规划")}
          >
            <article
              className="wl-team-card wl-supervisor-card"
              data-persona={SUPERVISOR.key}
              data-reveal
            >
              <span className="wl-team-stage">{t(SUPERVISOR.layer)}</span>
              <h3>{t(SUPERVISOR.name)}</h3>
              <p>{t(SUPERVISOR.duty)}</p>
            </article>

            <div className="wl-supervision-bus" aria-hidden="true">
              <span />
              <span />
              <span />
            </div>

            <ol className="wl-team-flow" role="list" aria-label={t("业务顾问交接顺序")}>
              {BUSINESS_TEAM.map((member, index) => (
                <li key={member.key}>
                  <article
                    className="wl-team-card"
                    data-persona={member.key}
                    data-reveal
                    style={{ transitionDelay: `${(index + 1) * 90}ms` }}
                  >
                    <span className="wl-team-stage">{t(member.stage)}</span>
                    <h3>{t(member.name)}</h3>
                    <p>{t(member.duty)}</p>
                  </article>
                </li>
              ))}
            </ol>
          </div>
        </div>
      </section>

      <section className="wl-scene wl-ivory">
        <div className="wl-inner">
          <p className="wl-chapter" data-reveal>
            {t("02 · 证据先行")}
          </p>
          <h2 data-reveal>{t("每一句建议，都指得回你的真实经历")}</h2>
          <p className="wl-lede" data-reveal>
            {t(
              "简历会被整理成结构化档案，同时逐句保留原文证据。顾问引用你的经历时标注出处， 缺关键信息时会先向你确认——不编造、不脑补。",
            )}
          </p>
          <figure className="wl-evidence" data-reveal>
            <blockquote>
              {t("C001 · 「独立完成部门数据看板搭建，支撑三个业务组的日常决策」")}
            </blockquote>
            <figcaption>{t("↳ 被引用于「数据分析师（Now Fit）」的匹配解释")}</figcaption>
          </figure>
        </div>
      </section>

      <section className="wl-scene wl-warm">
        <div className="wl-inner">
          <p className="wl-chapter" data-reveal>
            {t("03 · 双空间检索")}
          </p>
          <h2 data-reveal>{t("硬条件交给数据库，语义交给向量")}</h2>
          <p className="wl-lede" data-reveal>
            {t(
              '签证、地点、学历这类底线由数据库直接过滤；关键词与语义两路并行检索、融合重排， 兼顾"写了什么"与"意味着什么"。',
            )}
          </p>
          <div className="wl-tiers" data-reveal>
            <span data-tier="now">{t("Now Fit · 现在就投")}</span>
            <span data-tier="stretch">{t("Stretch Fit · 跳一跳够得着")}</span>
            <span data-tier="bridge">{t("Bridge Role · 迂回积累")}</span>
          </div>
        </div>
      </section>

      <section className="wl-scene wl-dark">
        <div className="wl-inner">
          <p className="wl-chapter" data-reveal>
            {t("04 · 全程督导")}
          </p>
          <h2 data-reveal>{t("过程透明，质量有人把关")}</h2>
          <p className="wl-lede" data-reveal>
            {t(
              "项目经理核查每个阶段的产出：信息不足会追问、结果存疑会重查；重试有上限，进度看得见。",
            )}
          </p>
        </div>
      </section>

      <section className="wl-scene wl-ivory wl-final">
        <div className="wl-inner" data-reveal>
          <h2>{t("准备好了吗？")}</h2>
          <p className="wl-lede">
            {t(
              me.data
                ? "随时可以从首页顶栏进入工作台继续。"
                : "验证码登录，首次登录自动创建账号。",
            )}
          </p>
          <div className="mk-cta-row">
            <button type="button" className="v2-btn primary mk-cta" onClick={exitIntro}>
              {t(me.data ? "返回首页" : "进入枝涯")}
            </button>
          </div>
          <p className="v2-footnote">{t("此介绍只在首次进入时展示")}</p>
        </div>
      </section>
    </div>
  );
}
