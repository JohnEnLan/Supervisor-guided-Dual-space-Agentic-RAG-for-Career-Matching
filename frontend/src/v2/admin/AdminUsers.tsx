import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ChevronDown, ChevronUp, RotateCcw, UsersRound } from "lucide-react";
import { useState } from "react";

import { api, type AdminUserResume } from "../../api/queries";
import type { GuardedAdminRequest } from "./types";

function dateTime(value: string | null): string {
  return value ? new Intl.DateTimeFormat("zh-CN", { dateStyle: "short", timeStyle: "short" }).format(new Date(value)) : "—";
}

function resumeValue(value: string | null): string {
  return value ?? "未上传";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function ContactSummary({ resume }: { resume: AdminUserResume }) {
  const contact = isRecord(resume.resume_state?.contact) ? resume.resume_state.contact : {};
  const fields = [
    ["姓名", contact.name],
    ["电话", contact.phone],
    ["邮箱", contact.email],
  ] as const;
  return (
    <dl className="v2-admin-resume-contact">
      {fields.map(([label, value]) => (
        <div key={label}><dt>{label}</dt><dd>{typeof value === "string" ? value : "—"}</dd></div>
      ))}
    </dl>
  );
}

function ResumeDetail({ id, userId, request }: { id: string; userId: string; request: GuardedAdminRequest }) {
  const resume = useQuery({
    queryKey: ["admin", "user-resume", userId],
    queryFn: () => request(() => api.adminUserResume(userId)),
    retry: false,
  });
  if (resume.isPending) return <section className="v2-admin-inline-state" role="status">正在读取简历</section>;
  if (resume.isError) return <section className="v2-admin-error" role="alert">简历读取失败。</section>;
  return (
    <section id={id} className="v2-admin-resume" aria-label="简历详情">
      <header><div><span>用户</span><code>{resume.data.user_id}</code></div><div><span>会话</span><code>{resume.data.session_id ?? "—"}</code></div></header>
      <h3>联系人</h3>
      <ContactSummary resume={resume.data} />
      <h3>resume_state 原始 JSON</h3>
      <pre>{JSON.stringify(resume.data.resume_state, null, 2)}</pre>
    </section>
  );
}

export function AdminUsers({ request }: { request: GuardedAdminRequest }) {
  const [page, setPage] = useState(1);
  const [expandedUserId, setExpandedUserId] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const users = useQuery({
    queryKey: ["admin", "users", page],
    queryFn: () => request(() => api.adminUsers(page)),
    retry: false,
  });
  const reset = useMutation({
    mutationFn: async (userId: string) => {
      const resume = await queryClient.fetchQuery({
        queryKey: ["admin", "user-resume", userId],
        queryFn: () => request(() => api.adminUserResume(userId)),
        staleTime: 0,
      });
      if (!resume.session_id) throw new Error("该用户没有可重置的简历会话。");
      return request(() => api.adminResetParseCount(resume.session_id!));
    },
  });

  return (
    <section aria-labelledby="admin-users-title">
      <header className="v2-admin-section-heading">
        <div><p>ACCOUNT DIRECTORY</p><h2 id="admin-users-title">用户</h2></div>
        <span>{users.data ? `第 ${users.data.page} 页 · 每页 ${users.data.page_size} 条` : "每页 20 条"}</span>
      </header>
      {users.isPending ? <section className="v2-admin-loading" role="status"><UsersRound size={20} />正在读取用户</section> : null}
      {users.isError ? <section className="v2-admin-error" role="alert"><AlertTriangle size={20} />用户数据暂时不可用。</section> : null}
      {users.data ? (
        <>
          <div className="v2-admin-table-scroll v2-admin-users-table">
            <table>
              <thead><tr><th>用户 / 邮箱</th><th>注册 / 最近登录</th><th>会话</th><th>姓名</th><th>电话</th><th>学校</th><th>学历</th><th>操作</th></tr></thead>
              <tbody>
                {users.data.items.length ? users.data.items.map((row) => (
                  <tr key={row.user_id}>
                    <td><code>{row.user_id}</code><small>{row.email ?? "未绑定"}</small></td>
                    <td><span>{dateTime(row.created_at)}</span><small>{dateTime(row.last_login_at)}</small></td>
                    <td>{row.session_count}</td>
                    <td>{resumeValue(row.resume_name)}</td>
                    <td>{resumeValue(row.resume_phone)}</td>
                    <td>{resumeValue(row.resume_school)}</td>
                    <td>{resumeValue(row.resume_degree)}</td>
                    <td><div className="v2-admin-row-actions">
                      <button
                        type="button"
                        aria-expanded={expandedUserId === row.user_id}
                        aria-controls={`admin-resume-${encodeURIComponent(row.user_id)}`}
                        onClick={() => setExpandedUserId(expandedUserId === row.user_id ? null : row.user_id)}
                      >
                        {expandedUserId === row.user_id ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
                        {expandedUserId === row.user_id ? "收起简历" : "查看简历"}
                      </button>
                      <button
                        type="button"
                        disabled={reset.isPending}
                        onClick={() => {
                          if (window.confirm("确认将该用户最新简历会话的解析次数重置为 0？")) reset.mutate(row.user_id);
                        }}
                      ><RotateCcw size={15} />重置解析额度</button>
                    </div></td>
                  </tr>
                )) : <tr><td colSpan={8}>暂无用户</td></tr>}
              </tbody>
            </table>
          </div>
          {expandedUserId ? (
            <ResumeDetail
              id={`admin-resume-${encodeURIComponent(expandedUserId)}`}
              userId={expandedUserId}
              request={request}
            />
          ) : null}
          {reset.data ? (
            <p className="v2-admin-reset-result" role="status" aria-label="解析额度重置结果">
              {reset.data.session_id} · {reset.data.status} · {reset.data.resume_parse_count} 次
            </p>
          ) : null}
          {reset.isError ? <p className="v2-admin-error" role="alert">{reset.error.message}</p> : null}
          <footer className="v2-admin-pagination">
            <button type="button" disabled={page === 1} onClick={() => setPage((value) => Math.max(1, value - 1))}>上一页</button>
            <span>第 {users.data.page} 页</span>
            <button type="button" disabled={!users.data.has_more} onClick={() => setPage((value) => value + 1)}>下一页</button>
          </footer>
        </>
      ) : null}
    </section>
  );
}
