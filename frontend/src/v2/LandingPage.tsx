import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { ApiError } from "../api/client";
import { api } from "../api/queries";
import "./theme.css";

type Channel = "email" | "phone";

const CHANNEL_META: Record<Channel, { label: string; placeholder: string; inputLabel: string }> = {
  email: { label: "邮箱验证码", placeholder: "you@example.com", inputLabel: "邮箱地址" },
  phone: { label: "手机验证码", placeholder: "+8613800000000", inputLabel: "手机号（含国家码）" },
};

export function LandingPage() {
  const navigate = useNavigate();
  const [channel, setChannel] = useState<Channel>("email");
  const [target, setTarget] = useState("");
  const [code, setCode] = useState("");
  const [cooldown, setCooldown] = useState(0);

  // 已登录则直接进入工作台
  const me = useQuery({ queryKey: ["me"], queryFn: api.me, retry: false });
  useEffect(() => {
    if (me.data) navigate("/app", { replace: true });
  }, [me.data, navigate]);

  // 服务端可能禁用某个 OTP 通道（如 production 未接短信网关）：
  // 只展示可用通道的 tab；接口不可达时退化为全部展示
  const capabilities = useQuery({ queryKey: ["capabilities"], queryFn: api.capabilities });
  const enabledChannels = (
    capabilities.data?.otp_channels?.length
      ? capabilities.data.otp_channels
      : (Object.keys(CHANNEL_META) as Channel[])
  ) as Channel[];
  useEffect(() => {
    if (!enabledChannels.includes(channel)) setChannel(enabledChannels[0]);
  }, [enabledChannels.join(","), channel]);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setInterval(() => setCooldown((s) => s - 1), 1000);
    return () => clearInterval(timer);
  }, [cooldown > 0]);

  const request = useMutation({
    mutationFn: () => api.otpRequest({ channel, target: target.trim() }),
    onSuccess: () => setCooldown(60),
  });
  const verify = useMutation({
    mutationFn: () => api.otpVerify({ channel, target: target.trim(), code: code.trim() }),
    onSuccess: () => navigate("/app", { replace: true }),
  });

  const errorText = (error: unknown): string => {
    if (error instanceof ApiError) {
      if (error.status === 401) return "验证码不正确或已过期，请重试。";
      if (error.status === 429) return "请求太频繁，请稍后再试。";
      return error.message;
    }
    return "网络异常，请重试。";
  };

  return (
    <div className="v2-landing">
      <nav className="v2-topnav">
        <span className="v2-wordmark">Career RAG</span>
        <Link className="v2-back-home" to="/">
          ← 返回首页
        </Link>
      </nav>
      <main className="v2-hero">
        <section>
          <h1>把求职这件事，交给一支为你服务的团队</h1>
          <p className="lede">
            上传简历，和你的职业顾问团队聊清楚方向。需求顾问、岗位顾问、规划师与项目经理在一个群里协作——
            每一条推荐都有 JD 原文证据，每一条简历建议都指回你的真实经历。
          </p>
          <ul className="v2-hero-points">
            <li>已支持的硬条件（地点、签证担保要求、学历、经验等）由数据库过滤；其余偏好参与检索排序</li>
            <li>多轮启发式咨询：从明确目标到探索方向都被认真对待</li>
            <li>全程可解释：分层推荐、证据溯源、过程透明</li>
          </ul>
        </section>
        <section className="v2-login-card" aria-label="登录">
          <h2>开始使用</h2>
          <p className="hint">验证码登录，首次登录自动创建账号</p>
          <div className="v2-tabs" role="tablist">
            {enabledChannels.map((key) => (
              <button
                key={key}
                role="tab"
                aria-selected={channel === key}
                onClick={() => {
                  setChannel(key);
                  request.reset();
                  verify.reset();
                }}
              >
                {CHANNEL_META[key].label}
              </button>
            ))}
          </div>
          <div className="v2-field">
            <label htmlFor="login-target">{CHANNEL_META[channel].inputLabel}</label>
            <input
              id="login-target"
              value={target}
              placeholder={CHANNEL_META[channel].placeholder}
              autoComplete={channel === "email" ? "email" : "tel"}
              onChange={(event) => setTarget(event.target.value)}
            />
          </div>
          <div className="v2-field">
            <label htmlFor="login-code">验证码</label>
            <div className="v2-otp-row">
              <input
                id="login-code"
                value={code}
                placeholder="6 位数字"
                inputMode="numeric"
                maxLength={6}
                onChange={(event) => setCode(event.target.value)}
              />
              <button
                type="button"
                className="v2-btn ghost"
                disabled={!target.trim() || cooldown > 0 || request.isPending}
                onClick={() => request.mutate()}
              >
                {cooldown > 0 ? `${cooldown}s` : "获取验证码"}
              </button>
            </div>
          </div>
          <button
            type="button"
            className="v2-btn primary"
            disabled={!target.trim() || code.trim().length < 6 || verify.isPending}
            onClick={() => verify.mutate()}
          >
            {verify.isPending ? "登录中…" : "登录 / 注册"}
          </button>
          {request.isSuccess ? <p className="v2-notice">验证码已发送，5 分钟内有效。</p> : null}
          {request.isError ? <p className="v2-error">{errorText(request.error)}</p> : null}
          {verify.isError ? <p className="v2-error">{errorText(verify.error)}</p> : null}
        </section>
      </main>
      <p className="v2-footnote">演示环境 · 岗位数据含合成演示语料 · 不构成任何求职承诺</p>
    </div>
  );
}
