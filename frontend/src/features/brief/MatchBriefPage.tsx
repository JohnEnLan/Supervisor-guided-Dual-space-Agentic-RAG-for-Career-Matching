import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowRight, Building2, Compass, MessageSquareText, Target } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { ApiError, recoveryMessage } from "../../api/client";
import { api, type IntentConsult, type IntentConsultRequest, type MatchBriefRequest } from "../../api/queries";
import { useFlowProgress } from "../../app/App";

type Mode = "targeted" | "explore";

export const splitList = (value: string): string[] =>
  value.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean);

function listText(value: unknown): string {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string").join(", ")
    : typeof value === "string" ? value : "";
}

function visaText(hard: Record<string, unknown>): string {
  if (hard.need_visa_sponsor === true) return "需要签证担保";
  if (hard.need_visa_sponsor === false) return "不需要签证担保";
  return listText(hard.visa_requirement);
}

function needsVisaSponsor(value: string): boolean {
  const normalized = value.trim().toLowerCase();
  const noSponsorMarkers = ["不需要", "无需", "不要求", "no sponsorship", "not require", "graduate visa", "dependent visa"];
  return !noSponsorMarkers.some((marker) => normalized.includes(marker));
}

export function consultationToForm(consultation: IntentConsult) {
  const hard = consultation.hard_constraints ?? {};
  const soft = consultation.soft_preferences ?? {};
  const hardCompanies = listText(hard.companies);
  return {
    mode: consultation.mode,
    careerGoal: consultation.current_goal?.join("；") ?? "",
    locations: listText(hard.locations ?? hard.location),
    visa: visaText(hard),
    roleFamilies: listText(hard.role_clusters ?? hard.role_cluster ?? soft.preferred_role_clusters ?? soft.role_families ?? soft.preferred_role_families),
    avoidRoles: consultation.avoid_roles?.join(", ") ?? "",
    companies: hardCompanies || listText(soft.preferred_companies),
    companyExclusive: Boolean(hardCompanies),
  };
}

type BriefFormValues = {
  careerGoal: string;
  locations: string;
  visa: string;
  roleFamilies: string;
  avoidRoles: string;
  companies: string;
  companyExclusive: boolean;
  resultCount: number;
};

export function buildBriefRequest(values: BriefFormValues): MatchBriefRequest {
  const companies = splitList(values.companies);
  const hardConstraints: Record<string, unknown> = {};
  if (splitList(values.locations).length) hardConstraints.locations = splitList(values.locations);
  if (values.visa.trim()) hardConstraints.need_visa_sponsor = needsVisaSponsor(values.visa);
  if (companies.length && values.companyExclusive) hardConstraints.companies = companies;
  const softPreferences: Record<string, unknown> = {};
  if (splitList(values.roleFamilies).length) softPreferences.preferred_role_clusters = splitList(values.roleFamilies);
  if (companies.length && !values.companyExclusive) softPreferences.preferred_companies = companies;
  return {
    career_goal: values.careerGoal.trim(),
    hard_constraints: hardConstraints,
    soft_preferences: softPreferences,
    avoid_roles: splitList(values.avoidRoles),
    result_count: values.resultCount,
    conflicts: [],
    needs_clarification: false,
    clarification_question: null,
  };
}

type IntentModeFieldsProps = {
  mode: Mode;
  targetRoles?: string;
  targetCompanies?: string;
  companyExclusive?: boolean;
  onTargetRolesChange?: (value: string) => void;
  onTargetCompaniesChange?: (value: string) => void;
  onCompanyExclusiveChange?: (value: boolean) => void;
};

export function IntentModeFields({
  mode,
  targetRoles = "",
  targetCompanies = "",
  companyExclusive = false,
  onTargetRolesChange,
  onTargetCompaniesChange,
  onCompanyExclusiveChange,
}: IntentModeFieldsProps) {
  if (mode === "explore") {
    return <p className="mode-help">第一个 Agent 会基于已确认的教育、经历、项目与技能，给出最多三个可解释方向。</p>;
  }
  return (
    <div className="form-grid">
      <label>目标岗位<input value={targetRoles} onChange={(event) => onTargetRolesChange?.(event.target.value)} placeholder="例如：Data Analyst, BI Analyst" /></label>
      <label>目标公司<input value={targetCompanies} onChange={(event) => onTargetCompaniesChange?.(event.target.value)} placeholder="例如：HSBC, Deloitte（可留空）" /></label>
      <label className="check-row wide"><input type="checkbox" checked={companyExclusive} onChange={(event) => onCompanyExclusiveChange?.(event.target.checked)} />只检索这些目标公司（否则仅作为偏好加权）</label>
    </div>
  );
}

export function MatchBriefPage() {
  const { sessionId = "" } = useParams();
  const navigate = useNavigate();
  const { setProgress } = useFlowProgress();
  const [mode, setMode] = useState<Mode | null>(null);
  const [context, setContext] = useState("");
  const [targetRoles, setTargetRoles] = useState("");
  const [targetCompanies, setTargetCompanies] = useState("");
  const [companyExclusive, setCompanyExclusive] = useState(false);
  const [clarification, setClarification] = useState("");
  const [careerGoal, setCareerGoal] = useState("");
  const [locations, setLocations] = useState("");
  const [visa, setVisa] = useState("");
  const [roleFamilies, setRoleFamilies] = useState("");
  const [avoidRoles, setAvoidRoles] = useState("");
  const [resultCount, setResultCount] = useState(5);

  useEffect(() => {
    setProgress({ activeStage: "intent", completedStages: ["resume"] });
  }, [setProgress]);

  const hydrateConsultation = useCallback((result: IntentConsult) => {
    const restored = consultationToForm(result);
    setMode(restored.mode);
    setCareerGoal(restored.careerGoal);
    setTargetRoles(restored.careerGoal);
    setLocations(restored.locations);
    setVisa(restored.visa);
    setRoleFamilies(restored.roleFamilies);
    setAvoidRoles(restored.avoidRoles);
    setTargetCompanies(restored.companies);
    setCompanyExclusive(restored.companyExclusive);
  }, []);
  const savedConsultation = useQuery({
    queryKey: ["intent-consult", sessionId],
    queryFn: () => api.getIntentConsult(sessionId),
    enabled: Boolean(sessionId),
    retry: false,
  });
  useEffect(() => {
    if (savedConsultation.data) hydrateConsultation(savedConsultation.data);
  }, [hydrateConsultation, savedConsultation.data]);

  const consultation = useMutation({
    mutationFn: (request: IntentConsultRequest) => api.consultIntent(sessionId, request),
    onSuccess: (result) => {
      hydrateConsultation(result);
    },
  });
  const brief = useMutation({
    mutationFn: (request: MatchBriefRequest) => api.createMatchBrief(sessionId, request),
  });

  const sendConsultation = (answer?: string) => {
    if (!mode) return;
    consultation.mutate({
      mode,
      goal_text: context.trim() || null,
      target_roles: splitList(targetRoles),
      target_companies: splitList(targetCompanies),
      company_exclusive: companyExclusive,
      clarification_answer: answer?.trim() || null,
    });
  };
  const submitBrief = (event: FormEvent) => {
    event.preventDefault();
    brief.mutate(buildBriefRequest({ careerGoal, locations, visa, roleFamilies, avoidRoles, companies: targetCompanies, companyExclusive, resultCount }));
  };
  const consultError = consultation.error instanceof ApiError ? consultation.error : null;
  const visibleConsultation = consultation.data ?? savedConsultation.data;
  const savedConsultationError = savedConsultation.error instanceof ApiError && savedConsultation.error.status !== 404
    ? savedConsultation.error
    : null;

  return (
    <section>
      <p className="eyebrow">Stage 1 · Intent Agent</p>
      <h1>你已经有目标职业或目标公司吗？</h1>
      <p className="lead">你的选择会决定第一个 Agent 的工作方式：校验并细化现有目标，或从简历证据探索少量可行方向。</p>
      {savedConsultation.isPending ? <p className="muted">正在检查已保存的咨询…</p> : null}
      {savedConsultationError ? <p className="inline-error" role="alert">{recoveryMessage(savedConsultationError)}</p> : null}
      <div className="mode-selector" role="radiogroup" aria-label="目标状态">
        <label className={mode === "targeted" ? "selected" : ""}><input type="radio" name="mode" checked={mode === "targeted"} onChange={() => setMode("targeted")} /><Target /> <span><strong>我已有目标</strong><small>输入岗位、公司或职业想法</small></span></label>
        <label className={mode === "explore" ? "selected" : ""}><input type="radio" name="mode" checked={mode === "explore"} onChange={() => setMode("explore")} /><Compass /> <span><strong>我想先探索</strong><small>让 Agent 给出最多三个方向</small></span></label>
      </div>
      {mode ? (
        <section className="consult-panel">
          <IntentModeFields mode={mode} targetRoles={targetRoles} targetCompanies={targetCompanies} companyExclusive={companyExclusive} onTargetRolesChange={setTargetRoles} onTargetCompaniesChange={setTargetCompanies} onCompanyExclusiveChange={setCompanyExclusive} />
          <label>补充背景或偏好（可选）<textarea value={context} onChange={(event) => setContext(event.target.value)} rows={3} placeholder="例如：希望留在英国、偏好金融数据场景、长期想转向数据产品" /></label>
          <button className="primary" type="button" disabled={consultation.isPending || (mode === "targeted" && !targetRoles.trim() && !context.trim())} onClick={() => sendConsultation()}><MessageSquareText size={18} />{consultation.isPending ? "Agent 正在分析…" : "与目标咨询 Agent 对话"}</button>
          {consultation.isError ? <p className="inline-error" role="alert">{consultError ? recoveryMessage(consultError) : "咨询暂时失败，请重试。"}</p> : null}
        </section>
      ) : null}
      {visibleConsultation ? (
        <section className="agent-response" aria-live="polite">
          <div className="agent-label"><span>A1</span><strong>目标咨询 Agent</strong></div>
          <p>{visibleConsultation.assistant_message}</p>
          {visibleConsultation.directions?.length ? <div className="direction-grid">{visibleConsultation.directions.slice(0, 3).map((direction) => (
            <article key={direction.role_family}><p className="eyebrow">{direction.role_family}</p><h3>{direction.title}</h3><p>{direction.rationale}</p>{direction.primary_gap ? <p><strong>主要缺口：</strong>{direction.primary_gap}</p> : null}<button className="secondary" type="button" onClick={() => { setCareerGoal(`${direction.title} — ${direction.rationale}`); setRoleFamilies(direction.role_family); }}>选择{direction.title}方向</button></article>
          ))}</div> : null}
          {visibleConsultation.needs_clarification && visibleConsultation.clarification_question ? (
            <div className="clarification"><label>{visibleConsultation.clarification_question}<textarea rows={2} value={clarification} onChange={(event) => setClarification(event.target.value)} /></label><button className="secondary" type="button" disabled={!clarification.trim() || consultation.isPending} onClick={() => sendConsultation(clarification)}>回答一次澄清问题</button></div>
          ) : null}
        </section>
      ) : null}
      {visibleConsultation && !visibleConsultation.needs_clarification ? (
        <form className="brief-form" onSubmit={submitBrief}>
          <div><p className="eyebrow">Supervisor Planning</p><h2>确认 Match Brief</h2><p className="muted">运行开始后硬约束不会被 Agent 改写。</p></div>
          <div className="form-grid">
            <label className="wide">职业目标<textarea aria-label="职业目标" required minLength={10} rows={3} value={careerGoal} onChange={(event) => setCareerGoal(event.target.value)} /></label>
            <label>地点硬约束<input value={locations} onChange={(event) => setLocations(event.target.value)} placeholder="Birmingham, London" /></label>
            <label>签证要求<input value={visa} onChange={(event) => setVisa(event.target.value)} placeholder="例如：需要 Skilled Worker sponsorship" /></label>
            <label>岗位族偏好<input value={roleFamilies} onChange={(event) => setRoleFamilies(event.target.value)} placeholder="Data Analyst, BI Analyst" /></label>
            <label>避免岗位<input value={avoidRoles} onChange={(event) => setAvoidRoles(event.target.value)} placeholder="Sales, Recruiter" /></label>
            <label>结果数量<select value={resultCount} onChange={(event) => setResultCount(Number(event.target.value))}>{[3, 5, 8, 10].map((count) => <option key={count} value={count}>{count} 个</option>)}</select></label>
          </div>
          <button className="primary" type="submit" disabled={brief.isPending || careerGoal.trim().length < 10}>{brief.isPending ? "正在锁定计划…" : "生成并批准 Match Brief"}</button>
          {brief.isError ? <p className="inline-error" role="alert">计划创建失败，请检查冲突后重试。</p> : null}
        </form>
      ) : null}
      {brief.data ? (
        <section className="approved-brief">
          <div><p className="eyebrow">计划已锁定</p><h2>{brief.data.brief.career_goal}</h2><p>计划版本 {brief.data.brief.plan_version} · 指纹 <code>{brief.data.brief.plan_hash.slice(0, 8)}</code></p></div>
          <button className="primary" type="button" onClick={() => navigate(`/runs/${brief.data.run_id}`)}>开始匹配<ArrowRight size={18} /></button>
        </section>
      ) : null}
    </section>
  );
}
