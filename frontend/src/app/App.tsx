import { AlertTriangle } from "lucide-react";
import { Link, useRouteError } from "react-router-dom";

import { useLanguage } from "../i18n";

export function RouteError() {
  const error = useRouteError();
  const { t } = useLanguage();
  const message =
    error instanceof Error ? error.message : t("页面出现了一个意外错误。");
  return (
    <section className="notice error" role="alert" style={{ margin: 40 }}>
      <AlertTriangle />
      <div>
        <h1>{t("出错了")}</h1>
        <p>{message}</p>
        <Link className="button secondary" to="/">
          {t("返回首页")}
        </Link>
      </div>
    </section>
  );
}
