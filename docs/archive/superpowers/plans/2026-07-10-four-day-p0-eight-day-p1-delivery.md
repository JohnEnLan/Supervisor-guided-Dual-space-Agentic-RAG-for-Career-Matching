# 4-Day P0 / 8-Day P1 Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 基于当前已通过 112 个测试的后端，在第 4 天交付可运行、带前端、可解释、可离线演示的 P0；在第 8 天前完成正确的匿名简历结果空间、反馈闭环和双空间对照评估 P1。

**Architecture:** 不重做现有简历归一化、混合检索、三 Agent、Supervisor、PostgreSQL state store 和评估基础。先以“显式 JD 检索为权威候选集、匿名结果案例只做置信度受控重排”的方式补上真实双空间读路径，再增加最小 `session_id`/`run_id` 公共契约和 allow-list 结果投影，React 前端只消费 `/api/v1` DTO。P1 在同一条链路上补齐私有快照、严格匿名化、申请事件、审核后案例发布和延迟回访，不保留第二套并行闭环。

**Tech Stack:** Python 3.11+、FastAPI、Pydantic、asyncio、asyncpg、PostgreSQL + pgvector、DeepSeek、Qwen Embedding；Vite + React + TypeScript、React Router、TanStack Query、OpenAPI 生成类型、Zod、Vitest、Testing Library、Playwright。

## Global Constraints

- 状态按 `session_id` / `run_id` 存 PostgreSQL；不得使用进程全局用户状态。
- 并发只使用 `asyncio`；LLM/embedding 全部经过现有 Semaphore、timeout 和错误分类。
- 三个业务 Agent 仍是三次不同 system prompt 的 LLM 调用；不引入 LangGraph、AutoGen、CrewAI、线程或多进程。
- SQL/metadata 硬过滤始终权威；隐式证据只能重排显式候选，不能恢复被过滤岗位。
- 所有推荐解释至少引用一个 JD evidence ID；所有简历建议至少引用一个原简历 evidence ID。
- clarification、re-retrieval、repair 各最多一次；禁止开放式循环。
- 公共 API 不返回 raw `SharedState`、`user_id`、完整简历、完整 prompt、原始 `supervisor_log` 或 provider/SQL 异常。
- P2 RAPTOR、cross-encoder 和公共生产部署不进入 8 天关键路径。
- 每个小任务采用 TDD：先失败测试，再最小实现，再定向测试与全量回归。
- 数据库变更使用编号 SQL migration，并同步 `app/db/schema.sql` 新装快照。
- 不覆盖当前未跟踪的用户文档与 `outputs/`；提交前检查 secrets、临时简历和构建产物。

---

## 0. 范围口径与当前基线

### P0（Day 4 结束）

P0 是“答辩可用的完整产品主链”，必须包含：

```text
上传简历
→ 解析预览与确认
→ 输入目标/硬约束/软偏好
→ 确认 Match Brief
→ 创建 run_id 并轮询阶段
→ 显式 JD 检索 + fixture-backed 匿名结果案例重排
→ 三 Agent + Supervisor
→ 一份统一推荐结果
→ JD/简历 evidence 明细
→ examiner-only 双空间解释
→ 即时 usefulness reaction
```

P0 的隐式空间使用确定性、去身份化样例运行真实读取与融合代码；P0 不要求真实用户反馈自动写入公共案例库。

### P1（Day 8 结束）

P1 是“正确双空间记忆与反馈机制闭环”，必须包含：私有简历版本、严格去身份化、推荐/申请/阶段事件分离、显式 learning consent、待审核案例、匿名案例结果发布、相似案例重排、可重试的延迟回访 demo、无泄漏对照评估。

这里的 P1 不等于 `codex_step_plan_dual_space_link.md` 中的 Release 1 Public Beta。账号体系、CSRF、生产 worker lease、配额、TLS、备份恢复与公网 SLA 继续列为后续工作。

### 已验证基线

- 当前分支：`codex/week3-reoptimization`。
- 当前全量测试：`112 passed in 2.74s`。
- 可直接复用：归一化/evidence、hybrid search、Agent/Supervisor、有界 repair/re-retrieval、状态持久化、FastAPI 轮询、private memory、feedback closure、ranking metrics、并发测试。
- 主要缺口：正确双空间读取与融合、`run_id`/公开 DTO、allow-list Result/Explain、React 前端、匿名简历结果写路径。

### 执行前提

- 单人 + Codex 全职执行，每天约 8–10 小时。
- PostgreSQL/pgvector 与现有 job corpus 可用；live provider 不稳定时使用 deterministic fake provider。
- 每天只并行无共享写依赖的测试/审查；业务模块仍按“一个模块跑通再下一个”执行。

---

## 1. 八天总排期

| 天 | 当天唯一主目标 | 当天结束必须可演示 |
|---|---|---|
| Day 1 | 正确双空间读取、融合、双证据 | 显式结果可在匿名案例证据充分时被受控重排；空案例/故障时显式结果不变 |
| Day 2 | `run_id` API、Match Brief、Result/Explain | 纯 API 跑通 preview → brief → execute → status → result/explain，公共响应无 raw state |
| Day 3 | React 前端完整主流程 | 浏览器完成上传、确认、轮询、统一结果、evidence drawer、Evaluation View |
| Day 4 | P0 集成、离线 demo、最小评估、缓冲 | 一条 deterministic E2E、两会话不串、explicit vs dual-space 指标表、P0 Gate 全过 |
| Day 5 | 私有快照与严格匿名化 | PII 被删除，学校/公司/岗位/项目/技能等职业证据保留，上传时不发布公共案例 |
| Day 6 | 推荐/申请/阶段事件与案例发布闭环 | 推荐不等于申请；consent + confirmed application + stage + review 后才发布匿名案例 |
| Day 7 | 延迟回访、样例案例、P1 前端入口 | console channel 可领取到期回访且不重复发送；前端可提交申请阶段与学习同意 |
| Day 8 | P1 E2E、无泄漏消融、总验收 | cold-start 与 mature 双场景、explicit vs dual-space 对照、反馈反哺下一次推荐 |

---

## Day 1：正确双空间读取与证据化融合

**目标：** 先修正论文核心语义，不动已经稳定的 BM25/dense/RRF 主体。

**Files:**

- Create: `app/memory/case_schema.py`
- Create: `app/db/migrations/0001_dual_space_read_model.sql`
- Create: `app/db/migrate.py`
- Modify: `app/db/schema.sql`
- Create: `app/retrieval/implicit_search.py`
- Create: `app/retrieval/dual_space_search.py`
- Modify: `app/memory/case_base.py`
- Modify: `app/retrieval/hybrid_search.py`
- Modify: `app/retrieval/__init__.py`
- Modify: `app/config.py`
- Modify: `.env.example`
- Modify: `app/agents/matching_agent.py`
- Modify: `app/agents/supervisor.py`
- Modify: `app/agents/orchestrator.py`
- Test: `tests/test_dual_space_schema.py`
- Test: `tests/test_implicit_search.py`
- Test: `tests/test_dual_space_search.py`
- Modify: `tests/test_agents_phase_c.py`
- Modify: `tests/test_matching_explanation_benchmark.py`

**Interfaces:**

```python
def aggregate_implicit_evidence(
    rows: list[dict], *, candidate_job_id: str
) -> ImplicitEvidence: ...

def build_implicit_query_text(resume_state: ResumeState) -> str: ...

async def search_similar_resume_cases_by_embedding(
    query_embedding: list[float], *, top_k: int = 20
) -> list[dict]: ...

async def search_implicit_evidence(
    *, anonymized_resume_text: str,
    candidates: list[JobCandidate],
    top_k_cases: int = 20,
) -> dict[str, ImplicitEvidence]: ...

async def dual_space_search(
    *, query: str,
    anonymized_resume_text: str,
    hard_constraints: dict,
    soft_prefs: dict,
    top_k: int,
    implicit_enabled: bool = True,
) -> list[JobCandidate]: ...
```

- [ ] **1.1 锁定领域契约和只读表。** 定义 `HiringStage`、`AnonymousResumeCase`、`CaseJobOutcome`、`ImplicitEvidence`；migration 创建 `anonymous_resume_cases` 与 `case_job_outcomes`，两表不含 `user_id`、邮箱、电话或外部身份。`case_base.py` 先提供 embedding-based 只读查询，Day 6 再增加受控写入。
- [ ] **1.2 建立 P0 查询隐私边界。** `build_implicit_query_text` 只拼教育、公司、岗位、项目和技能等结构化 allow-list 字段，不使用姓名、联系方式或整份 `normalized_base_resume`；Day 5 在此基础上补完整持久化匿名化。
- [ ] **1.3 写纯函数隐式评分。** 使用 `similarity × stage_weight × explicit_match_score × source_confidence` 的有界加权平均，按 `job_id` 优先、`company + role_family` 次之匹配，禁止 company-only 匹配。
- [ ] **1.4 写并行融合。** 显式/隐式分支用 `asyncio.gather`；`beta = IMPLICIT_MAX_WEIGHT × confidence`，默认最大权重 `0.30`；只修改显式候选的最终排序。
- [ ] **1.5 锁定降级规则。** 空案例、弱证据或隐式异常返回显式顺序；`CancelledError` 继续抛出；显式检索失败则 run 失败。
- [ ] **1.6 接入 Agent。** `matching_agent` 输出分离的 `explicit_explanation`、`implicit_explanation` 和 evidence；Supervisor 删除无 case ID、夸大数量或承诺录用结果的隐式 claim。
- [ ] **1.7 删除错误语义入口。** `Supervisor.plan_retrieval` 不再把 `case_soft_preferences` 当第二空间；旧字段仅兼容读取，不参与默认 ranking。

**Day 1 tests:**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_dual_space_schema.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_implicit_search.py tests\test_dual_space_search.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_hybrid_search.py tests\test_agents_phase_c.py tests\test_matching_explanation_benchmark.py tests\test_llm_concurrency.py -q
.\.venv\Scripts\python.exe -m pytest -q
```

**Day 1 Gate:**

- `DUAL_SPACE_ENABLED=false` 与无案例时保持显式-only 排序。
- `job-hidden` 即使有高隐式分也不能进入候选。
- 隐式证据充分时可以重排至少一组相近显式候选。
- 每条输出仍有 JD evidence；隐式 claim 有 case ID、阶段、置信度。
- 全量测试不得低于现有 112 项且全部通过。

**Commit boundary:** `feat: add evidence-grounded dual-space retrieval`

---

## Day 2：Run/Public API 与双层可解释性

**目标：** 让前端有稳定、可恢复、不会泄露内部 state 的契约。

**Files:**

- Create: `app/domain/run.py`
- Create: `app/domain/match_brief.py`
- Create: `app/domain/results.py`
- Create: `app/db/migrations/0002_run_lifecycle.sql`
- Create: `app/db/run_store.py`
- Create: `app/db/event_store.py`
- Create: `app/api/v1/__init__.py`
- Create: `app/api/v1/schemas.py`
- Create: `app/api/v1/router.py`
- Create: `app/api/v1/sessions.py`
- Create: `app/api/v1/runs.py`
- Create: `app/api/v1/feedback.py`
- Create: `app/api/result_projector.py`
- Create: `app/agents/trace.py`
- Modify: `app/api/main.py`
- Modify: `app/agents/orchestrator.py`
- Create: `scripts/export_openapi.py`
- Create: `tests/snapshots/openapi_v1.json`
- Test: `tests/test_match_brief.py`
- Test: `tests/test_run_store.py`
- Test: `tests/test_api_v1.py`
- Test: `tests/test_result_projector.py`
- Test: `tests/test_public_trace.py`

**Public route contract:**

```text
GET  /api/v1/capabilities
POST /api/v1/sessions
POST /api/v1/sessions/{session_id}/resume
GET  /api/v1/sessions/{session_id}/resume-preview
POST /api/v1/sessions/{session_id}/resume-confirm
POST /api/v1/sessions/{session_id}/match-brief
POST /api/v1/runs/{run_id}/execute
GET  /api/v1/runs/{run_id}/status
GET  /api/v1/runs/{run_id}/result
GET  /api/v1/runs/{run_id}/explain
POST /api/v1/runs/{run_id}/reaction
```

- [ ] **2.1 分离 Session 与 Run。** `session_id` 表示简历/用户交互会话；每次匹配生成独立 `run_id`，批准的 Match Brief 以 canonical JSON + `plan_hash` 保存。
- [ ] **2.2 复用现有状态并增加 run snapshot。** 不搬迁整个 `SharedState`；`match_runs` 保存 run 状态、阶段、approved plan、result snapshot、warnings、时间戳，`run_events` 只存 allow-list public payload。
- [ ] **2.3 增加确认门。** resume 未确认不能生成 brief；brief 有冲突/clarification 未解决不能 execute；execute 后 Supervisor 不得重写 hard constraints。
- [ ] **2.4 建立 typed DTO。** 每个 v1 route 声明 `response_model`；Legacy route 暂时保留但前端不得消费。
- [ ] **2.5 建立 Product Result Projector。** 输出唯一 `recommended_roles`、resume strategy、skill gaps、career path、warnings；拒绝任何 hard constraint 失败或无 JD evidence 的推荐。
- [ ] **2.6 建立 Examiner Explain。** 仅 evaluation capability 开启时返回 explicit/implicit rank、case IDs、融合参数、stage duration 和有界 recovery event；从不返回原始 prompt/state/log。
- [ ] **2.7 导出 OpenAPI snapshot。** 以后修改 route/DTO 必须同提交刷新 snapshot。

**Day 2 tests:**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_match_brief.py tests\test_run_store.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_api_v1.py tests\test_result_projector.py tests\test_public_trace.py -q
.\.venv\Scripts\python.exe scripts\export_openapi.py
.\.venv\Scripts\python.exe -m pytest tests\test_api_routes.py tests\test_api_concurrency.py -q
.\.venv\Scripts\python.exe -m pytest -q
```

**Day 2 Gate:**

- 两个 `session_id`、三个 `run_id` 并发执行时状态和结果不串。
- 旧 `plan_hash` execute 返回 409；同一 run 重复 execute 只有一次成功。
- Result/Explain JSON 中找不到 `user_id`、完整简历、`supervisor_log`、prompt、provider error。
- `completed_with_warnings` 可读结果；非终态 result 返回 409 和恢复提示。
- curl 可完成 preview → confirm → brief → execute → status → result/explain。

**Commit boundary:** `feat: add run-scoped public API and safe explanations`

---

## Day 3：React 前端完整 P0 流程

**目标：** 一天内完成答辩工作台，不做营销站和非关键设置页。

**Files:**

- Create: `frontend/package.json`
- Create: `frontend/package-lock.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/playwright.config.ts`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/app/App.tsx`
- Create: `frontend/src/app/router.tsx`
- Create: `frontend/src/app/providers.tsx`
- Create: `frontend/src/api/generated.ts`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/api/queries.ts`
- Create: `frontend/src/features/session/NewSessionPage.tsx`
- Create: `frontend/src/features/session/ResumeReviewPage.tsx`
- Create: `frontend/src/features/brief/MatchBriefPage.tsx`
- Create: `frontend/src/features/run/RunPage.tsx`
- Create: `frontend/src/features/results/ResultsPage.tsx`
- Create: `frontend/src/features/results/EvidenceDrawer.tsx`
- Create: `frontend/src/features/evaluation/EvaluationRunPage.tsx`
- Create: `frontend/src/features/feedback/ReactionForm.tsx`
- Create: `frontend/src/styles/tokens.css`
- Create: `frontend/src/styles/global.css`
- Create: `frontend/e2e/full-flow.spec.ts`
- Create: component and feature `*.test.tsx` files next to each page.

- [ ] **3.1 建立 typed client。** `openapi-typescript` 从 `tests/snapshots/openapi_v1.json` 生成类型；client 使用相对 `/api/v1`；核心响应不得使用 `any`。
- [ ] **3.2 完成上传与 Resume Review。** 标准 file input + dropzone；显示 skills/experience/education/projects/quality warnings/evidence；只有“确认简历”一个主 CTA。
- [ ] **3.3 完成 Goal/Match Brief。** 表单仅显示 career goal、locations、visa、role families、avoid roles、count；不显示 RAPTOR、latent、alpha、模型名。
- [ ] **3.4 完成轮询。** TanStack Query 读取 `retry_after_ms`，终态停止；刷新从服务器恢复；stale/failed 显示可执行恢复动作。
- [ ] **3.5 完成统一结果与 evidence。** 一个 recommendation list；岗位详情显示 JD evidence、resume evidence、must-have 命中、skill gaps；不得显示“97% 录用概率”。
- [ ] **3.6 完成 examiner view。** capability off 时 route 不可用；开启时显示显式/隐式排序、案例证据、融合权重、warning/recovery timeline。
- [ ] **3.7 完成最小可访问性。** 键盘可完成主流程；drawer 关闭后 focus 回触发项；375/768/1440px 无横向溢出；文本对比度达标。

**Day 3 tests:**

```powershell
npm --prefix frontend ci
npm --prefix frontend run api:generate
npm --prefix frontend run api:check
npm --prefix frontend test -- --run
npm --prefix frontend run build
```

**Day 3 Gate:**

- 非技术用户可在浏览器完成上传至查看 evidence 的完整流程。
- 页面刷新不会丢失已持久化 session/run 状态。
- 普通结果只有一份排序；研究字段只在 Evaluation View。
- loading、empty、warning、failed、stale 五类状态都有可理解界面。
- 单元测试和 production build 通过。

**Commit boundary:** `feat: add explainable career matching frontend`

---

## Day 4：P0 集成、确定性 Demo、评估与冻结

**目标：** 上午完成 E2E，下午只修 Gate，不再加入功能。

**Files:**

- Create: `app/llm/fake_provider.py`
- Create: `data/demo/provider_responses.json`
- Create: `data/demo/anonymous_cases.jsonl`
- Create: `scripts/seed_demo_data.py`
- Create: `scripts/evaluate_dual_space.py`
- Create: `scripts/release0_smoke.py`
- Create: `tests/test_dual_space_end_to_end.py`
- Create: `tests/test_evaluate_dual_space.py`
- Modify: `frontend/e2e/full-flow.spec.ts`
- Create: `docs/demo_runbook.md`
- Create: `docs/evaluation_protocol.md`
- Modify: `README.md`
- Modify: `.gitignore`

- [ ] **4.1 建立 deterministic provider。** 只替换 DeepSeek/Qwen 外部响应，真实调用 API、PostgreSQL store、dual-space retrieval、Agent orchestration 和 result projector。
- [ ] **4.2 建立两种演示场景。** cold start 保持 explicit-only；mature fixture 有足够匿名案例并产生可解释重排；两者 evidence ID 均可解析。
- [ ] **4.3 跑最小真实评估。** 输出 explicit-only 与 dual-space 的 Precision@K、Recall@K、MRR、NDCG@K、hard-constraint violation rate、evidence coverage；fixture 不独立时报告只写“mechanism demo”，不写“性能提升”。
- [ ] **4.4 做并发与故障注入。** 同时两个 session；latent timeout 降级；非法 JSON 最多一次 repair；严格地点不被放宽；result projection 拒绝无 evidence claim。
- [ ] **4.5 完成浏览器 E2E。** 从 `/new` 走到 results/evidence/evaluation/reaction；375 与 1440px 截图无重叠；键盘主流程通过。
- [ ] **4.6 冻结 P0。** 14:00 后只修 release gate；记录真实通过数量、运行模式和未实现项。

**P0 Release Gate:**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\export_openapi.py --check
npm --prefix frontend ci
npm --prefix frontend run api:check
npm --prefix frontend test -- --run
npm --prefix frontend run build
.\.venv\Scripts\python.exe scripts\release0_smoke.py --mode demo
npm --prefix frontend run test:e2e -- full-flow.spec.ts
git diff --check
git status --short
```

**P0 Definition of Done:**

- [ ] 上传 → 预览确认 → Brief 确认 → run → 结果 → evidence → reaction 全链路通过。
- [ ] 双空间真实读取与融合；implicit failure 明确降级为 explicit-only。
- [ ] hard constraint violation rate = 0。
- [ ] zero-evidence recommendation rate = 0。
- [ ] 普通用户看统一结果，答辩视图能解释两空间与 Supervisor。
- [ ] 两个并发用户不串 state；所有外部调用受 Semaphore 限流。
- [ ] deterministic demo 在无真实 API key 时可运行。
- [ ] 前后端测试、build、E2E 全通过。

**Commit boundary:** `release: deliver four-day explainable p0`

---

## Day 5：私有简历快照与严格去身份化

**目标：** 建立公共隐式空间的隐私边界；上传不等于发布。

**Files:**

- Create: `app/memory/anonymization.py`
- Create: `app/db/migrations/0003_private_snapshots.sql`
- Modify: `app/db/schema.sql`
- Modify: `app/memory/private_memory.py`
- Modify: `app/normalization/resume_intake.py`
- Modify: `app/state/schema.py`
- Test: `tests/test_resume_anonymization.py`
- Modify: `tests/test_resume_intake.py`
- Modify: `tests/test_memory_phase_e.py`

- [ ] **5.1 保存 immutable private snapshot。** intake 完成后写 `resume_snapshots`，在 `ResumeState` 只保存 `resume_version_id`；原始 evidence 继续留在私有空间。
- [ ] **5.2 递归删除身份字段。** 删除姓名、邮箱、电话、地址、证件号、学号、个人主页与 free-text 联系行。
- [ ] **5.3 保留职业证据。** 教育、专业、学校、实习/工作公司、岗位、项目、技能和描述必须保留；不得把所有公司名当 PII 删除。
- [ ] **5.4 生成 deterministic case ID/embedding text。** canonical JSON 哈希生成 case ID；同一匿名内容幂等；维度与 `EMBED_DIM` 校验。
- [ ] **5.5 锁定发布边界。** 上传、推荐、即时 reaction 均不得调用公共案例 upsert。

**Day 5 Gate:**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_resume_anonymization.py tests\test_resume_intake.py tests\test_memory_phase_e.py -q
.\.venv\Scripts\python.exe -m pytest -q
```

- PII fixture 序列化后无身份字段/模式。
- Tencent/学校/岗位/SQL/Python 等职业证据仍存在。
- 原始 evidence 私有可解析，公共匿名 payload 不含原始 evidence 文本集合。

**Commit boundary:** `feat: add private resume snapshots and strict anonymization`

---

## Day 6：申请事件、Consent 与匿名案例结果写路径

**目标：** 把现有薄标签反馈闭环改成正确的匿名简历结果闭环，同时保留其幂等与并发保证。

**Files:**

- Create: `app/db/migrations/0004_application_feedback.sql`
- Modify: `app/db/schema.sql`
- Create: `app/memory/application_tracking.py`
- Create: `app/memory/outcome_repository.py`
- Modify: `app/memory/case_base.py`
- Modify: `app/memory/feedback.py`
- Modify: `app/memory/feedback_loop.py`
- Modify: `app/agents/orchestrator.py`
- Modify: `app/api/v1/feedback.py`
- Modify: `app/api/routes.py`
- Test: `tests/test_application_tracking.py`
- Test: `tests/test_implicit_case_repository.py`
- Modify: `tests/test_feedback_loop.py`
- Modify: `tests/test_api_routes.py`

**Lifecycle:**

```text
recommendation
→ user confirms applied
→ application event: applied/screen/OA/interview/offer/joined/rejected/withdrawn
→ explicit learning consent
→ pending anonymous case candidate
→ review approval
→ anonymous_resume_cases + case_job_outcomes
```

- [ ] **6.1 分开三类事实。** recommendation、application、feedback event 使用不同表/ID；没有响应不等于 rejection。
- [ ] **6.2 阶段单调与幂等。** `screen_passed` 不能覆盖 `interview`；同 idempotency key 不重复；并发较高阶段胜出；joined 为终态。
- [ ] **6.3 收紧发布条件。** 必须同时满足 confirmed application、有效 stage、learning consent、review approval；此前只写 private/pending 区。
- [ ] **6.4 改造 closure。** 加载 application 对应 private snapshot → anonymize → upsert case → upsert outcome；不再发布 `CareerCase` skill tags。
- [ ] **6.5 保持兼容。** 旧 `POST /feedback` 作为 adapter 进入新 event service；不得保留两套 closure truth。
- [ ] **6.6 保存推荐事实。** orchestrator 完成后写 recommendation row，包含 resume version、explicit/implicit/final score，但不自动创建 application/case。

**Day 6 Gate:**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_application_tracking.py tests\test_implicit_case_repository.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_feedback_loop.py tests\test_api_routes.py -q
.\.venv\Scripts\python.exe -m pytest -q
```

- recommendation-only、reaction-only、no-response 均不创建公共案例。
- consent false 或 pending review 不发布。
- 已确认阶段 + consent + approval 只创建一个匿名 case/outcome。
- 现有 durable case truth 与原子 state merge 回归测试继续通过。

**Commit boundary:** `feat: persist consented anonymous hiring outcomes`

---

## Day 7：延迟回访、样例案例与 P1 前端入口

**目标：** 用可运行的 channel-neutral demo 证明反馈不是匹配完成后立即伪造出来的。

**Files:**

- Create: `app/db/migrations/0005_feedback_followups.sql`
- Modify: `app/db/schema.sql`
- Create: `app/integrations/feedback_channels.py`
- Create: `app/memory/followups.py`
- Create: `scripts/run_due_followups.py`
- Modify: `app/config.py`
- Modify: `.env.example`
- Modify: `scripts/seed_cases.py`
- Create: `data/cases/anonymous_resume_cases.jsonl`
- Create: `data/cases/case_job_outcomes.jsonl`
- Create: `frontend/src/features/feedback/ApplicationFeedbackPage.tsx`
- Create: `frontend/src/features/feedback/LearningConsent.tsx`
- Test: `tests/test_followups.py`
- Test: `tests/test_seed_implicit_cases.py`
- Add corresponding frontend tests.

- [ ] **7.1 建立 bounded scheduler 数据。** 推荐后按配置写 follow-up；只领取 due + consented 行；最大尝试 3；退订取消待发送项。
- [ ] **7.2 安全领取与发送。** 事务内 `FOR UPDATE SKIP LOCKED` 领取，提交后才调用 channel；网络 I/O 不持有 DB lock；outbox 保证两个 dispatcher 不重复发送。
- [ ] **7.3 实现 console adapter。** 一次脚本领取一个有限 batch 后退出；不使用跨天 `asyncio.sleep`，不集成真实微信凭据。
- [ ] **7.4 塞 10–20 条 fictional fixtures。** 覆盖 screen/OA/interview/offer/joined/rejection；无真实人物 PII；标记 `mechanism_demo` 和 `not_for_real_world_success_claims`。
- [ ] **7.5 补前端 P1 输入。** 用户明确确认是否申请、招聘阶段、optional reason、learning consent；不把 usefulness reaction 混成 application outcome。

**Day 7 Gate:**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_followups.py tests\test_seed_implicit_cases.py -q
npm --prefix frontend test -- --run src/features/feedback
npm --prefix frontend run build
.\.venv\Scripts\python.exe -m pytest -q
```

- 新推荐不会立即发送回访。
- 到期回访一次发送；失败按上限重试；opt-out 后不再发送。
- 两个 dispatcher 不重复投递同一 outbox row。
- fixtures 可被隐式检索命中但不支持真实录用概率主张。

**Commit boundary:** `feat: add delayed feedback mechanism demo`

---

## Day 8：P1 E2E、消融评估与最终 Gate

**目标：** 证明反馈确实能改变后续相似简历的辅助排序，并诚实说明证据边界。

**Files:**

- Create: `data/eval/implicit_case_split.json`
- Modify: `data/eval/evaluation_manifest.json`
- Modify: `scripts/evaluate_dual_space.py`
- Create: `scripts/demo_delayed_feedback_loop.py`
- Create: `tests/test_dual_space_evaluation.py`
- Create: `tests/test_dual_space_feedback_end_to_end.py`
- Modify: `docs/evaluation_protocol.md`
- Create: `docs/p1_acceptance.md`
- Modify: `README.md`
- Modify: `frontend/e2e/full-flow.spec.ts`

- [ ] **8.1 固定 train/test case split。** 同一简历、近重复模板或 query 自身 case 不跨 split；manifest 记录 corpus/case fixture hashes。
- [ ] **8.2 运行 explicit-only vs dual-space。** 报告 ranking metrics、implicit coverage、company+role evidence hit rate、hard violation、evidence coverage；所有指标限定 `[0,1]`。
- [ ] **8.3 演示完整 delayed feedback loop。** 初始 explicit-only → recommendation row → console follow-up → confirmed application/stage/consent → approval → anonymous case/outcome → 第二份相似简历取得隐式 evidence。
- [ ] **8.4 做故障与隐私复验。** implicit DB timeout 仍返回 explicit；PII 扫描通过；无 consent 不发布；重复事件不重复写；case 不能引入硬过滤岗位。
- [ ] **8.5 完成前后端 P1 E2E。** 浏览器提交申请阶段和 consent，管理员/demo CLI 批准，下一次匹配 examiner view 展示新 case provenance。
- [ ] **8.6 冻结论文主张。** 若独立数据不足，结论仅为“闭环机制可运行、证据可追溯”；只有 held-out 结果支持时才报告描述性 ranking delta，不写真实招聘成功率。

**P1 Final Gate:**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\demo_delayed_feedback_loop.py
.\.venv\Scripts\python.exe scripts\evaluate_dual_space.py --format table --table-k 5
.\.venv\Scripts\python.exe scripts\export_openapi.py --check
npm --prefix frontend ci
npm --prefix frontend run api:check
npm --prefix frontend test -- --run
npm --prefix frontend run build
npm --prefix frontend run test:e2e -- full-flow.spec.ts
git diff --check
git status --short
```

**P1 Definition of Done:**

- [ ] private memory、feedback、anonymous case base 三个 P1 模块均走真实 PostgreSQL 路径。
- [ ] 双空间是 public JD + public anonymous resume outcomes；private memory 不再被描述为第二 RAG 空间。
- [ ] 推荐、申请、阶段、reaction、consent 不混淆。
- [ ] 匿名案例无身份字段，保留职业相关公司/岗位/项目/技能证据。
- [ ] 阶段更新单调、幂等、并发安全；无响应绝不当拒绝。
- [ ] empty/disabled/failed implicit path 与 explicit-only 行为一致。
- [ ] 反馈后下一次相似简历能获得独立的 implicit evidence 和置信度受控重排。
- [ ] 评估无 train/test leakage，报告包含 scope 和 fixture truth 标签。
- [ ] 全量后端、前端、E2E、评估脚本全部通过。

**Commit boundary:** `release: complete eight-day p1 mechanism demo`

---

## 2. 每日固定节奏

```text
09:00–09:30  复读当天范围、git status、全量基线
09:30–12:00  第一个最小模块：失败测试 → 实现 → 定向通过
13:00–16:00  第二个最小模块：失败测试 → 实现 → 定向通过
16:00–18:00  当天纵向集成与全量回归
18:00–19:00  手动演示、文档、diff 检查、单一职责提交
```

发现前一日 Gate 未通过时，先修 Gate；不在失败基线上继续叠下一天核心功能。

---

## 3. 风险、降级线与不可砍项

### 第一优先级风险

| 风险 | 早期信号 | 当天处理 |
|---|---|---|
| 前端依赖/构建占用过多时间 | Day 3 上午仍未生成 typed client | 保留 React/TS/TanStack Query，只合并页面与组件，不删完整主流程 |
| run API 改造破坏 legacy tests | Day 2 中午旧 API 大量失败 | v1 使用 adapter 包现有 orchestrator，legacy route 保持不动 |
| live provider/DB 不稳定 | smoke 依赖网络或外部额度 | 切 deterministic fake provider；仍调用真实内部流水线 |
| 隐式案例数据不足 | confidence 始终低于阈值 | 使用明确标记的 fictional fixtures，仅声称机制演示 |
| P1 closure 并发回归 | 原 idempotency/durable truth 测试失败 | 停止新增 follow-up，先恢复已有并发与幂等保证 |

### 可以按顺序砍

1. Docker Compose、CI、TLS、账户、CSRF、配额、备份恢复。
2. Context Builder 与 typed Recovery extension；保留当前已测试的 bounded loops。
3. 前端视觉动画、完整五断点截图矩阵；至少保留 375/768/1440 和键盘流程。
4. 真实微信/邮件渠道；保留 console adapter + outbox 机制。
5. 复杂统计显著性；保留 leakage audit、指标表、样本数和诚实 scope 标签。

### 绝对不能砍

- SQL hard filters 和 explicit candidate authority。
- evidence IDs 与公共 allow-list projection。
- `session_id`/`run_id` PostgreSQL 隔离。
- Semaphore、asyncio、bounded loop。
- 完整前端主流程与 progress/result 恢复。
- explicit-only fallback。
- consent、匿名化、推荐≠申请、无响应≠拒绝。
- P0/P1 各自 Gate 的全量回归。

---

## 4. 论文与答辩映射

- **方法贡献：** Supervisor-guided explicit JD retrieval + confidence-gated anonymous outcome reranking。
- **可信性：** SQL hard constraints、JD/resume/case provenance、zero-evidence rejection、bounded recovery。
- **系统贡献：** FastAPI async/stateless service、PostgreSQL session/run state、React typed client、deterministic demo。
- **P1 机制贡献：** delayed feedback、strict anonymization、consent/review、monotonic outcome history。
- **评估主张：** P0 必报 retrieval metrics 与 evidence/hard-filter reliability；P1 必报 explicit-only vs dual-space 与 leakage audit。
- **不得声称：** 真实录用概率、真实公司成功率、公共 beta 已上线、生产级故障恢复、RAPTOR/cross-encoder 已进入主线。

---

## 5. Plan Self-review

- [x] 两份文档的共同硬约束均有对应 Gate。
- [x] 采用第一份文档的产品/API/前端骨架和第二份文档的双空间语义/隐私/反馈定义。
- [x] 当前仓库 112-test 基线被视为复用资产，没有安排无关重写。
- [x] P0 第 4 天包含前端与两层可解释性。
- [x] P1 第 8 天包含 private memory、feedback closure、anonymous case base、延迟回访 demo 与评估。
- [x] P2、public-beta hardening 和真实渠道集成均在关键路径之外。
- [x] 每天都有精确文件、接口、命令、验收和提交边界。
- [x] 无占位内容、开放式循环或无证据成功主张。
