import { useQuery } from "@tanstack/react-query";
import { LoaderCircle } from "lucide-react";

import { api } from "../api/queries";
import "./theme.css";

export function ProfilePage() {
  const me = useQuery({ queryKey: ["me"], queryFn: api.me });
  const profile = useQuery({ queryKey: ["me-profile"], queryFn: api.meProfile });

  if (me.isPending || profile.isPending) {
    return (
      <section className="v2-profile">
        <p className="v2-inline-loading">
          <LoaderCircle className="spin" size={16} /> 读取档案…
        </p>
      </section>
    );
  }

  const remembered = profile.data?.profile ?? null;
  const hasProfile = remembered && Object.keys(remembered).length > 0;

  return (
    <section className="v2-profile">
      <h1>我的档案</h1>
      <p className="v2-profile-sub">
        账号：{me.data?.display_name || me.data?.user_id.slice(0, 8)} · 状态 {me.data?.status} ·
        注册于 {me.data ? new Date(me.data.created_at).toLocaleDateString() : "—"}
      </p>

      <h2>记忆画像</h2>
      <p className="v2-profile-sub">
        确认 Match Brief 时系统会记住你的职业画像，下次咨询自动作为起点（仅作草稿呈现，需你确认后才生效）。
      </p>
      {hasProfile ? (
        <pre className="v2-profile-json">{JSON.stringify(remembered, null, 2)}</pre>
      ) : (
        <p className="v2-profile-sub">还没有画像——完成一次咨询并确认 Brief 后就有了。</p>
      )}
    </section>
  );
}
