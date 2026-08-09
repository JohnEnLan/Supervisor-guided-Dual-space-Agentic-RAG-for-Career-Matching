import { useQuery } from "@tanstack/react-query";
import { Activity, AlertTriangle, Coins, TrendingUp } from "lucide-react";

import { api, type AdminOverview } from "../../api/queries";
import { useLanguage } from "../../i18n";
import type { GuardedAdminRequest } from "./types";

type TokenRow = AdminOverview["tokens_by_model"][number];
type Currency = "USD" | "CNY";
type PriceRule =
  | { mode: "split"; inputPerMillion: number; outputPerMillion: number; currency: Currency }
  | { mode: "input"; inputPerMillion: number; currency: Currency }
  | { mode: "total"; totalPerMillion: number; currency: Currency };

const PRICE_VERSION = "估算·价格版本 2026-08";
const MODEL_PRICES: Record<string, PriceRule> = {
  "deepseek-v4-flash": { mode: "split", inputPerMillion: 0.14, outputPerMillion: 0.28, currency: "USD" },
  "deepseek-v4-pro": { mode: "split", inputPerMillion: 0.435, outputPerMillion: 0.87, currency: "USD" },
  "deepseek-chat": { mode: "split", inputPerMillion: 0.14, outputPerMillion: 0.28, currency: "USD" },
  "deepseek-reasoner": { mode: "split", inputPerMillion: 0.14, outputPerMillion: 0.28, currency: "USD" },
  "text-embedding-v4": { mode: "input", inputPerMillion: 0.5, currency: "CNY" },
  "gte-rerank-v2": { mode: "total", totalPerMillion: 0.8, currency: "CNY" },
  "qwen-vl-ocr": { mode: "split", inputPerMillion: 0.3, outputPerMillion: 0.5, currency: "CNY" },
};

function tokens(value: number | null): string {
  return value == null ? "—" : value.toLocaleString("zh-CN");
}

function money(value: number, currency: Currency): string {
  const symbol = currency === "USD" ? "$" : "¥";
  if (value > 0 && value < 0.000001) return `<${symbol}0.000001`;
  return `${symbol}${value.toFixed(6)}`;
}

function estimatedCost(row: TokenRow): string | null {
  const price = MODEL_PRICES[row.model];
  if (!price) return null;
  if (price.mode === "total") {
    return money((row.total_tokens / 1_000_000) * price.totalPerMillion, price.currency);
  }
  if (price.mode === "input") {
    return row.prompt_tokens == null
      ? null
      : money((row.prompt_tokens / 1_000_000) * price.inputPerMillion, price.currency);
  }
  if (row.prompt_tokens == null || row.completion_tokens == null) return null;
  const value =
    (row.prompt_tokens / 1_000_000) * price.inputPerMillion +
    (row.completion_tokens / 1_000_000) * price.outputPerMillion;
  return money(value, price.currency);
}

function priceMode(row: TokenRow): string {
  const price = MODEL_PRICES[row.model];
  if (!price) return "未配置";
  if (price.mode === "total") return "仅 total";
  return price.mode === "input" ? "仅 prompt" : "prompt / completion";
}

function DashboardData({ overview }: { overview: AdminOverview }) {
  const { t } = useLanguage();
  const metrics = [
    ["用户", overview.users_total],
    ["今日登录", overview.logins_today],
    ["7 日登录", overview.logins_7d],
    ["30 日登录", overview.logins_30d],
    ["会话", overview.sessions_total],
    ["咨询轮次", overview.consult_turns_total],
    ["运行", overview.runs_total],
  ] as const;

  return (
    <>
      <div className="v2-admin-metrics">
        {metrics.map(([label, value]) => (
          <article key={label}>
            <span>{t(label)}</span>
            <strong>{value.toLocaleString("zh-CN")}</strong>
          </article>
        ))}
      </div>
      <div className="v2-admin-dashboard-grid">
        <section className="v2-admin-panel">
          <h3><TrendingUp size={18} />{t("每日 Token")}</h3>
          <div className="v2-admin-table-scroll">
            <table>
              <thead><tr><th>{t("UTC 日期")}</th><th>{t("总 Token")}</th></tr></thead>
              <tbody>
                {overview.tokens_by_day.length ? overview.tokens_by_day.map((row) => (
                  <tr key={row.date}><td>{row.date}</td><td>{row.total_tokens.toLocaleString("zh-CN")}</td></tr>
                )) : <tr><td colSpan={2}>{t("暂无用量")}</td></tr>}
              </tbody>
            </table>
          </div>
        </section>
        <section className="v2-admin-panel v2-admin-cost-panel">
          <header>
            <h3><Coins size={18} />{t("模型用量与成本")}</h3>
            <span>{t(PRICE_VERSION)}</span>
          </header>
          <p className="v2-admin-price-note">{t("DeepSeek 输入按缓存未命中价估算；不同币种不跨行合计。")}</p>
          <div className="v2-admin-table-scroll">
            <table>
              <thead><tr><th>{t("模型")}</th><th>Prompt</th><th>Completion</th><th>Total</th><th>{t("计价")}</th><th>{t("估算成本")}</th></tr></thead>
              <tbody>
                {overview.tokens_by_model.length ? overview.tokens_by_model.map((row) => (
                  <tr key={row.model}>
                    <td><code>{row.model}</code></td>
                    <td>{tokens(row.prompt_tokens)}</td>
                    <td>{tokens(row.completion_tokens)}</td>
                    <td>{row.total_tokens.toLocaleString("zh-CN")}</td>
                    <td>{t(priceMode(row))}</td>
                    <td>{estimatedCost(row) ?? t("无法估算")}</td>
                  </tr>
                )) : <tr><td colSpan={6}>{t("暂无模型用量")}</td></tr>}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </>
  );
}

export function AdminDashboard({ request }: { request: GuardedAdminRequest }) {
  const { t } = useLanguage();
  const overview = useQuery({
    queryKey: ["admin", "overview"],
    queryFn: () => request(api.adminOverview),
    retry: false,
  });

  return (
    <section aria-labelledby="admin-dashboard-title">
      <header className="v2-admin-section-heading">
        <div><p>OPERATIONS LEDGER</p><h2 id="admin-dashboard-title">Dashboard</h2></div>
        <span>{t("只读概览")}</span>
      </header>
      {overview.isPending ? (
        <section className="v2-admin-loading" role="status" aria-label={t("正在汇总管理数据")}>
          <Activity className="spin" size={20} /><span>{t("正在汇总管理数据")}</span>
        </section>
      ) : null}
      {overview.isError ? (
        <section className="v2-admin-error" role="alert"><AlertTriangle size={20} /><span>{t("管理概览暂时不可用。")}</span></section>
      ) : null}
      {overview.data ? <DashboardData overview={overview.data} /> : null}
    </section>
  );
}
