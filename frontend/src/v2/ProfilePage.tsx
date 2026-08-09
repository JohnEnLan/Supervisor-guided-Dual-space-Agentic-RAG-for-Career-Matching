import { useQuery } from "@tanstack/react-query";
import { LoaderCircle } from "lucide-react";

import { api } from "../api/queries";
import { useLanguage } from "../i18n";
import "./theme.css";

export function ProfilePage() {
  const { t } = useLanguage();
  const me = useQuery({ queryKey: ["me"], queryFn: api.me });
  const profile = useQuery({ queryKey: ["me-profile"], queryFn: api.meProfile });

  if (me.isPending || profile.isPending) {
    return (
      <section className="v2-profile">
        <p className="v2-inline-loading">
          <LoaderCircle className="spin" size={16} /> {t("读取档案…")}
        </p>
      </section>
    );
  }

  if (me.isError || profile.isError) {
    return (
      <section className="v2-profile">
        <h1>{t("我的档案")}</h1>
        <p className="v2-error">{t("画像加载失败，请重试")}</p>
        <button
          type="button"
          className="v2-btn ghost"
          disabled={me.isFetching || profile.isFetching}
          onClick={() => void Promise.all([me.refetch(), profile.refetch()])}
        >
          {me.isFetching || profile.isFetching ? t("重试中…") : t("重试加载画像")}
        </button>
      </section>
    );
  }

  const remembered = profile.data?.profile ?? null;
  const hasProfile = remembered && Object.keys(remembered).length > 0;

  return (
    <section className="v2-profile">
      <h1>{t("我的档案")}</h1>
      <p className="v2-profile-sub">
        {t("账号：{account} · 状态 {status} · 注册于 {date}", {
          account: me.data?.display_name || me.data?.user_id.slice(0, 8) || "—",
          status: me.data?.status ?? "—",
          date: me.data ? new Date(me.data.created_at).toLocaleDateString() : "—",
        })}
      </p>

      <h2>{t("记忆画像")}</h2>
      <p className="v2-profile-sub">
        {t("确认 Match Brief 时系统会记住你的职业画像，下次咨询自动作为起点（仅作草稿呈现，需你确认后才生效）。")}
      </p>
      {hasProfile ? (
        <pre className="v2-profile-json">{JSON.stringify(remembered, null, 2)}</pre>
      ) : (
        <p className="v2-profile-sub">{t("还没有画像——完成一次咨询并确认 Brief 后就有了。")}</p>
      )}
    </section>
  );
}
