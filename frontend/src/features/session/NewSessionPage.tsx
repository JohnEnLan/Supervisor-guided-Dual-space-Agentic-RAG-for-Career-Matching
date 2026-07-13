import { useMutation } from "@tanstack/react-query";
import { FileText, LockKeyhole, Upload } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError } from "../../api/client";
import { api } from "../../api/queries";

const ALLOWED_EXTENSIONS = [".pdf", ".docx", ".txt"];

export function resumeFileError(file: File | null): string | null {
  if (!file) return "请先选择一份简历文件。";
  const name = file.name.toLowerCase();
  return ALLOWED_EXTENSIONS.some((extension) => name.endsWith(extension))
    ? null
    : "请选择 PDF、DOCX 或 TXT 格式的简历。";
}

export function NewSessionPage() {
  const navigate = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [validation, setValidation] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: async (resume: File) => {
      const session = await api.createSession({ user_id: crypto.randomUUID() });
      await api.uploadResume(session.session_id, resume);
      return session;
    },
    onSuccess: (session) => navigate(`/sessions/${session.session_id}/resume`),
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const error = resumeFileError(file);
    setValidation(error);
    if (!error && file) mutation.mutate(file);
  };
  const apiError = mutation.error instanceof ApiError ? mutation.error : null;

  return (
    <section className="narrow-page">
      <p className="eyebrow">新匹配任务</p>
      <h1>先从一份真实简历开始</h1>
      <p className="lead">系统会先提取结构化经历并展示原文证据，只有你确认后才会进入职业目标咨询。</p>
      <form className="upload-panel" onSubmit={submit}>
        <FileText size={34} aria-hidden="true" />
        <label htmlFor="resume-file"><strong>选择简历文件</strong><span>支持 PDF、DOCX、TXT；一次上传一份</span></label>
        <input
          id="resume-file"
          type="file"
          accept=".pdf,.docx,.txt"
          onChange={(event) => {
            const next = event.target.files?.[0] ?? null;
            setFile(next);
            setValidation(resumeFileError(next));
          }}
        />
        {file ? <p className="file-name">已选择：{file.name}</p> : null}
        {validation ? <p className="inline-error" role="alert">{validation}</p> : null}
        {mutation.isError ? (
          <div className="notice error" role="alert">
            <strong>上传没有完成</strong>
            <span>{apiError?.message ?? "请检查服务连接后重试。"}</span>
          </div>
        ) : null}
        <button className="primary" type="submit" disabled={mutation.isPending}>
          <Upload size={18} />{mutation.isPending ? "正在处理…" : "上传并开始"}
        </button>
      </form>
      <p className="privacy-note"><LockKeyhole size={16} />简历内容仅用于当前会话；公开解释不会返回完整简历或内部提示词。</p>
    </section>
  );
}
