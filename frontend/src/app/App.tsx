import { AlertTriangle } from "lucide-react";
import { Link, useRouteError } from "react-router-dom";

export function RouteError() {
  const error = useRouteError();
  const message =
    error instanceof Error ? error.message : "页面出现了一个意外错误。";
  return (
    <section className="notice error" role="alert" style={{ margin: 40 }}>
      <AlertTriangle />
      <div>
        <h1>出错了</h1>
        <p>{message}</p>
        <Link className="button secondary" to="/">
          返回首页
        </Link>
      </div>
    </section>
  );
}
