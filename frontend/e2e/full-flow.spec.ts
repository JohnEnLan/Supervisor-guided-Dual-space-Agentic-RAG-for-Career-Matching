import { expect, test, type Page, type Route } from "@playwright/test";

const planHash = "a".repeat(64);

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

async function installFlowApi(page: Page) {
  let executed = false;
  const calls = { execute: 0, status: 0 };
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const method = route.request().method();
    if (path === "/api/v1/capabilities") return json(route, { api_version: "v1", dual_space_enabled: true, execution_durability: "process_local", explain_enabled: true, monitoring_enabled: true });
    if (path === "/api/v1/sessions" && method === "POST") return json(route, { session_id: "session-1", status: "created" }, 201);
    if (path === "/api/v1/sessions/session-1/resume" && method === "POST") return json(route, { session_id: "session-1", status: "resume_queued" }, 202);
    if (path.endsWith("/resume-preview")) return json(route, { session_id: "session-1", resume_version: 1, confirmed: false, skills: ["Python", "SQL"], experience: [{ organization: "Example Lab", title: "Data Intern", location: "Birmingham", dates: "2025", achievements: ["Built a matching benchmark"], evidence_span_ids: ["resume-1"] }], education: [{ institution: "University of Birmingham", degree: "MSc", field: "Computer Science", dates: "2025–2026", evidence_span_ids: ["resume-2"] }], projects: [{ name: "Career RAG", summary: "Evidence-grounded job matching", dates: "2026", outcomes: ["Built retrieval benchmark"], technologies: ["Python"] }], resume_quality_issues: ["部分项目缺少量化结果"], evidence: [{ evidence_span_id: "resume-1", content: "Built a matching benchmark" }] });
    if (path.endsWith("/resume-confirm") && method === "POST") return json(route, { session_id: "session-1", resume_version: 1, confirmed: true, confirmed_at: "2026-07-13T12:00:00Z" });
    if (path.endsWith("/intent-consult") && method === "POST") return json(route, { session_id: "session-1", mode: "targeted", assistant_message: "目标清晰：优先数据分析岗位，并保留可验证的 SQL 证据。", current_goal: ["Become a data analyst in the UK market"], long_term_goal: ["Grow into analytics leadership"], hard_constraints: {}, soft_preferences: { role_families: ["Data Analyst"] }, avoid_roles: [], directions: [], needs_clarification: false, clarification_question: null, clarification_used: 0 });
    if (path.endsWith("/match-brief") && method === "POST") return json(route, { session_id: "session-1", run_id: "run-1", brief: { career_goal: "Become a data analyst in the UK market", hard_constraints: {}, soft_preferences: { role_families: ["Data Analyst"] }, avoid_roles: [], result_count: 5, conflicts: [], needs_clarification: false, clarification_question: null, plan_version: 1, plan_hash: planHash } }, 201);
    if (path === "/api/v1/runs/run-1/status") { calls.status += 1; return json(route, executed ? { run_id: "run-1", session_id: "session-1", status: "completed", stage: "result", result_ready: true, warning_codes: [], error_code: null, execution_durability: "process_local", retry_after_ms: null, completed_stages: ["resume", "intent", "retrieval", "strategy", "verification", "finalization"], total_stages: 7, plan_version: 1, plan_hash: planHash, updated_at: "2026-07-13T12:01:00Z" } : { run_id: "run-1", session_id: "session-1", status: "plan_ready", stage: "intent", result_ready: false, warning_codes: [], error_code: null, execution_durability: "process_local", retry_after_ms: 100, completed_stages: ["resume", "intent"], total_stages: 7, plan_version: 1, plan_hash: planHash, updated_at: "2026-07-13T12:00:00Z" }); }
    if (path.endsWith("/execute") && method === "POST") { calls.execute += 1; executed = true; return json(route, { run_id: "run-1", session_id: "session-1", status: "running", stage: "retrieval", result_ready: false, warning_codes: [], error_code: null, execution_durability: "process_local", retry_after_ms: 100, completed_stages: ["resume", "intent"], total_stages: 7, plan_version: 1, plan_hash: planHash, updated_at: "2026-07-13T12:00:10Z" }, 202); }
    if (path.endsWith("/result")) return json(route, { run_id: "run-1", status: "completed", result: { summary: "找到 1 个证据充分的推荐", recommended_roles: [{ job_id: "job-1", title: "Data Analyst", company: "Example Ltd", location: "Birmingham", tier: "now_fit", listing_kind: "dataset_only", source_url: null, concise_explanation: "SQL 与数据项目证据吻合", why_this_match: ["SQL 技能与 JD 要求一致"], evidence: [{ evidence_span_id: "jd-1", content: "Advanced SQL is required", field: "requirements" }], resume_evidence: [{ evidence_span_id: "resume-1", content: "Built a matching benchmark", field: "experience" }] }], skill_gaps: [{ skill: "Power BI", gap: "需要作品集证据", priority: "medium", evidence_span_ids: ["jd-1"] }], resume_strategy: [{ section: "Projects", suggestion: "补充可验证的指标", evidence_span_ids: ["resume-1"] }], career_path: [{ horizon: "short", action: "完成 BI 仪表盘项目", evidence_span_ids: ["jd-1"] }], warnings: [] } });
    if (path.endsWith("/explain")) return json(route, { run_id: "run-1", fusion: { implicit_max_weight: 0.3 }, rank_trace: [{ job_id: "job-1", explicit_rank: 2, explicit_score: 0.82, implicit_rank: 1, implicit_score: 0.9, final_rank: 1, implicit_confidence: 0.8, implicit_weight: 0.24, case_ids: ["case-001"], case_evidence: [{ case_id: "case-001", highest_stage: "interview", confidence: 0.8 }] }], stage_durations_ms: { retrieval: 2100, strategy: 1800 }, recovery_events: [] });
    if (path.endsWith("/reaction") && method === "POST") return json(route, { feedback_id: 1, run_id: "run-1", status: "reaction_recorded" }, 201);
    return json(route, { detail: "fixture route not found" }, 404);
  });
  return calls;
}

async function expectNoOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)).toBe(false);
}

test("completes the resume-to-evidence flow and remains responsive", async ({ page }) => {
  const calls = await installFlowApi(page);
  await page.setViewportSize({ width: 375, height: 900 });
  await page.goto("/workspace");
  await expectNoOverflow(page);
  await page.getByLabel("选择简历文件").setInputFiles({ name: "resume.txt", mimeType: "text/plain", buffer: Buffer.from("Python SQL") });
  await page.getByRole("button", { name: "上传并开始" }).click();
  await expect(page.getByRole("heading", { name: "确认系统理解的简历事实" })).toBeVisible();
  await expectNoOverflow(page);
  await page.getByRole("button", { name: "确认简历" }).click();
  await page.getByRole("radio", { name: /我已有目标/ }).check();
  await page.getByLabel("目标岗位").fill("Data Analyst");
  await page.getByRole("button", { name: "与目标咨询 Agent 对话" }).click();
  await expect(page.getByText("目标清晰：优先数据分析岗位")).toBeVisible();
  await expectNoOverflow(page);
  await page.getByRole("button", { name: "生成并批准 Match Brief" }).click();
  await expect(page.getByText("计划已锁定")).toBeVisible();
  await page.getByRole("button", { name: /开始匹配/ }).click();
  await page.getByRole("link", { name: /查看完整结果/ }).click();
  expect(calls.execute).toBe(1);
  const terminalStatusCalls = calls.status;
  await page.waitForTimeout(250);
  expect(calls.status).toBe(terminalStatusCalls);
  await expect(page.getByRole("heading", { name: "找到 1 个证据充分的推荐" })).toBeVisible();
  await expectNoOverflow(page);
  const evidenceTrigger = page.getByRole("button", { name: "查看证据" });
  await evidenceTrigger.click();
  await expect(page.getByRole("dialog")).toContainText("Advanced SQL is required");
  await expectNoOverflow(page);
  await page.keyboard.press("Escape");
  await expect(evidenceTrigger).toBeFocused();
  await page.getByRole("button", { name: "提交反馈" }).click();
  await expect(page.getByText("反馈已记录，谢谢你的判断。")).toBeVisible();
  await page.getByRole("link", { name: /查看评估解释/ }).click();
  await expect(page.getByRole("heading", { name: "双空间检索与恢复轨迹" })).toBeVisible();
  await expect(page.getByText(/case-001/)).toBeVisible();

  for (const width of [768, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await expectNoOverflow(page);
  }
});

test("explores at most three directions and selects one without another Agent call", async ({ page }) => {
  let intentCalls = 0;
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/capabilities")) return json(route, { api_version: "v1", dual_space_enabled: true, execution_durability: "process_local", explain_enabled: true, monitoring_enabled: false });
    if (path.endsWith("/intent-consult") && route.request().method() === "POST") {
      intentCalls += 1;
      return json(route, { session_id: "session-1", mode: "explore", assistant_message: "基于简历证据找到两个可行方向。", current_goal: [], long_term_goal: [], hard_constraints: {}, soft_preferences: {}, avoid_roles: [], needs_clarification: false, clarification_question: null, clarification_used: 0, directions: [{ role_family: "Data Analytics", title: "Data Analyst", rationale: "已有 SQL 与项目证据", resume_evidence_span_ids: ["resume-1"], primary_gap: "BI portfolio", entry_role: "Junior Data Analyst" }, { role_family: "Business Intelligence", title: "BI Analyst", rationale: "分析与沟通经历可迁移", resume_evidence_span_ids: ["resume-2"], primary_gap: "Power BI", entry_role: "Junior BI Analyst" }] });
    }
    return json(route, { detail: "fixture route not found" }, 404);
  });
  await page.goto("/sessions/session-1/brief");
  await page.getByRole("radio", { name: /我想先探索/ }).check();
  await page.getByRole("button", { name: "与目标咨询 Agent 对话" }).click();
  await page.getByRole("button", { name: "选择Data Analyst方向" }).click();
  await expect(page.getByLabel("职业目标")).toHaveValue(/Data Analyst/);
  expect(intentCalls).toBe(1);
});

test("restores a saved consultation after refresh without another Agent call", async ({ page }) => {
  let getCalls = 0;
  let postCalls = 0;
  const saved = { session_id: "session-1", mode: "targeted", assistant_message: "已恢复保存的目标咨询。", current_goal: ["Become a data analyst in Birmingham"], long_term_goal: [], hard_constraints: { locations: ["Birmingham"], visa_requirement: "Skilled Worker sponsorship", companies: ["Example Ltd"] }, soft_preferences: { role_families: ["Data Analyst"] }, avoid_roles: ["Sales"], directions: [], needs_clarification: false, clarification_question: null, clarification_used: 0 };
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/capabilities")) return json(route, { api_version: "v1", dual_space_enabled: true, execution_durability: "process_local", explain_enabled: false, monitoring_enabled: false });
    if (path.endsWith("/intent-consult") && route.request().method() === "GET") { getCalls += 1; return json(route, saved); }
    if (path.endsWith("/intent-consult")) { postCalls += 1; return json(route, saved); }
    return json(route, { detail: "not found" }, 404);
  });
  await page.goto("/sessions/session-1/brief");
  await expect(page.getByText("已恢复保存的目标咨询。")).toBeVisible();
  await expect(page.getByLabel("地点硬约束")).toHaveValue("Birmingham");
  await expect(page.getByLabel("签证要求")).toHaveValue("Skilled Worker sponsorship");
  await expect(page.getByLabel("避免岗位")).toHaveValue("Sales");
  await page.reload();
  await expect(page.getByText("已恢复保存的目标咨询。")).toBeVisible();
  expect(getCalls).toBeGreaterThanOrEqual(2);
  expect(postCalls).toBe(0);
});

test("recovers a competing execute with status refetch and one execute call", async ({ page }) => {
  let executeCalls = 0;
  let anotherTabWon = false;
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/capabilities")) return json(route, { api_version: "v1", dual_space_enabled: true, execution_durability: "process_local", explain_enabled: false, monitoring_enabled: false });
    if (path.endsWith("/status")) return json(route, anotherTabWon ? { run_id: "run-1", session_id: "session-1", status: "completed", stage: "result", result_ready: true, warning_codes: [], error_code: null, execution_durability: "process_local", retry_after_ms: null, completed_stages: ["resume", "intent", "retrieval", "strategy", "verification", "finalization"], total_stages: 7, plan_version: 1, plan_hash: planHash, updated_at: "2026-07-13T12:01:00Z" } : { run_id: "run-1", session_id: "session-1", status: "plan_ready", stage: "intent", result_ready: false, warning_codes: [], error_code: null, execution_durability: "process_local", retry_after_ms: 100, completed_stages: ["resume", "intent"], total_stages: 7, plan_version: 1, plan_hash: planHash, updated_at: "2026-07-13T12:00:00Z" });
    if (path.endsWith("/execute")) { executeCalls += 1; anotherTabWon = true; return json(route, { detail: "run already executing" }, 409); }
    return json(route, { detail: "not found" }, 404);
  });
  await page.goto("/runs/run-1");
  await expect(page.getByRole("link", { name: /查看完整结果/ })).toBeVisible();
  expect(executeCalls).toBe(1);
});

test("offers an idempotent manual retry after a transient execute failure", async ({ page }) => {
  let executeCalls = 0;
  let completed = false;
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/capabilities")) return json(route, { api_version: "v1", dual_space_enabled: true, execution_durability: "process_local", explain_enabled: false, monitoring_enabled: false });
    if (path.endsWith("/status")) return json(route, completed ? { run_id: "run-1", session_id: "session-1", status: "completed", stage: "result", result_ready: true, warning_codes: [], error_code: null, execution_durability: "process_local", retry_after_ms: null, completed_stages: ["resume", "intent", "retrieval", "strategy", "verification", "finalization"], total_stages: 7, plan_version: 1, plan_hash: planHash, updated_at: "2026-07-13T12:01:00Z" } : { run_id: "run-1", session_id: "session-1", status: "plan_ready", stage: "intent", result_ready: false, warning_codes: [], error_code: null, execution_durability: "process_local", retry_after_ms: 100, completed_stages: ["resume", "intent"], total_stages: 7, plan_version: 1, plan_hash: planHash, updated_at: "2026-07-13T12:00:00Z" });
    if (path.endsWith("/execute")) { executeCalls += 1; if (executeCalls === 1) return route.abort("failed"); completed = true; return json(route, { run_id: "run-1", session_id: "session-1", status: "running", stage: "retrieval", result_ready: false, warning_codes: [], error_code: null, execution_durability: "process_local", retry_after_ms: 100, completed_stages: ["resume", "intent"], total_stages: 7, plan_version: 1, plan_hash: planHash, updated_at: "2026-07-13T12:00:10Z" }, 202); }
    return json(route, { detail: "not found" }, 404);
  });
  await page.goto("/runs/run-1");
  await page.getByRole("button", { name: "重试执行" }).click();
  await expect(page.getByRole("link", { name: /查看完整结果/ })).toBeVisible();
  expect(executeCalls).toBe(2);
});

test("allows one clarification answer and then locks the brief fields", async ({ page }) => {
  let postCalls = 0;
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/capabilities")) return json(route, { api_version: "v1", dual_space_enabled: true, execution_durability: "process_local", explain_enabled: false, monitoring_enabled: false });
    if (path.endsWith("/intent-consult") && route.request().method() === "GET") return json(route, { detail: "not found" }, 404);
    if (path.endsWith("/intent-consult")) {
      postCalls += 1;
      return json(route, postCalls === 1
        ? { session_id: "session-1", mode: "targeted", assistant_message: "需要确认地点。", current_goal: ["Become a data analyst in the UK"], hard_constraints: {}, soft_preferences: {}, avoid_roles: [], directions: [], needs_clarification: true, clarification_question: "你是否只考虑 Birmingham？", clarification_used: 1 }
        : { session_id: "session-1", mode: "targeted", assistant_message: "地点已确认。", current_goal: ["Become a data analyst in Birmingham"], hard_constraints: { locations: ["Birmingham"] }, soft_preferences: {}, avoid_roles: [], directions: [], needs_clarification: false, clarification_question: null, clarification_used: 1 });
    }
    return json(route, { detail: "not found" }, 404);
  });
  await page.goto("/sessions/session-1/brief");
  await page.getByRole("radio", { name: /我已有目标/ }).check();
  await page.getByLabel("目标岗位").fill("Data Analyst");
  await page.getByRole("button", { name: "与目标咨询 Agent 对话" }).click();
  await page.getByLabel("你是否只考虑 Birmingham？").fill("是，只考虑 Birmingham");
  await page.getByRole("button", { name: "回答一次澄清问题" }).click();
  await expect(page.getByLabel("地点硬约束")).toHaveValue("Birmingham");
  await expect(page.getByRole("button", { name: "回答一次澄清问题" })).toHaveCount(0);
  expect(postCalls).toBe(2);
});

test("uses structured result recovery without claiming completed progress", async ({ page }) => {
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/capabilities")) return json(route, { api_version: "v1", dual_space_enabled: true, execution_durability: "process_local", explain_enabled: false, monitoring_enabled: false });
    if (path.endsWith("/result")) return json(route, { detail: { message: "run result is not ready", recovery: { action: "poll_status", status_url: "/api/v1/runs/run-1/status" } } }, 409);
    return json(route, { detail: "not found" }, 404);
  });
  await page.goto("/runs/run-1/results");
  await expect(page.getByRole("heading", { name: "结果尚未可读" })).toBeVisible();
  await expect(page.getByText("请返回运行进度页继续等待。")).toBeVisible();
  await expect(page.getByRole("link", { name: "返回运行" })).toHaveAttribute("href", "/runs/run-1");
  await expect(page.getByText("第 7/7 阶段")).toHaveCount(0);
});

test("blocks the direct examiner route when capability is disabled", async ({ page }) => {
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/capabilities")) return json(route, { api_version: "v1", dual_space_enabled: true, execution_durability: "process_local", explain_enabled: false, monitoring_enabled: false });
    return json(route, { detail: "not found" }, 404);
  });
  await page.goto("/runs/run-1/evaluation");
  await expect(page.getByRole("heading", { name: "评估解释未开启" })).toBeVisible();
  await expect(page.getByRole("link", { name: "返回产品结果" })).toHaveAttribute("href", "/runs/run-1/results");
});
