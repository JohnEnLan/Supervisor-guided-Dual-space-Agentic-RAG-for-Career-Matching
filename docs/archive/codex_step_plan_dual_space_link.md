# Supervisor-guided Dual-space Career Agent 实施计划（重构版）

> **给执行本计划的 Codex：** 必须逐个 Step 执行。每个 Step 先写失败测试，再做最小实现，再运行该 Step 的定向测试和全量回归。验收失败时停止，不得提前实现后续 Step。
>
> **推荐执行方式：** 使用 `subagent-driven-development` 逐任务执行并在任务之间复核；也可以使用 `executing-plans` 在同一会话分批执行。所有 checkbox 都是实际进度，不得一次性批量勾完。
>
> **上下文控制：** 每次执行只读取“全局硬约束 + 当前 Phase + 当前 Step”，用 `rg -n "^# Phase|^## Step N"` 定位；不要在每个任务里反复把 2,000 多行全文塞进 Agent context。

**Goal：** 在不偏离一个月毕业设计范围的前提下，先交付可答辩、可复现、可评估的 Release 0，再以独立的 Release 1 把系统加固为可以小规模公开试用的产品。

**Architecture：** 后端继续使用 FastAPI、asyncio、PostgreSQL/pgvector 和轻量自研 Agent Harness。先建立稳定的 Session / Run / Event / Public DTO 契约，再将显式岗位检索与隐式案例检索汇合为一个带来源证据的推荐结果；前端只消费公开 DTO，不读取内部 `SharedState`。Release 0 允许明确标识的本地进程内执行模式，Release 1 必须切换到 PostgreSQL 持久任务与租约 worker。

**Tech Stack：** Python 3.11+、FastAPI、Pydantic v2、asyncpg、PostgreSQL + pgvector、DeepSeek、Qwen Embedding；前端使用 Vite + React + TypeScript、React Router、TanStack Query、OpenAPI 生成类型、Zod 表单校验、Lucide 图标、Vitest、Testing Library、Playwright；部署使用 Docker Compose 和同源反向代理。

---

## 1. 为什么替换旧计划

本文件完整取代旧版 Step 0–29，不应与旧步骤混合执行。旧版中的有效想法已经重新放入正确依赖位置；以下问题被明确修正：

1. API 契约必须早于前端，而不是前端完成后再补 TypeScript 类型。
2. 部署与最终验收必须放在 Agent Runtime、前端和 Demo 完成之后。
3. `session_id` 不能同时代表简历会话、匹配任务和结果；新增独立 `run_id`。
4. `session_state.user_id` 已存在，禁止再次按“缺列”处理；需要新增的是版本、确认状态和 run 级存储。
5. FastAPI `BackgroundTasks` 只允许用于 Release 0 的本地 Demo，不能被描述为多实例生产任务队列。
6. 普通求职用户不输入 API Key，也不需要理解 RAPTOR、latent、alpha 等研究参数。
7. 产品视图返回一份统一推荐；显式/隐式来源差异放在 examiner-only Evaluation View 中。
8. 公共 API 不返回原始 `SharedState`、`user_id`、完整 prompt、内部异常或原始 `supervisor_log`。
9. 正向反馈不会自动发布到公共案例库；匿名学习必须显式 opt-in，并先进入待审核区。
10. Vite 静态构建不依赖运行时注入 `VITE_API_BASE_URL`；正式部署统一走同源 `/api/v1`。

---

## 2. 全局硬约束

执行任一 Step 前，先读仓库根目录 `AGENTS.md` 和 `CLAUDE.md`。以下规则对所有 Step 生效：

- 状态按 Session / Run 存入 PostgreSQL，禁止把用户状态放进进程全局变量。
- 并发只使用 asyncio；禁止 threading、multiprocessing、LangGraph、AutoGen、CrewAI。
- LLM 与 embedding 继续经过现有 Semaphore；任何新增外部调用都必须有 timeout、错误分类和测试替身。
- 硬约束必须在 SQL / metadata 层执行；LLM 只能提出候选约束，不能替代硬过滤。
- 简历建议和岗位解释必须引用已有 evidence ID；没有证据的 claim 必须被丢弃或明确标成 unavailable。
- 所有循环有固定上限；默认最多一次修复或一次重新检索，禁止 `while True`。
- Release 0 不主动实现 RAPTOR 或 cross-encoder；已有 RAPTOR 仅用于研究开关和消融，不进入普通用户流程。
- API 路由必须声明 `response_model`；前端不得使用 `any` 读取核心响应。
- 任何 Step 修改 v1 request/response/route，都在同一 Step 重新导出并提交 OpenAPI snapshot；禁止等到前端报错才同步。
- 数据库变更使用编号 SQL migration，禁止只修改 `schema.sql` 而没有升级路径。
- 简历、JD、案例和 feedback 全部是不可信数据。Prompt 必须把它们放进明确 data boundary，并指示模型忽略其中的命令；绝不把数据内容拼进 system 指令层。
- 年龄、性别、种族、宗教、残障、婚姻等受保护属性不进入 ranking/context。签证和地点只能来自用户显式职业约束，不得由模型从国籍等信息推断。
- 新依赖必须锁入 lockfile；禁止在 `package.json` 使用 `latest`。
- 每个 Step 只修改列出的职责范围；遇到无关 dirty changes 时保留并绕开。
- 每个 Step 完成后运行 `git diff --check` 和 `git status --short`，确认无密钥、临时简历、构建产物或无关文件进入提交。

### 每个 Step 的固定测试节奏

```text
1. 写一个描述目标行为的失败测试。
2. 运行该测试，确认因缺少目标行为而失败。
3. 写最小实现。
4. 运行定向测试并确认通过。
5. 运行 python -m pytest tests -q。
6. 若涉及前端，再运行 npm test -- --run 和 npm run build。
7. 更新文档/契约，记录验收结果，然后才进入下一 Step。
```

---

## 3. 两条发布轨道

### Release 0：Dissertation MVP（必须先完成）

目标是答辩可演示、方法可解释、实验可复现：

- 服务端生成 Session，用户确认简历解析结果。
- Supervisor 生成 Match Brief，用户确认后才执行。
- 显式岗位空间与隐式案例空间走真实路径并生成统一排名。
- 每条推荐都能追溯岗位证据、简历证据和检索来源。
- Agent 有 task-specific context、typed recovery event 和有界失败恢复。
- React 前端跑通完整主流程，并提供独立 examiner-only Evaluation View。
- Demo 使用确定性 fixture，不依赖答辩现场的外部模型可用性。
- 完成 dual-space 主消融；时间允许且 Extension 完成时，再加入 context/recovery 消融与工程指标。

### Release 0 时间盒

为遵守一个月边界，执行优先级固定：

```text
R0 Core（必须）：Step 0–6、9–16
R0 Extension（主链跑通后再做）：Step 7 Context Builder、Step 8 Recovery 标准化
```

如果论文截止日期逼近，允许跳过 Step 7/8，继续使用当前已测试的 Agent payload 与 Supervisor bounded loops；此时 Step 11/论文必须删除 context/recovery 提升主张，只保留 dual-space 主贡献。禁止为了完成 Extension 延误可运行主线、评估和简单前端。Release 1 永远排在两者之后。

### Release 1：Small Public Beta（Release 0 验收后才开始）

目标是允许少量真实用户公开试用：

- HttpOnly opaque guest session 或账户会话，所有资源严格校验属主。
- PostgreSQL 持久任务队列、worker 租约、heartbeat、重启恢复和幂等执行。
- 用户配额、模型成本上限、速率限制、数据保留与删除。
- 结构化日志、健康检查、备份恢复演练、TLS 和发布回滚流程。

**禁止把 Release 1 的上线承诺写进论文实现章节，除非对应验收测试真的通过。**

---

## 4. 最终用户流程

```text
打开产品
  -> 新建 Session（服务端生成 session_id）
  -> 上传 PDF / DOCX / TXT
  -> 查看 Resume Preview（技能、经历、教育、原文 evidence）
  -> 确认解析正确，或重新上传
  -> 输入目标和用户能理解的约束
  -> Supervisor 生成 Match Brief
  -> 用户检查并确认 Match Brief
  -> 创建并执行 run_id
  -> 查看阶段进度与可恢复错误
  -> 查看统一推荐列表
  -> 展开岗位证据、简历证据、显式/隐式来源贡献
  -> 答辩/评估身份可选进入 Evaluation View 比较双空间路径
  -> Release 0：提交当前推荐是否有帮助的即时 reaction
  -> Release 1：回访提交申请结果，并单独选择是否允许匿名学习
  -> Release 1：隐私设置中查看保留策略或删除数据
```

普通用户流程中不显示 `include_raptor`、`include_latent`、fusion alpha、embedding model 或内部 Agent 名称。研究参数只存在于 `APP_EVALUATION_MODE=true`、服务端授权的 Evaluation View 和评估脚本。

---

## 5. 目标目录与职责

以下是计划完成后的目标结构。已有文件尽量原位演进，不做无关重构。

```text
app/
  api/
    main.py                       # lifespan、异常处理、挂载 /api/v1
    legacy_routes.py              # 旧端点临时兼容，Release 0 后评估删除
    v1/
      router.py                   # 只组合 feature routers
      schemas.py                  # 所有 public request/response DTO
      errors.py                   # ErrorEnvelope 与异常映射
      sessions.py                 # Session、上传、Resume Preview/Confirm
      runs.py                     # Match Brief、Execute、Status、Result、Explain
      feedback.py                 # 反馈与 learning consent
  agents/
    context_builder.py            # task-specific ContextPacket
    recovery.py                   # bounded recovery policy/decision
    trace.py                      # allow-list public trace projection
    orchestrator.py               # 按 run_id 执行并写事件
  domain/
    match_brief.py                # MatchBrief 与合并规则
    run.py                        # RunStatus、RunStage、MatchRun
    events.py                     # typed RunEvent
    results.py                    # unified result/domain models
  retrieval/
    latent_match.py               # case kNN + case_job_links 查询
    score_fusion.py               # 可配置、可评估的双空间融合
    dual_space.py                 # 显式/隐式编排，返回不可变结果
  memory/
    case_job_linker.py            # 预计算和单案例重建
    feedback_loop.py              # consent -> pending candidate，不自动发布
  db/
    migrations/
      0001_baseline.sql
      0002_run_lifecycle.sql
      0003_feedback_consent.sql
      0004_dual_space_and_job_metadata.sql
    migrate.py                    # 顺序执行 migration
    run_store.py                  # run snapshot、CAS transition、idempotency
    event_store.py                # append-only run events
    case_candidate_store.py       # 待审核案例
scripts/
  export_openapi.py
  build_case_job_links.py
  approve_case_candidate.py
  evaluate_dual_space.py
  seed_demo_run.py
frontend/
  src/
    app/                           # router、providers、route guards、AppShell
    api/                           # generated types、client、query hooks
    components/                    # Button、Stepper、Timeline、Drawer、states
    features/
      session/                     # upload + resume preview
      brief/                       # goal form + Match Brief review
      run/                         # progress
      results/                     # unified result + evidence
      evaluation/                  # dual-space trace，仅 examiner mode
      feedback/                    # feedback + consent
      privacy/                     # data lifecycle
    styles/                        # tokens、global、responsive rules
```

---

# Release 0：Dissertation MVP

# Phase A：契约与运行基础（Step 0–2）

## Step 0：冻结基线与建立执行记录

**目的：** 确认当前代码真实行为，避免计划继续依赖错误假设。

**读取：** `AGENTS.md`、`CLAUDE.md`、`README.md`、`app/state/schema.py`、`app/db/schema.sql`、`app/api/routes.py`、`app/agents/orchestrator.py`、`app/agents/supervisor.py`、`app/memory/case_base.py`、`app/memory/feedback_loop.py`。

- [ ] 运行 `python -m pytest tests -q`，把实际通过数和失败详情记录到 `docs/release0_baseline.md`；禁止写“预期 63+”之类会过期的数字。
- [ ] 运行 `git status --short`，在 baseline 文档中注明执行前已有的用户改动，后续不得覆盖。
- [ ] 用 `rg -n "BackgroundTasks|session_id|supervisor_log|search_similar_cases|run_feedback_closure" app tests` 记录现有调用点。
- [ ] 用 `rg -n "TODO|pass|NotImplemented" app tests` 区分真实缺口与 P2 占位。
- [ ] 在 baseline 中画出现有数据流，并明确四个断点：feedback closure 未接在线 API、private memory 未接、case search 未进主检索、API 返回 raw state。
- [ ] 确认 `.env` 被忽略，并运行 `git log --all -- .env`；若历史中出现 `.env`，停止并提示用户轮换密钥，不自行改写 Git 历史。

**验收：** baseline 文档包含测试结果、现有 dirty files、真实数据流和断点；本 Step 不改业务代码。

**建议提交：** `docs: record release 0 baseline`

---

## Step 1：数据库 migration、Session/Run/Event 基础契约

**依赖：** Step 0。

**目的：** 先分离 Session 与一次匹配运行，给前端、幂等、轨迹和 Release 1 worker 提供稳定主键。

**新增：**

- `app/db/migrations/0001_baseline.sql`
- `app/db/migrations/0002_run_lifecycle.sql`
- `app/db/migrate.py`
- `app/db/session_store.py`
- `app/db/run_store.py`
- `app/db/event_store.py`
- `app/domain/run.py`
- `app/domain/events.py`
- `tests/test_migrations.py`
- `tests/test_run_store.py`
- `tests/test_event_store.py`

**修改：** `app/db/schema.sql` 只用于全新安装的最终快照；migration 才是升级事实来源。

### 1.1 领域模型

在 `app/domain/run.py` 定义：

```python
class RunStatus(StrEnum):
    DRAFT = "draft"
    PLAN_READY = "plan_ready"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"
    CANCELLED = "cancelled"
    STALE = "stale"


class RunStage(StrEnum):
    PLAN = "plan"
    RETRIEVAL = "retrieval"
    STRATEGY = "strategy"
    VERIFICATION = "verification"
    FINALIZATION = "finalization"


class MatchRun(BaseModel):
    run_id: UUID
    session_id: str
    owner_id: UUID | None = None
    status: RunStatus
    stage: RunStage | None = None
    plan_version: int = 0
    approved_plan: dict = Field(default_factory=dict)
    state_version: int = 0
    created_at: datetime
    updated_at: datetime
```

在 `app/domain/events.py` 定义 allow-list event 结构：`event_id`、`run_id`、`event_type`、`stage`、`status`、`public_payload`、`created_at`。时间线按数据库生成的 `event_id` 排序，不手写 `MAX(sequence)+1`。公共 payload 禁止包含 prompt、完整简历、user_id、API key、数据库错误。

### 1.2 Migration

`0002_run_lifecycle.sql` 至少创建：

```sql
ALTER TABLE session_state
    ADD COLUMN IF NOT EXISTS version BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS resume_version INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS confirmed_resume_version INT,
    ADD COLUMN IF NOT EXISTS resume_content_hash TEXT,
    ADD COLUMN IF NOT EXISTS resume_confirmed_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS match_runs (
    run_id UUID PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES session_state(session_id) ON DELETE CASCADE,
    owner_id UUID,
    status TEXT NOT NULL,
    stage TEXT,
    plan_version INT NOT NULL DEFAULT 0,
    draft_plan JSONB NOT NULL DEFAULT '{}',
    approved_plan JSONB NOT NULL DEFAULT '{}',
    plan_hash TEXT,
    run_state JSONB NOT NULL,
    result_snapshot JSONB,
    state_version BIGINT NOT NULL DEFAULT 0,
    idempotency_key TEXT,
    error_code TEXT,
    warning_codes TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_match_runs_owner_idempotency
    ON match_runs(owner_id, idempotency_key)
    WHERE owner_id IS NOT NULL AND idempotency_key IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_match_runs_demo_idempotency
    ON match_runs(session_id, idempotency_key)
    WHERE owner_id IS NULL AND idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS run_events (
    event_id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES match_runs(run_id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    stage TEXT,
    status TEXT,
    public_payload JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_run_events_timeline
    ON run_events(run_id, event_id);
```

不要删除现有 `session_state.user_id`；它已经存在。

`migrate.py` 在读取文件前用固定 bootstrap SQL 创建 `schema_migrations` registry。`0001_baseline.sql` 是当前 `schema.sql` 的幂等基线，包含既有 extension、table 与 index：空数据库从 0001 顺序执行；已有数据库执行 0001 时由 `IF NOT EXISTS` 安全通过并记录。后续禁止新增比已应用版本更小的 migration。

### 1.3 Store 接口

```python
async def create_run(
    *, session_id: str, owner_id: UUID | None,
    initial_state: SharedState, idempotency_key: str | None,
) -> MatchRun: ...

async def load_run(run_id: UUID) -> tuple[MatchRun, SharedState] | None: ...

async def transition_run(
    *, run_id: UUID, expected: set[RunStatus],
    new_status: RunStatus, new_stage: RunStage | None = None,
    error_code: str | None = None,
) -> bool: ...

async def save_run_state(
    *, run_id: UUID, state: SharedState, expected_version: int,
) -> int: ...

async def append_run_event(
    *, run_id: UUID, event_type: str,
    stage: RunStage | None, status: RunStatus | None,
    public_payload: dict,
) -> RunEvent: ...
```

`save_run_state` 使用 compare-and-swap：`WHERE run_id=$1 AND state_version=$2`，更新成功后版本加一；0 行更新时抛出专用 `ConcurrentRunUpdate`，禁止悄悄覆盖。

`app/db/session_store.py` 提供：

```python
async def save_session_state(
    *, state: SharedState, status: str, expected_version: int,
) -> int: ...

async def replace_resume(
    *, session_id: str, resume_state: ResumeState,
    content_hash: str, expected_version: int,
) -> int: ...

async def confirm_resume(
    *, session_id: str, resume_version: int,
    excluded_item_ids: list[str], expected_version: int,
) -> int: ...

async def create_run_from_confirmed_session(
    *, session_id: str, idempotency_key: str | None,
) -> MatchRun: ...
```

`replace_resume` 原子增加 `resume_version` 并清空 confirmed version；`confirm_resume` 只确认当前版本；`create_run_from_confirmed_session` 在一个事务中验证 `confirmed_resume_version=resume_version`、复制 state 并创建 run，避免确认与重新上传竞态。现有 `state_store.py` 逐步改为兼容 wrapper，不再用于 v1 的盲覆盖写入。

### 1.4 测试

- [ ] migration 连续执行两次均成功，并只在 `schema_migrations` 记录一次。
- [ ] 登录模式同一 `(owner_id, idempotency_key)`、Demo 模式同一 `(session_id, idempotency_key)` 重复创建时返回同一 run 或明确 conflict，不生成两条记录。
- [ ] 非法状态转换 `completed -> running` 返回 false。
- [ ] 两个相同 expected_version 保存时只能一个成功。
- [ ] re-upload 与 confirm 并发时，旧 resume version 不能被确认。
- [ ] create run 与 re-upload 并发时，只能克隆事务中确认的版本，否则返回 conflict。
- [ ] 同一 run 的 event 按 `event_id` 稳定递增；并发 append 不需要计算自定义 sequence。
- [ ] 级联删除 Session 后 match_runs/run_events 一并删除。

**定向命令：** `python -m pytest tests/test_migrations.py tests/test_run_store.py tests/test_event_store.py -q`

**验收：** Session 和 Run 已分离；状态更新具备 CAS；事件是 append-only；旧测试仍通过。

**建议提交：** `feat: add session run and event persistence`

---

## Step 2：Public API v1 与 OpenAPI 单一事实来源

**依赖：** Step 1。

**目的：** 在任何前端代码之前锁定公开 DTO；不再把内部 `SharedState` 直接发给浏览器。

**新增：**

- `app/domain/constraints.py`
- `app/domain/match_brief.py`
- `app/domain/feedback.py`
- `app/domain/ids.py`
- `app/api/v1/__init__.py`
- `app/api/v1/router.py`
- `app/api/v1/schemas.py`
- `app/api/v1/errors.py`
- `scripts/export_openapi.py`
- `tests/test_api_v1_contract.py`
- `tests/test_call_timeouts.py`
- `tests/snapshots/openapi_v1.json`

**修改：** `app/api/main.py` 默认只挂载 `/api/v1`；现有 `app/api/routes.py` 改名/包装为 `legacy_routes.py`，仅在显式本地兼容模式下挂载。

### 2.0 先定义 canonical domain types

OpenAPI DTO 之前先定义内部单一事实来源，全部 `extra="forbid"`：

```python
class HardConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")
    locations: list[str] = Field(default_factory=list, max_length=5)
    need_visa_sponsor: bool | None = None
    degree_required: str | None = None
    max_required_years: int | None = Field(default=None, ge=0, le=50)


class SoftPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preferred_role_clusters: list[str] = Field(default_factory=list)
    title_keywords: list[str] = Field(default_factory=list)


class ApplicationOutcome(StrEnum):
    PASSED_SCREEN = "passed_screen"
    OA = "oa"
    INTERVIEW = "interview"
    INTERVIEW_1 = "interview_1"
    INTERVIEW_2 = "interview_2"
    FINAL_INTERVIEW = "final_interview"
    OFFER = "offer"
    REJECTED = "rejected"


class BriefConflict(BaseModel):
    field: str
    explicit_value: Any
    suggested_value: Any
    resolution: Literal["explicit_value_kept", "user_action_required"]


class MatchBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_version: int = Field(ge=1)
    career_goal: str
    hard_constraints: HardConstraints
    soft_preferences: SoftPreferences
    avoid_roles: list[str]
    result_count: int = Field(ge=3, le=10)
    needs_clarification: bool
    clarification_question: str | None
    conflicts: list[BriefConflict]
    plan_hash: str
```

`EvidenceId`/`ResumeEvidenceId`/`JobEvidenceId` 使用受约束字符串类型。Step 6 只消费这里定义的 `MatchBrief`，Step 9 实现生成与确认行为，消除依赖循环。

统一成功终态：`COMPLETED` 与 `COMPLETED_WITH_WARNINGS` 都可读取 result；只有后者额外显示 warnings。API friendly alias（例如 UI 的 “Screening passed”）只在 request adapter 转成 canonical outcome，内部不出现第二套枚举。

### 2.1 必须定义的 DTO

在 `schemas.py` 定义并给所有字段明确类型：

- `CreateSessionResponse`
- `ResumeUploadResponse`
- `ResumePreviewResponse`
- `ConfirmResumeResponse`
- `CreateMatchBriefRequest`
- `MatchBriefResponse`
- `ExecuteRunRequest`
- `ExecuteRunResponse`
- `RunStatusResponse`
- `RecommendedRoleView`
- `EvidenceView`
- `MatchResultResponse`
- `ExplainResponse`
- `FeedbackRequest`
- `FeedbackResponse`
- `RecommendationReactionRequest`
- `RecommendationReactionResponse`
- `CapabilitiesResponse`
- `ErrorEnvelope`

公共错误统一为：

```json
{
  "error": {
    "code": "resume_not_confirmed",
    "message": "Confirm the parsed resume before creating a match brief.",
    "recovery_hint": "Open the resume review step and confirm or upload a new file.",
    "trace_id": "..."
  }
}
```

禁止返回 Python exception、SQL、文件路径、模型 prompt 或 raw provider response。

### 2.2 v1 路由清单

先注册接口和 response model；具体业务在后续 Step 接通：

```text
POST   /api/v1/sessions
POST   /api/v1/sessions/{session_id}/resume
GET    /api/v1/sessions/{session_id}/resume
POST   /api/v1/sessions/{session_id}/resume/confirm
POST   /api/v1/sessions/{session_id}/match-briefs
POST   /api/v1/runs/{run_id}/execute
GET    /api/v1/runs/{run_id}
GET    /api/v1/runs/{run_id}/result
GET    /api/v1/runs/{run_id}/explain
POST   /api/v1/runs/{run_id}/feedback
POST   /api/v1/runs/{run_id}/reaction
GET    /api/v1/capabilities
```

路由处理器从一开始就调用明确的 service protocol，测试通过 dependency override 注入 fake service。尚未完成的真实 service 返回统一 `503 feature_not_ready`，禁止返回假的成功数据；后续 Step 逐个替换为真实实现。

### 2.3 Legacy 隔离

- 默认 app 不挂载 legacy root routes。
- 只有 `APP_MODE=demo`、`ENABLE_LEGACY_API=true` 且监听 loopback 时允许挂载。
- `APP_MODE=production` 检测到 legacy enabled 必须拒绝启动。
- legacy 测试直接构造隔离的 legacy router/app，不能以默认应用继续挂载旧端点为前提。
- README 标记旧 curl 为 deprecated，并给出 v1 替代流程。

`POST /sessions` 由服务端生成不可预测的 UUID/ULID 风格 ID。禁止客户端继续提交任意 `session_id` 创建资源。

Release 0 尚无浏览器身份时，后端在 `APP_MODE=demo` 内部设置 `SharedState.user_id="local-demo"` 且 `match_runs.owner_id=NULL`；该值不出现在公共 DTO。Release 1 用 actor UUID 作为属主，仍不接受浏览器提交 user_id。

### 2.4 OpenAPI 导出

`scripts/export_openapi.py` 从 FastAPI app 导出排序稳定的 `openapi_v1.json`。脚本不得启动数据库或调用外部 API。后续前端从该文件生成 TypeScript 类型。

### 2.5 最小外部调用边界

在新增 Agent 调用之前，给现有 `app/llm/deepseek.py` 和 `app/llm/qwen_embed.py` 接入 `app/llm/call_policy.py`：

- 配置 connect/read/total timeout；
- timeout、auth、rate-limit、provider 5xx 映射为 typed error；
- 本 Step 不做自动重试、budget 或 usage ledger，那些留在 Step 19；
- 仍经过原 Semaphore；
- provider 卡住时调用在 total timeout 内结束。

### 2.6 测试

- [ ] 每个 v1 路由都声明 response model。
- [ ] `/result` 响应 schema 中不存在 `resume_state`、`user_id`、`supervisor_log`。
- [ ] `/explain` schema 中不存在 raw prompt 或内部异常字段。
- [ ] 404、409、413、415、422、429 都映射为 ErrorEnvelope。
- [ ] OpenAPI 导出两次字节一致，避免无意义 drift。
- [ ] legacy API 测试保持通过；README 标记 legacy 为临时兼容。
- [ ] 默认 app 访问旧 `/resume`、`/result/{id}` 得到 404；production + legacy enabled 启动失败。
- [ ] canonical hard/soft constraints 和 outcome 拒绝未知字段/枚举。
- [ ] completed_with_warnings 与 completed 都被定义为 result-readable。
- [ ] mock provider 永不返回时，DeepSeek/Qwen 调用在配置 timeout 内抛 typed error。

**定向命令：** `python -m pytest tests/test_api_v1_contract.py -q`

**验收：** 前端所需契约已经稳定；核心响应没有 `dict[str, Any]` 逃逸；OpenAPI 可重复生成。

**建议提交：** `feat: define versioned public api contract`

---

# Phase B：可信数据入口与案例写路径（Step 3–5）

## Step 3：安全上传、Resume Preview 与用户确认

**依赖：** Step 2。

**目的：** 补上旧前端计划遗漏的“解析结果确认”。用户必须先看见系统理解了什么，再允许匹配。

**新增：**

- `app/api/v1/sessions.py`
- `app/normalization/resume_preview.py`
- `tests/test_resume_api_v1.py`
- `tests/test_resume_preview.py`

**修改：** `app/config.py`、`.env.example`、`app/state/schema.py`、`app/api/v1/router.py`。

### 3.1 上传边界

- `RESUME_MAX_BYTES` 默认 5 MiB，配置集中在 Settings。
- 只允许 `.pdf`、`.docx`、`.txt`；扩展名、声明 MIME 和最小 magic signature 必须相互合理。
- 按块读取并在超过限制时立即中止，禁止 `await file.read()` 把任意大文件整体放进内存。
- 临时文件使用服务端生成随机名，不使用用户 filename 或 session_id 拼路径。
- DOCX 作为 ZIP 先限制 entry 数量和解压后总大小，拒绝 zip bomb；PDF/DOCX 解析在 worker/task timeout 内运行。
- 解析完成后默认删除原始上传；Release 0 只保留 normalized state 与 evidence。保留原文件必须等 Release 1 的显式 consent。
- 解析失败写可恢复错误码，不把本地路径返回给用户。
- Release 0 可复用现有 `BackgroundTasks` 做 resume parse，但仅在 `APP_MODE=demo` 下；必须持久化 queued/running/ready/error 状态，Step 18 再替换为 durable work item。

### 3.2 Resume Preview

`build_resume_preview(state: SharedState) -> ResumePreviewResponse` 只返回：

- skills
- education summary
- experience summary
- project summary
- resume quality issues
- evidence snippets（稳定 ID + 最短必要文本）
- parser warnings
- `can_confirm`

每个 skill、education、experience、project 派生项都必须有稳定 `profile_item_id` 和对应 `evidence_ids`。ID 来自 canonical item 内容 + resume version 的确定性 hash，不使用数组位置；重新解析相同版本结果应稳定。

不返回 normalized full resume、内部 layout diagnostics 或 user_id。

### 3.3 确认规则

`POST /resume/confirm` 只接受当前最新 resume version。请求包含 `resume_version`；版本不一致返回 409，提示刷新 Preview。

Release 0 不做在线富文本简历编辑器。用户只能：

1. 确认解析结果；
2. 对 skill、education、experience、project 中明显错误的派生项做 include/exclude；
3. 或重新上传。

排除 skill 只影响派生 profile，不能删除原始 evidence。

### 3.4 测试

- [ ] 客户端无法指定 session ID；`POST /sessions` 每次生成不同 ID。
- [ ] `.exe`、伪装扩展名、超大文件返回 415/413 ErrorEnvelope。
- [ ] 路径穿越 filename 不影响临时路径。
- [ ] DOCX zip bomb / 异常压缩比被拒绝且不会耗尽内存或磁盘。
- [ ] Preview 只含 allow-list 字段。
- [ ] 未确认 resume 创建 Match Brief 返回 409。
- [ ] 旧 resume_version 确认返回 409。
- [ ] skill/education/experience/project 的 item-level exclude 只影响派生 profile，不删除 source evidence。
- [ ] 相同 resume version 重建 Preview 时 profile_item_id 稳定。
- [ ] 重新上传会清除旧 confirmed_at 并增加 resume_version。
- [ ] 成功或失败后临时文件都被清理。

**定向命令：** `python -m pytest tests/test_resume_api_v1.py tests/test_resume_preview.py -q`

**验收：** 用户能够创建 Session、上传、查看 Preview、确认或重新上传；未确认状态无法进入匹配。

**建议提交：** `feat: add safe resume review flow`

---

## Step 4：Feedback Consent 与待审核案例写路径

**依赖：** Step 1、Step 2；可与 Step 3 之后顺序执行，但必须早于在线自动学习。

**目的：** 接通反馈闭环，同时避免“拿到 offer 就自动发布公共案例”的隐私和数据污染风险。

**新增：**

- `app/db/migrations/0003_feedback_consent.sql`
- `app/db/case_candidate_store.py`
- `scripts/approve_case_candidate.py`
- `tests/test_feedback_consent.py`
- `tests/test_case_candidate_store.py`

**修改：** `app/memory/feedback_loop.py`、`app/api/v1/feedback.py`、`app/db/schema.sql`。

### 4.1 请求契约

`FeedbackRequest` 增加：

```python
outcome: Literal[
    "passed_screen", "oa", "interview", "interview_1",
    "interview_2", "final_interview", "offer", "rejected"
]
reason: str | None = Field(default=None, max_length=1000)
user_rating: int | None = Field(default=None, ge=1, le=5)
allow_anonymous_learning: bool = False
```

学习 consent 必须默认 false，且不能从上一次反馈继承。

这是“用户之后回来报告真实申请结果”的接口，不是 Release 0 结果页上的即时评价。Release 0 结果页调用独立 `/reaction`：`helpful: bool`、`reason: str | None`、`job_id`；reaction 不进入案例学习。

### 4.2 待审核表

`case_candidates` 保存匿名化候选及审核状态：

```text
candidate_id UUID
source_feedback_id
status = pending | approved | rejected
anonymized_payload JSONB
pii_scan JSONB
created_at / reviewed_at
```

候选 payload 不存姓名、邮箱、电话、地址、完整简历或可逆 session hash。`case_id` 使用随机 UUID，不再由 `session_id` hash 生成。

### 4.3 闭环行为

```text
always: feedback_memory 落库
if consent=false: stop, event=feedback_saved
if outcome 非正向: stop, event=feedback_saved_not_eligible
if consent=true and eligible:
  -> deterministic PII scan
  -> Supervisor eligibility check
  -> case_candidates(status=pending)
  -> event=case_candidate_created
manual approval script:
  -> 再做 PII guard
  -> upsert career_cases
  -> 记录 case approved；link 构建由 Step 5 接入
```

Release 0 不制作管理员 UI；审批脚本足够。任何 PII scan 不通过都不得进入 `career_cases`。

审批事务成功后删除或不可逆清空 candidate 中的 `source_feedback_id`、原始审核输入和任何来源映射，只保留不含身份的审核结果摘要。否则“匿名案例”仍能通过 candidate 表追溯到用户。

### 4.4 Private Memory 决策

删除旧计划中“每次匹配成功自动写 private_memory”的要求。Release 0 默认不长期保留私有简历版本；Release 1 加入明确的 profile retention consent 后再接入。

### 4.5 测试

- [ ] consent=false 时只保存反馈，不创建 candidate。
- [ ] consent=true + rejected 时不创建 candidate。
- [ ] consent=true + offer/interview 且资格通过时创建 pending candidate。
- [ ] payload 出现邮箱/电话时被拒绝。
- [ ] approve 脚本幂等；重复审批不创建重复 case；本 Step 不依赖尚未存在的 linker。
- [ ] case_id 与 session_id/user_id 没有可见关联。
- [ ] feedback closure 失败不让反馈 API 500，但写入 typed warning event。

**定向命令：** `python -m pytest tests/test_feedback_consent.py tests/test_case_candidate_store.py -q`

**验收：** 反馈写路径真实贯通，默认不学习，公共案例只来自显式 consent + 审核通过的数据。

**建议提交：** `feat: gate case learning behind consent and review`

---

## Step 5：`case_job_links` 预计算与可追溯 provenance

**依赖：** Step 4；审批脚本与本 Step 完成后再接 link rebuild。

**目的：** 将隐式案例到显式岗位的关联离线化，同时保留构建版本与证据，供解释和消融使用。

**新增：**

- `app/db/migrations/0004_dual_space_and_job_metadata.sql`
- `app/memory/case_job_linker.py`
- `scripts/build_case_job_links.py`
- `tests/test_case_job_linker.py`

**修改：** `scripts/approve_case_candidate.py`、`scripts/load_jobs.py`、`app/db/schema.sql`。案例审批成功后调用本 Step 的单案例 linker，失败时保留 approved case、记录 `case_link_build_failed`，并允许 CLI 重建。

### 5.1 表结构

```sql
CREATE TABLE IF NOT EXISTS case_job_links (
    case_id TEXT NOT NULL REFERENCES career_cases(case_id) ON DELETE CASCADE,
    job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    score DOUBLE PRECISION NOT NULL,
    rank INT NOT NULL,
    evidence_chunk_ids TEXT[] NOT NULL DEFAULT '{}',
    embedding_model TEXT NOT NULL,
    build_version TEXT NOT NULL,
    built_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (case_id, job_id, build_version)
);

CREATE INDEX IF NOT EXISTS idx_case_job_links_lookup
    ON case_job_links(case_id, build_version, rank);

ALTER TABLE jobs
    ADD COLUMN IF NOT EXISTS source_url TEXT,
    ADD COLUMN IF NOT EXISTS source_name TEXT,
    ADD COLUMN IF NOT EXISTS listed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS work_type TEXT;
```

同一案例可保留不同 build_version，评估脚本必须显式选择版本；在线服务使用 Settings 中指定的 active version。

`load_jobs.py` 只在来源数据实际提供字段时映射 metadata。`source_url` 只接受 `http`/`https`；无 URL 的岗位仍可用于论文检索，但产品 DTO 标记为 dataset-only，不能显示误导性的 Apply 动作。

### 5.2 Linker 接口

```python
@dataclass(frozen=True)
class CaseJobLinkBuildResult:
    case_id: str
    build_version: str
    linked_jobs: int


async def build_case_job_links(
    *, case_id: str, top_n: int,
    build_version: str, embedding_model: str,
) -> CaseJobLinkBuildResult: ...
```

实现要求：

- 直接读取 `career_cases.embedding`，不重复调用 embedding API。
- 对 `job_chunks` 做 dense 检索并聚合到 job 级。
- 存储贡献最大的 evidence chunk IDs。
- 在单个事务中删除该 case/build_version 旧 links 后重建，保证幂等。
- 不带用户地点、签证等个人硬约束；这些必须在线查询时重新过滤。
- 不调用 LLM。

### 5.3 CLI

```text
python scripts/build_case_job_links.py --all --build-version v1 --top-n 20
python scripts/build_case_job_links.py --case-id case-001 --build-version v1
```

缺少 case、embedding 维度不匹配、没有开放岗位时输出明确错误码并非零退出；不得静默生成空缓存。

### 5.4 测试

- [ ] job chunk 聚合后按最高/聚合分数稳定排序。
- [ ] evidence_chunk_ids 来自真实命中 chunk。
- [ ] 重建同一版本不产生重复行。
- [ ] 新 build_version 不覆盖旧实验版本。
- [ ] linker 不调用 embedding 或 LLM。
- [ ] approve case 后只重建该 case 的 active version。

**定向命令：** `python -m pytest tests/test_case_job_linker.py -q`

**验收：** seed cases 能建立非空 links；每条 link 有版本和 evidence provenance；重复运行幂等。

**建议提交：** `feat: precompute versioned case job links`

---

# Phase C：双空间检索（Step 6）

## Step 6：Dual-space Retrieval 与统一排序模型

**依赖：** Step 5。

**目的：** 让显式岗位空间和隐式案例空间走真实在线路径，但对产品只输出一份可解释推荐列表。

**新增：**

- `app/retrieval/latent_match.py`
- `app/retrieval/score_fusion.py`
- `app/retrieval/dual_space.py`
- `app/domain/results.py`
- `tests/test_latent_match.py`
- `tests/test_score_fusion.py`
- `tests/test_dual_space.py`

**修改：** `app/retrieval/hybrid_search.py`、`app/memory/case_base.py`。只提取可复用硬过滤、embedding-based case search 与 query context；不得重写已经通过测试的 BM25/dense/RRF 主体。

### 6.1 不可变领域结果

在 `app/domain/results.py` 定义：

```python
class SourceContribution(BaseModel):
    source: Literal["bm25", "dense", "rrf", "raptor", "latent_case"]
    raw_score: float
    normalized_score: float
    rank: int | None = None


class DualSpaceCandidate(BaseModel):
    job_id: str
    final_score: float
    explicit_score: float
    latent_score: float
    contributions: list[SourceContribution]
    latent_case_ids: list[str] = Field(default_factory=list)
    evidence_span_ids: list[str] = Field(default_factory=list)
    hard_constraints_passed: bool


class DualSpaceRetrievalResult(BaseModel):
    candidates: list[DualSpaceCandidate]
    explicit_count: int
    latent_count: int
    fusion_alpha: float
    active_link_version: str
    warnings: list[str] = Field(default_factory=list)
```

函数返回新对象，禁止显式和隐式 coroutine 同时修改同一个 `SharedState`。

### 6.2 Query Context 与 embedding 复用

新增一个 run 内不可变 `RetrievalQueryContext`，至少包含 query text、query embedding、hard constraints、soft preferences。显式 dense 和 case kNN 使用同一个 query embedding；禁止依赖进程全局 LRU 才避免重复调用。

在 `hybrid_search.py` 保留现有兼容入口，并增加最小适配：

```python
async def build_retrieval_query_context(
    *, state: SharedState, approved_plan: MatchBrief,
) -> RetrievalQueryContext: ...

async def hybrid_search_with_context(
    *, context: RetrievalQueryContext, top_k: int,
) -> list[JobCandidate]: ...

def build_hard_filter_query(
    hard_constraints: dict[str, Any],
) -> tuple[str, list[Any]]: ...

async def hard_filter_job_ids(
    pool, hard_constraints: dict[str, Any],
) -> list[str]: ...
```

旧 `hybrid_search(...)` 作为 wrapper 构建 context 后调用新函数；原 `_build_hard_filter_query` / `_hard_filter_ids` 暂时作为兼容 alias 或 wrapper，等所有调用迁移后再删除，保证现有测试不被一次性打断。

在 `case_base.py` 增加：

```python
async def search_similar_cases_by_embedding(
    query_embedding: list[float], *, top_k: int = 5,
) -> list[dict[str, Any]]: ...
```

现有 `search_similar_cases(query: str)` 只负责调用 `embed_one(query)` 后委托新函数；latent path 直接调用 embedding 版本，从而保证同一 run 只 embed 一次且不复制 case kNN SQL。

旧计划中的全局 embedding LRU 改为 Release 1 可选优化。Release 0 优先保证同一 run 内复用、隐私隔离和确定性。

### 6.3 Latent Match

```python
async def search_similar_cases(
    *, query_embedding: list[float], top_cases: int,
) -> list[SimilarCase]: ...

async def lookup_linked_jobs(
    *, case_ids: list[str], hard_constraints: dict,
    build_version: str, top_jobs: int,
) -> list[LatentJobCandidate]: ...

async def latent_match(
    *, query: RetrievalQueryContext,
    top_cases: int, top_jobs: int, build_version: str,
) -> LatentMatchResult: ...
```

`lookup_linked_jobs` 必须 JOIN `jobs` 并重新应用地点、签证、学历、经验、开放状态等硬过滤。空案例库或空 links 返回 typed warning 和空结果，不让显式路径失败。

### 6.4 融合规则

使用可配置且可记录的线性融合，不在代码里散落 magic number：

```text
explicit_norm = per-run min-max/rank normalization
latent_norm   = per-run min-max/rank normalization
final_score   = (1 - alpha) * explicit_norm + alpha * latent_norm
```

归一化规则必须写成纯函数并覆盖边界：空列表返回空；只有一个值或所有值相等时，所有已有候选归一化为 `1.0`；不得产生除零或 NaN。

- Release 0 默认 `alpha=0.20`，仅作为待消融的起始值，不宣称最优。
- 显式分数缺失时按 0 处理；latent-only 岗位只有在能取得真实 JD evidence 且通过硬过滤时才可保留。
- 最终排序必须稳定：`final_score desc, explicit_score desc, job_id asc`。
- 每个候选保留 explicit/latent raw rank，Evaluation View 才能还原路径差异。
- 普通结果文案不说“历史上一定成功”，只说“匿名案例相似性提供了辅助信号”。

### 6.5 并发边界

`dual_space_retrieve()` 使用 `asyncio.gather` 并行显式和隐式查询，但两个分支只读 query context 并返回结果。融合完成后由调用方一次性写入 run state。

隐式分支异常时：

- 显式结果继续；
- `warnings` 增加 `latent_path_unavailable`；
- 写入 public event，但不暴露 SQL/provider message；
- run 最终可成为 `completed_with_warnings`。

显式分支异常时不得用 latent-only 假装完整结果；run 失败并返回 `explicit_retrieval_failed`。

### 6.6 测试

- [ ] query embedding 在两个路径间只生成一次。
- [ ] latent SQL 包含全部硬过滤和 `is_open=true`。
- [ ] 多案例命中同一 job 时去重且保留所有贡献 case IDs。
- [ ] alpha=0 等价 explicit-only；alpha=1 的行为可预测。
- [ ] 排序在相同输入下确定性一致。
- [ ] latent 异常时 explicit 结果保留并有 warning。
- [ ] explicit 异常时整体失败。
- [ ] 所有最终岗位都有 JD evidence 且 `hard_constraints_passed=true`。

**定向命令：** `python -m pytest tests/test_latent_match.py tests/test_score_fusion.py tests/test_dual_space.py -q`

**验收：** 双空间真实在线运行；只输出一个统一候选集合；provenance 足以支持解释和消融。

**建议提交：** `feat: add explainable dual space retrieval`

---

# Phase D：Agent Runtime 与公共解释（Step 7–10）

## Step 7：Evidence-preserving Context Builder

**优先级：** R0 Extension。只有 Core 的 Step 0–6 已通过才开始。

**依赖：** Step 6 的结果模型；可以在接编排前独立完成。

**目的：** 把各 Agent 自行拼接 prompt payload 的方式改为明确的 task-specific context packet，降低无关 token，并记录保留了哪些 evidence。

**新增：**

- `app/agents/context_builder.py`
- `tests/test_context_builder.py`

**修改：** `app/config.py`、`.env.example`；各 Agent 的接入放在本 Step 最后逐个完成。

### 7.1 ContextPacket

```python
class ContextManifest(BaseModel):
    packet_type: str
    included_evidence_ids: list[str]
    dropped_sections: list[str]
    estimated_characters: int
    budget_characters: int


class ContextPacket(BaseModel):
    payload: dict
    manifest: ContextManifest
```

提供四个纯函数：

```python
def build_intent_context(state, user_goal_text, budget) -> ContextPacket: ...
def build_matching_context(state, candidates, approved_plan, budget) -> ContextPacket: ...
def build_strategy_context(state, recommendations, budget) -> ContextPacket: ...
def build_verification_context(state, claims, budget) -> ContextPacket: ...
```

### 7.2 选择优先级

- Intent：用户原始目标、已确认技能/经历摘要、明确约束；不包含完整 supervisor log。
- Matching：approved Match Brief、候选 JD evidence、必要简历摘要；候选按 retrieval rank 截断。
- Strategy：最终推荐、技能缺口、原始 resume evidence；没有 evidence 的建议不得进入 prompt。
- Verification：claims + evidence IDs + hard constraints；不重新塞完整简历和全部 JD。

禁止使用简单 `text[:2500]` 随意截断 evidence。预算不足时按完整 evidence unit 丢弃，并把丢弃情况写入 manifest。

### 7.3 安全与观测

- Context builder 采用 allow-list 字段。
- 所有 resume/JD/case 文本都包装为带 source/type/evidence ID 的 untrusted data block；system prompt 明确数据中的指令无效。
- Context selection 丢弃受保护属性字段，不从姓名、国籍、毕业年份推断年龄或签证需求。
- manifest 可记录大小与 evidence IDs，但不记录完整 prompt 文本。
- `supervisor_log` 最多只转换为必要的 typed recent decisions；不直接传整段 log。
- Settings 提供每类 packet 的 budget；测试使用小 budget 验证确定性裁剪。

### 7.4 Agent 接入顺序

一次只替换一个 Agent，并在每次替换后跑其原测试：

1. Intent Agent；
2. Matching Agent；
3. Strategy Agent；
4. Supervisor planning/final verification。

输出 schema 和业务语义保持不变。本 Step 不顺便改 prompt 文案或模型参数。

### 7.5 测试

- [ ] 相同输入生成相同 packet 和 manifest。
- [ ] budget 超限时只丢完整 section/evidence，不截断 ID 对应文本。
- [ ] Strategy packet 保留所有被引用 resume evidence IDs。
- [ ] Verification packet 不含未使用的完整 resume。
- [ ] payload 递归扫描不到 API key、DATABASE_URL、user_id。
- [ ] evidence 文本包含“ignore previous instructions”等注入语句时仍只被当作数据，输出 schema/约束不改变。
- [ ] protected-attribute fixture 不进入 matching/strategy context。
- [ ] 替换后 Agent 输出结构测试全部保持通过。

**定向命令：** `python -m pytest tests/test_context_builder.py tests/test_agents_phase_c.py -q`

**验收：** 四类 Agent 使用可测试的 context policy；context 大小和 evidence 保留情况可量化。

**建议提交：** `refactor: add evidence preserving agent contexts`

---

## Step 8：Typed Bounded Recovery Policy

**优先级：** R0 Extension。Step 7 跳过时本 Step 也跳过，保留现有 bounded Supervisor 行为。

**依赖：** Step 1 Event Store、Step 7 Context Builder。

**目的：** 把散落的 clarification、JSON 修复、重新检索和 fabrication repair 整理为有边界的策略；失败时明确决定 fail、degrade 或 continue。

**新增：**

- `app/agents/recovery.py`
- `tests/test_recovery_policy.py`

**修改：** `app/agents/base.py`、`app/agents/supervisor.py`。本 Step 只让 Agent/Supervisor 返回 typed `RecoveryDecision`；Step 9 负责把 decision 持久化为 run event。

### 8.1 Recovery 类型

```python
class RecoverySite(StrEnum):
    GOAL_CLARIFICATION = "goal_clarification"
    STRUCTURED_OUTPUT_REPAIR = "structured_output_repair"
    RETRIEVAL_RELAXATION = "retrieval_relaxation"
    UNSUPPORTED_CLAIM_DROP = "unsupported_claim_drop"
    LATENT_PATH_DEGRADE = "latent_path_degrade"


class RecoveryOutcome(StrEnum):
    RECOVERED = "recovered"
    DEGRADED = "degraded"
    FAILED = "failed"


class RecoveryDecision(BaseModel):
    site: RecoverySite
    action: str
    reason_code: str
    attempt: int
    max_attempts: int
    outcome: RecoveryOutcome
    public_message: str
```

### 8.2 固定策略表

| Site | 最大次数 | 成功后 | 再失败时 |
|---|---:|---|---|
| goal clarification | 1 次用户补充 | 重新生成 brief | 阻止 execute，要求用户重写目标 |
| structured output repair | 1 次模型修复 | 继续当前 stage | Intent/Matching 失败则 run failed；Strategy 可 completed_with_warnings |
| retrieval relaxation | 1 次，只放宽 soft preference | 重新检索 | 保留较少结果并 warning，不放宽 hard constraint |
| unsupported claim drop | 1 次确定性过滤 | 删除无证据 claim | 结果为空则 strategy warning |
| latent path degrade | 0 次重试 | 使用 explicit | completed_with_warnings |

禁止“一律返回原 state 然后继续”。每个 stage 必须显式声明下游是否能接受缺失输出。

### 8.3 Structured JSON 修复

LLM 响应先经过 Pydantic schema 校验。失败时允许一次修复调用，输入只包含 validation errors 和原始响应的最小必要部分；仍然经过原 Semaphore 和 timeout。第二次失败按策略表终止或降级。

### 8.4 Event 写入

Step 9 接入 run-scoped orchestrator 后，每个 stage 至少写：

```text
stage_started
stage_completed | stage_failed
recovery_triggered（如果发生）
```

public payload 只含 reason code、用户可理解消息、attempt/max；内部 provider 错误写结构化服务日志，不放进 run_events。

### 8.5 测试

- [ ] 第一次非法 JSON、修复后合法，只发生一次 recovery。
- [ ] 两次非法 Intent JSON，run failed，不继续 retrieval。
- [ ] Strategy 两次失败，已有岗位仍返回，状态 completed_with_warnings。
- [ ] too few results 只清除 soft preferences，不改地点/签证等 hard constraints。
- [ ] unsupported advice 被删除且记录 evidence reason。
- [ ] latent failure 不触发 LLM 重试。
- [ ] 每个 loop 的 attempt 永远不超过 max_attempts。

**定向命令：** `python -m pytest tests/test_recovery_policy.py tests/test_agents_phase_c.py -q`

**验收：** 所有恢复点有明确上限和失败语义；Explain 能消费 typed event，不再解析任意 dict log。

**建议提交：** `feat: standardize bounded agent recovery`

---

## Step 9：Match Brief（Plan Confirm）与 run-scoped Orchestrator

**依赖：** Step 1、Step 2、Step 6。若 Step 7/8 已完成则使用 ContextPacket/RecoveryDecision；若按时间盒跳过，则适配现有 Agent/Supervisor 接口，不重新实现它们。

**目的：** 将 Supervisor planning 变为用户可确认的 Match Brief，并让批准后的 plan 成为一次 run 的不可变输入。

**新增：**

- `app/api/v1/runs.py`
- `tests/test_match_brief.py`
- `tests/test_run_orchestrator.py`

**修改：** `app/agents/orchestrator.py`、`app/agents/supervisor.py`、`app/api/v1/router.py`。

### 9.1 用户请求与合并优先级

用户可理解字段：

```python
class CreateMatchBriefRequest(BaseModel):
    career_goal: str = Field(min_length=10, max_length=2000)
    target_locations: list[str] = Field(default_factory=list, max_length=5)
    needs_visa_sponsorship: bool | None = None
    preferred_role_clusters: list[str] = Field(default_factory=list, max_length=5)
    avoid_roles: list[str] = Field(default_factory=list, max_length=10)
    result_count: int = Field(default=5, ge=3, le=10)
```

普通请求不包含 RAPTOR/latent/alpha。研究脚本通过服务层参数或 research-only endpoint 控制。

Brief 合并规则必须确定：

1. 用户显式表单值优先；
2. 已确认 resume profile 提供事实；
3. Intent Agent 只能补充缺失 soft preference；
4. Supervisor 可提出 clarification，但不能覆盖显式 hard constraint；
5. 冲突被列入 `conflicts`，必须由用户确认。

Public DTO 到内部 canonical key 的映射集中在 `match_brief.py`，不得让不同模块各自猜字段名：

```text
target_locations           -> hard_constraints["locations"]
needs_visa_sponsorship     -> hard_constraints["need_visa_sponsor"]
preferred_role_clusters    -> soft_preferences["preferred_role_clusters"]
avoid_roles                -> MatchBrief.avoid_roles
```

`soft_preferences` 是 MatchBrief/Public DTO 名称；调用现有 retrieval 时在一个 adapter 中映射为当前参数名 `soft_prefs`。

### 9.2 MatchBrief 模型

直接复用 Step 2 的 `app/domain/match_brief.py::MatchBrief`，不得在 API 或 orchestrator 再定义 dict 版本。Step 9 只负责生成字段、处理 conflict、递增 version 和计算 hash。

`plan_hash` 由 canonical JSON 计算。`POST /runs/{run_id}/execute` 必须提交 plan_version + plan_hash；过期或被修改返回 409。

计算 hash 时排除 `plan_hash` 自身，包含 `plan_version` 和所有会影响执行的 canonical 字段；JSON key 排序、Unicode/空白规则固定，并用测试锁定。

### 9.3 编排阶段

```text
Create Match Brief:
  clone confirmed Session state -> create run(draft)
  Intent Agent -> Supervisor planning
  persist MatchBrief -> plan_ready

Execute:
  CAS plan_ready -> queued
  demo backend schedules run
  queued -> running/retrieval
  dual_space_retrieve
  Matching/Strategy
  final verification + bounded recovery
  persist verified run_state
  completed | completed_with_warnings | failed
```

Execute 之后不再重新 planning，不允许 Supervisor 覆盖用户批准的 plan。

本 Step 只完成经过验证的内部 run state。Step 10 接入安全 Result Projector 后，再把 `build result_snapshot` 插入 finalization 与终态之间；因此本 Step 的 `/result` 仍可返回 `503 feature_not_ready`，不得临时返回 raw state。

### 9.4 Release 0 执行后端

允许 `EXECUTION_BACKEND=in_process_demo` 使用 BackgroundTasks，但必须：

- Settings 默认仅在 `APP_MODE=demo` 可启用；
- README 明确只能绑定 localhost 或受控答辩环境；
- Status Response 返回 `execution_durability="process_local"`；
- 服务启动时把遗留 queued/running demo run 标为 stale，而不是假装继续；
- Release 1 Gate 检测到该模式时禁止公网启动。

### 9.5 测试

- [ ] 显式 location/visa 不被 LLM suggestion 覆盖。
- [ ] vague goal 最多产生一个 clarification question。
- [ ] plan_hash 稳定，字段变化会改变 hash。
- [ ] 过期 plan_version execute 返回 409。
- [ ] 同一 run 两次 execute 只一个成功，另一个 409。
- [ ] approved plan 原样进入 retrieval。
- [ ] 每个 stage 保存 run state 和 event。
- [ ] latent degrade 得到 completed_with_warnings。
- [ ] restart recovery 将 demo queued/running 标为 stale，provider timeout 不留下永久 running。

**定向命令：** `python -m pytest tests/test_match_brief.py tests/test_run_orchestrator.py -q`

**验收：** 上传确认 -> Match Brief -> 用户批准 -> run 执行全链路可通过 API 完成；plan 不能被二次覆盖。

**建议提交：** `feat: add confirmed match brief execution`

---

## Step 10：统一 Result Projection、Evidence 与 Public Explain

**依赖：** Step 9。

**目的：** 为用户和论文演示提供两种清晰视图：产品视图回答“推荐什么、为什么”，examiner-only Evaluation View 回答“双空间和 Supervisor 做了什么”。两者都不能泄露内部状态。

**新增：**

- `app/api/result_projector.py`
- `app/agents/trace.py`
- `tests/test_result_projector.py`
- `tests/test_public_trace.py`

**修改：** `app/api/v1/runs.py`。

同时修改 `app/agents/orchestrator.py` 的 finalization：先从 verified run state 构建并持久化 `result_snapshot`，成功后才转为 completed；projection 发现 hard constraint/evidence 不变量被破坏时，run 必须 failed，不得发布半安全结果。

### 10.1 产品 Result

`GET /api/v1/runs/{run_id}/result` 在 `completed` 或 `completed_with_warnings` 返回；后者必须带非敏感 warnings：

```text
summary
recommended_roles[]            # 一份统一排序
  job_id/title/company/location/tier
  work_type/deadline/listed_at
  source_name/source_url/listing_kind
  concise_explanation
  why_this_match[]             # 普通语言理由，不含算法术语
  evidence[]                   # JD evidence
  resume_evidence[]            # 仅与建议相关的片段
resume_strategy[]
skill_gaps[]
career_path[]
warnings[]
```

产品 DTO 不返回 final_score、explicit/latent badge 或 `hard_constraints_passed` 这样的内部字段；满足约束的岗位可以显示普通文案 “Matches your must-haves”。所有岗位在内部必须有 `hard_constraints_passed=true`；否则 projector 直接拒绝构建并让 run failed。

`source_url` 仅在通过 http/https allow-list 校验后返回。存在有效 URL 时 UI 可显示 “View original listing”；否则 `listing_kind="dataset_only"`，UI 明确说明这是用于匹配研究的数据集记录，需要用户另行验证，不显示 Apply。

### 10.2 Research Projection

Explain response 增加 `evaluation` 区块，但只有 `APP_EVALUATION_MODE=true` 且服务端授权时返回：

- explicit rank / normalized score
- latent rank / normalized score
- contributing anonymized case IDs 与简短 background type
- fusion alpha / link build version
- recovery decisions
- context manifest 统计
- stage duration

不返回 career case 的原始来源用户，也不返回完整 prompt。

`GET /explain` 在 run 未完成时也可返回当前已有的 allow-list events，响应明确 `partial=true`；Research 的最终分数/案例贡献只有结果完成后才出现。`GET /result` 仍只接受完成终态。

### 10.3 Public Trace allow-list

```python
def build_public_trace(
    run: MatchRun, events: list[RunEvent]
) -> ExplainResponse: ...
```

只转换已知 event type；未知 event 忽略并记服务日志。使用 allow-list，不做“递归搜索 api_key 再删除”的 deny-list 方案。

### 10.4 Evidence 规则

- 岗位解释只引用该岗位的 JD evidence IDs。
- Resume revision 只引用 original resume evidence IDs。
- Evidence 文本由 ID 在可信 state 中解析，不接受 LLM 返回的新文本。
- 缺失 ID 时对应 claim 不进入产品响应，并产生 warning。

### 10.5 测试

- [ ] Result 中只有一份 ordered recommendations。
- [ ] Result/Explain 序列化后不存在 user_id、完整简历、supervisor_log、prompt、provider error。
- [ ] 每条 recommendation 至少一个 JD evidence。
- [ ] 每条 resume advice 至少一个合法 resume evidence。
- [ ] evaluation mode/authorization off 时不返回内部来源分数。
- [ ] 未知 event type 不穿透 API。
- [ ] completed_with_warnings 可读取 result；其他非完成 run 请求 result 返回 409 + recovery hint。
- [ ] 重新导出 OpenAPI snapshot，Result/Explain/Capabilities 字段与 projector 一致且无 drift。

**定向命令：** `python -m pytest tests/test_result_projector.py tests/test_public_trace.py -q`

**验收：** 用户结果可直接消费；Evaluation View 足以讲清双空间和 Supervisor；公共响应无 raw state 泄露。

**建议提交：** `feat: add safe result and explain projections`

---

# Phase E：评估与论文证据（Step 11）

## Step 11：真实消融、可靠性指标与论文证据

**依赖：** Step 6、Step 10。Context/Recovery 实验只有在 Extension Step 7/8 完成时启用。

**目的：** 让论文评估真正调用生产路径，而不是把 latent 文本 hint 拼进 query。

**新增：**

- `scripts/evaluate_dual_space.py`
- `app/evaluation/engineering_metrics.py`
- `tests/test_evaluate_dual_space.py`
- `docs/evaluation_protocol.md`
- `data/eval/dual_space_validation.jsonl`
- `data/eval/dual_space_test.jsonl`
- `data/eval/reliability_scenarios.jsonl`

**修改：** `scripts/evaluate_system.py` 保留兼容入口，但调用新 evaluator；`app/evaluation/metrics.py` 复用现有 ranking metrics。

### 11.1 固定实验矩阵

先做 leakage audit：当前 seed cases 与 `resume_queries.jsonl` 共享人工 background archetype，只能作为 smoke fixture，禁止用于“dual-space 提升 ranking”的最终统计。建立与 case seed 独立来源/独立改写的 validation 与 held-out test；同一简历、模板或近重复背景不能跨 split。

```text
A. explicit-only                 alpha = 0
B. explicit + latent             alpha = 0.20
C. explicit + latent alpha sweep alpha = 0.10 / 0.20 / 0.30
D. context full-state baseline   ContextPolicy.FULL_STATE_BASELINE
E. context evidence-selected     ContextPolicy.EVIDENCE_SELECTED
F. recovery disabled             max attempts = 0
G. bounded recovery              当前策略
```

RAPTOR 继续作为独立可选消融，不与 dual-space 主贡献混在一个变量里。

Alpha 只在 validation split 选择一次；锁定后对 test split 运行一次。禁止看 test 结果后回调 alpha。样本不足或无法证明独立时，结论降级为“机制可运行与可评估”，不声称 ranking 提升。

两种 context policy 都由 `context_builder.py` 实现并返回相同 `ContextPacket` 类型；禁止为了实验长期保留一套旧 Agent payload 代码。`FULL_STATE_BASELINE` 只用于评估，生产配置拒绝启用。

如果 Step 7/8 被时间盒跳过，矩阵只执行 A–C，并从论文删除 context/recovery 效果主张；不能用未实现功能填表。

### 11.2 指标

检索效果：

- Recall@K、Precision@K、MRR、NDCG@K
- hard constraint violation rate
- evidence coverage rate
- result coverage / novelty（latent 新增但相关的岗位比例）

Agent 可靠性：

- run completion rate
- completed_with_warnings rate
- recovery trigger/success rate
- unsupported claim drop rate
- zero-evidence recommendation rate（必须为 0）
- hard-constraint preservation under injected failures
- evidence factuality / recommendation quality rubric score

工程指标：

- 每 stage duration
- embedding/LLM call count
- context character/token estimate
- end-to-end latency
- estimated model cost（只在配置了单价时输出，不硬编码供应商价格）

### 11.3 可复现性

- 输入 dataset、label、case link build_version、模型名、alpha、随机 seed 写入报告 metadata。
- evaluator 不修改在线数据库；需要写临时 ranking 时写到独立 output path。
- mock/offline 模式必须能在无 API key 环境运行测试。
- live 模式缺少 API key 或 case links 时 fail fast，不输出伪造的“成功报告”。
- 对 ranking 指标报告 paired per-query delta；样本允许时给 bootstrap confidence interval，否则明确样本量与描述性结论，不只报平均数。
- `reliability_scenarios.jsonl` 固定注入：第一次非法 JSON、latent timeout、too-few-results、unsupported claim。Recovery off/on 使用完全相同的输入和 fake provider responses。
- Context policy 比较除了字符/token 估计，还用固定 rubric 评估 factuality、evidence correctness、recommendation usefulness 和 hard-constraint preservation。
- Match Brief 若要写成用户体验贡献，至少记录小规模用户测试的 plan correction rate、完成时间和错误约束发现数；没有用户研究时只写系统设计。

### 11.4 论文主张边界

论文主贡献最多聚焦：

1. Supervisor-guided dual-space retrieval；
2. evidence-preserving context + bounded recovery（仅在 Step 7/8 和对应质量评估完成时作为贡献）。

Trace、前端、Docker 属于系统工程贡献，不与算法提升混为一谈。Plan Confirm 的价值可通过少量用户研究或 constraint correction 记录说明，不强行包装成离线 ranking 提升。

### 11.5 测试与验收

- [ ] with-latent 分支 mock 断言调用 `dual_space_retrieve`，不拼 latent hint 文本。
- [ ] leakage audit 能识别 seed/query 近重复；final evaluator 拒绝使用 smoke fixture 生成 efficacy 报告。
- [ ] alpha 只从 validation 读取，test runner 不接受重新调参。
- [ ] alpha=0 报告与 explicit baseline 一致。
- [ ] 缺 link build version 时 live evaluator 拒绝运行。
- [ ] 报告 metadata 完整并可 JSON 序列化。
- [ ] zero-evidence recommendation rate 计算正确。
- [ ] 相同 fixture + seed 生成相同指标。
- [ ] failure-injection 场景在 recovery off/on 间输入完全一致，并输出 paired outcome。

**定向命令：** `python -m pytest tests/test_evaluate_dual_space.py tests/test_metrics.py -q`

**验收：** 能生成 explicit vs dual-space 的真实对比；实验配置完整；论文不再引用与实现脱节的 latent 结果。

**建议提交：** `feat: align dual space evaluation with runtime`

---

# Phase F：前端完整流程（Step 12–14）

## Step 12：Frontend Foundation、生成式 API Client 与设计系统

**依赖：** Step 2 Public API、Step 10 Result/Explain DTO。

**目的：** 建立轻量、可测试、不会猜后端字段的前端工程；先完成契约和路由状态机，再写业务页面。

**新增目录：** `frontend/`。

### 12.1 技术选择

使用：

- Vite + React + TypeScript；
- React Router；
- TanStack Query 负责 server state、轮询与缓存；
- `openapi-typescript` + `openapi-fetch` 从 `openapi_v1.json` 生成类型和 client；
- Zod 只负责表单输入和必要的边界校验，不手写一套与 OpenAPI 重复的响应类型；
- Lucide React 提供图标；
- Vitest、Testing Library、Playwright 提供测试。

安装时选择兼容的稳定版本并提交 `package-lock.json`。`package.json` 禁止出现 `latest`；Docker/CI 使用 lockfile 的 `npm ci`。

### 12.2 目录

```text
frontend/
  package.json
  package-lock.json
  vite.config.ts
  playwright.config.ts
  src/
    main.tsx
    app/
      App.tsx
      router.tsx
      providers.tsx
      routeGuards.ts
      AppShell.tsx
    api/
      generated.ts
      client.ts
      queries.ts
      errors.ts
    components/
      Button.tsx
      IconButton.tsx
      FlowStepper.tsx
      StatusTimeline.tsx
      EvidenceDrawer.tsx
      ErrorState.tsx
      EmptyState.tsx
      LoadingSkeleton.tsx
    features/
      session/
      brief/
      run/
      results/
      research/
      feedback/
      privacy/
    styles/
      tokens.css
      global.css
```

每个 feature 目录包含页面、局部组件、schema 和测试；禁止把所有页面逻辑塞进 `App.tsx`。

### 12.3 API 生成链

`package.json` 提供：

```json
{
  "scripts": {
    "api:generate": "openapi-typescript ../tests/snapshots/openapi_v1.json -o src/api/generated.ts",
    "api:check": "npm run api:generate && git diff --exit-code -- src/api/generated.ts",
    "test": "vitest",
    "build": "tsc -b && vite build",
    "test:e2e": "playwright test"
  }
}
```

`client.ts` 使用相对地址 `/api/v1`，不把 API key 或 base URL 存 localStorage。Vite dev server 通过 proxy 转发 `/api` 到本地 FastAPI；生产由同源反向代理转发。

### 12.4 路由与状态守卫

```text
/new                                  上传 + Resume Review（同一页面分阶段）
/sessions/:sessionId/match             目标输入 + “Review your search”
/runs/:runId                            先显示进度，完成后原位切换产品结果
/evaluation/runs/:runId                 examiner-only Evaluation View
/settings/privacy                       Release 1 才注册
```

`routeGuards.ts` 根据服务器状态决定合法页面：未确认 resume 不能进入 Brief，未完成 run 不能进入 Result。浏览器返回时保留已提交表单和滚动位置；禁止只靠前端内存判断流程状态。

前端从 `/api/v1/capabilities` 获取 demo/evaluation/privacy 能力；不能直接读取后端环境变量，也不能只靠隐藏菜单保护 examiner route。

### 12.5 视觉与交互规则

产品是工作台，不是营销 landing page：

- 首屏直接“新建匹配 / 打开 Demo”，没有巨型 Hero。
- 使用安静的 flat UI、清晰边界和适中信息密度；页面 section 不做漂浮卡片。
- 卡片仅用于重复岗位项，圆角最大 8px；禁止 card 内再嵌套 card。
- 使用系统字体栈，避免答辩现场依赖远程字体。
- 颜色以 neutral surface 为主，teal 作为主操作色，blue 表示 evidence，amber 表示 warning，red 表示 destructive；禁止整页被单一紫色/蓝色系支配。
- 所有控件使用语义 token，不在组件里散落 hex。
- icon button 使用 Lucide、固定尺寸和 tooltip；结构图标不使用 emoji。
- 一个页面只有一个 primary CTA。
- 表单有可见 label；错误显示在字段附近并用 `role="alert"`。
- focus ring 可见；普通文本对比度至少 4.5:1；颜色不是唯一状态信号。
- 提供 skip link、`header/nav/main` landmarks；route 变化后把 focus 移到主标题。
- 进度变化使用节制的 `aria-live="polite"`，只宣布 stage 变化，不在每次轮询重复播报。
- 动画只用于状态变化，150–200ms，支持 `prefers-reduced-motion`。
- 320、375、768、1024、1440px 均无横向溢出；200% text 和 400% zoom 可重排；移动端主要操作触点至少 44px。

建议 token 起点：

```css
:root {
  --color-bg: #f7f8fa;
  --color-surface: #ffffff;
  --color-text: #17212b;
  --color-muted-text: #52606d;
  --color-border: #d9e0e7;
  --color-primary: #0f766e;
  --color-evidence: #2563eb;
  --color-warning: #b45309;
  --color-danger: #b91c1c;
  --radius-sm: 4px;
  --radius-md: 8px;
}
```

实现前用对比度工具验证，不因示例 hex 通过就跳过检查。

### 12.6 测试

- [ ] `api:generate` 可运行，生成文件无手工修改。
- [ ] API schema 改变会让 `api:check` 失败。
- [ ] AppShell 与所有 route 可按需懒加载。
- [ ] route guard 根据 mocked server status 重定向正确。
- [ ] API error 被转换为统一 UI error，不白屏。
- [ ] 键盘可依次访问主导航和 CTA。
- [ ] Playwright 在 320/375/768/1024/1440 宽度打开 `/new` 无横向滚动。
- [ ] 200% text、400% zoom、route-change heading focus、skip link 和 restrained aria-live 通过可访问性回归。

**定向命令：**

```text
cd frontend
npm ci
npm run api:check
npm test -- --run
npm run build
```

**验收：** 空前端工程可构建；类型来自 OpenAPI；路由状态机、设计 token 和基础可访问性已建立。

**建议提交：** `feat: scaffold typed career agent frontend`

---

## Step 13：Upload -> Resume Review -> Match Brief 前端流程

**依赖：** Step 3、Step 9、Step 12。

**目的：** 完成用户做出第一次匹配之前的全流程，并保证返回、刷新和错误恢复都不会丢状态。

**新增：**

- `frontend/src/features/session/NewSessionPage.tsx`
- `frontend/src/features/session/ResumeUpload.tsx`
- `frontend/src/features/session/ResumeReviewPage.tsx`
- `frontend/src/features/brief/GoalForm.tsx`
- `frontend/src/features/brief/MatchBriefPage.tsx`
- 对应 `*.test.tsx`

### 13.1 New Session 与上传

```text
GET /new
  -> POST /sessions
  -> 选择文件
  -> 前端检查 extension/size（后端仍是最终边界）
  -> POST /sessions/{id}/resume
  -> 状态进入 parsing
  -> 轮询 Preview endpoint
  -> ready 后跳 Resume Review
```

要求：

- dropzone 不是唯一入口，必须有标准 file input。
- 上传中禁用重复提交并显示确定状态。
- 413/415 显示具体修复动作。
- 刷新后可根据 session 恢复轮询。

### 13.2 Resume Review

页面为不嵌套卡片的分区布局：Skills、Experience、Education、Projects、Quality Warnings、Evidence Preview。

用户可：

- 对误识别的 skill、education、experience、project 项做 include/exclude；
- 展开 evidence 查看原文；
- 点击“Use another file”；
- 点击唯一 primary CTA “Confirm resume”。

不提供自由改写 evidence 或在线简历编辑，避免破坏证据一致性。确认后显示不可编辑摘要；需要变更必须重新上传并生成新 version。

### 13.3 Goal Form

主表单只展示用户能理解且后端数据支持的字段：

- Career goal（必填）；
- Target locations；
- Need visa sponsorship（Yes / No / Not sure）；
- Preferred role families；
- Roles to avoid；
- Number of recommendations（默认 5，放在 Advanced 中）。

不显示 RAPTOR、latent、alpha、top cases 或模型选择。

表单使用可见 label，失焦后校验；多错误时顶部显示 error summary 并聚焦第一个错误。未提交草稿保存在 sessionStorage，只保存目标表单，不保存简历正文或认证 secret。

### 13.4 Match Brief Review

用户看到：

- confirmed goal；
- hard constraints；
- preferences；
- roles to avoid；
- recommendation count；
- conflicts/clarification（如有）。

用普通语言说明 hard 与 preference 的区别。用户修改任何字段后重新请求 Brief，旧 plan_hash 立即失效。只有 `needs_clarification=false` 且 conflicts 已处理时启用 “Confirm and match”。

### 13.5 测试

- [ ] 非允许文件在前端被拦截且 file input 仍可重选。
- [ ] 上传状态从 queued -> parsing -> preview ready 后跳转。
- [ ] 刷新 Resume Review 能从服务器恢复数据。
- [ ] 排除 skill 后 evidence 仍存在。
- [ ] 未确认 resume 访问 Brief 被 route guard 送回 review。
- [ ] goal 为空或过短时不发 API 请求。
- [ ] clarification 展示并允许一次补充。
- [ ] 修改 plan 后使用旧 hash 的 execute 错误能提示重新确认。
- [ ] 完成 execute 后跳转 `/runs/:runId`，该页面先显示 progress，完成后原位切换 result。

**定向命令：** `cd frontend && npm test -- --run src/features/session src/features/brief`

**验收：** 一个新用户能从 `/new` 走到 run queued；每一步知道下一步，错误时有明确恢复动作。

**建议提交：** `feat: add reviewed resume and match brief flow`

---

## Step 14：Progress、统一 Results、Evaluation View、Reaction

**依赖：** Step 2、Step 9、Step 10、Step 12。Step 4 的长期 application outcome API 不阻塞 Release 0 reaction UI。

**目的：** 完成长任务体验、推荐消费、方法解释与反馈闭环。

**新增：**

- `frontend/src/features/run/ProgressPage.tsx`
- `frontend/src/features/run/RunPage.tsx`
- `frontend/src/features/run/RunTimeline.tsx`
- `frontend/src/features/results/ResultsPage.tsx`
- `frontend/src/features/results/RecommendationList.tsx`
- `frontend/src/features/results/RecommendationDetail.tsx`
- `frontend/src/features/results/ResumeStrategy.tsx`
- `frontend/src/features/research/EvaluationRunPage.tsx`
- `frontend/src/features/feedback/ReactionForm.tsx`
- 对应单元测试与 `frontend/e2e/full-flow.spec.ts`

### 14.1 Progress Polling

`RunStatusResponse` 必须提供 `status`、`stage`、`updated_at`、`retry_after_ms`、`warnings`、`execution_durability`。

TanStack Query 轮询规则：

- 使用后端 `retry_after_ms`，默认 2 秒；
- completed、completed_with_warnings、failed、cancelled、stale 停止；
- 页面隐藏时降低频率，不创建多重 interval；
- 网络短暂失败指数退避，恢复后继续；
- `updated_at` 长时间不变时显示“可能停滞”，不伪造百分比；
- failed/stale 显示 reason code 和重新开始/返回 Brief 的动作。

Timeline 使用稳定 stage，不把每个内部 LLM call 暴露给用户：Preparing -> Retrieving -> Building strategy -> Verifying -> Ready。Recovery 以简短 warning 行显示。

### 14.2 产品 Results

桌面布局：

```text
结果摘要与 warning band
分段控制：Recommendations | Resume strategy | Career path
主区域：统一 recommendation list
右侧固定 detail panel（窄屏改为 drawer）
```

每个岗位项显示 title、company、location、tier、简短解释和 evidence count。不要显示算法来源 badge、explicit/latent rank 或两份 Top-K；这些只属于 examiner Evaluation View。

有效 `source_url` 使用带 ExternalLink 图标的 “View original listing”；dataset-only 岗位显示非阻塞说明并隐藏申请动作。展示 deadline/freshness 时必须允许 unknown，不能把缺失日期当作仍然开放。

Detail 展示：

- JD evidence；
- resume evidence；
- “Why this match” 的证据化摘要；
- “Matches your must-haves”；
- skill gaps。

结果页用简短说明标明这是职业决策支持，不保证面试或录用；匿名案例相似性只是辅助信号。说明放在结果摘要附近，不用模态框阻断主流程。

普通结果不显示归一化 ranking score，更不能伪装成 97%“匹配概率”。原始/归一化分数只在 Evaluation View 中按明确定义展示。

### 14.3 Examiner-only Evaluation View

前端先调用 `/api/v1/capabilities`；只有服务端返回 `evaluation_view=true` 且当前部署允许 examiner access 时才显示入口。Release 0 的本地答辩模式可开启，Release 1 必须增加服务端授权，不能只靠 Vite build flag 隐藏。展示：

- explicit/latent rank 对照表；
- fusion alpha 与 link build version；
- contributing anonymized cases；
- context manifest；
- bounded recovery timeline；
- stage duration。

Evaluation View 不是普通结果 tab，普通 job-seeker API 也不返回研究字段。所有表格支持键盘、可排序时使用 `aria-sort`，颜色以外还用文字/图标区分来源。

### 14.4 Release 0 Reaction

岗位 Detail 内提供“Was this recommendation useful?”，用户选择 Yes/No 和 optional note。提交到 `/reaction`，只衡量当前结果可用性，不宣称申请结果，也不触发案例学习。

application outcome、长期回访历史和 learning consent 的普通用户 UI 延后到 Release 1 身份/历史建立后。Step 4 的 outcome API 在 Release 0 仅用于受控机制测试或 CLI 演示。

### 14.5 测试

- [ ] polling 不重复创建 timer，终态停止。
- [ ] stale/failed 有可执行恢复动作。
- [ ] completed_with_warnings 仍显示结果和 warning。
- [ ] Results 只有一份 recommendation list。
- [ ] 点击岗位后 detail panel/drawer 展示对应 evidence。
- [ ] latent contribution 为空时不显示 badge，页面不报错。
- [ ] Evaluation route 在 capability off 时返回 Not Found；只改前端 flag 不能绕过后端。
- [ ] reaction 不创建 case candidate；Step 4 application feedback 的 consent 仍默认 false。
- [ ] 键盘可打开/关闭 drawer，关闭后 focus 回到触发按钮。
- [ ] 320/375/768/1024/1440px 截图无重叠、截断和横向滚动。
- [ ] 200% text 与 400% zoom 下 recommendation/detail 可重排；不依赖横向滚动阅读正文。
- [ ] route 变化聚焦主标题；进度 aria-live 只在 stage 变化时播报。

**定向命令：**

```text
cd frontend
npm test -- --run src/features/run src/features/results src/features/research src/features/feedback
npm run test:e2e -- full-flow.spec.ts
```

**验收：** 上传到 reaction 的主流程完整；用户结果清楚，Evaluation View 能讲论文方法，移动端和键盘操作可用。

**建议提交：** `feat: deliver explainable matching results workflow`

---

# Phase G：可复现 Demo 与 Release 0 验收（Step 15–16）

## Step 15：确定性 Demo、同源 Docker 部署、CI

**依赖：** Step 11、Step 13、Step 14。

**目的：** 让答辩和代码审查不依赖外部模型临时可用，并让另一台机器能够按 README 复现。

**新增：**

- `scripts/seed_demo_run.py`
- `app/llm/fake_provider.py`
- `data/demo/provider_responses.json`
- `data/demo/` 下最小、去身份化 fixture
- `app/api/v1/health.py`
- `frontend/Dockerfile`
- `frontend/nginx.conf`
- 根目录 `Dockerfile`
- `docker-compose.yml`
- `.github/workflows/ci.yml`
- `scripts/release0_smoke.py`
- `docs/demo_runbook.md`
- `tests/test_health_endpoints.py`

**修改：** `.env.example`、`.gitignore`、`README.md`、`app/api/main.py`。

### 15.1 Deterministic Real-workflow Demo

Demo 的主要路径必须调用真实 v1 API、Session/Run store、dual-space retriever 和 orchestrator，只把 DeepSeek/Qwen 换成确定性 fake provider。`provider_responses.json` 按 operation + fixture ID 返回合法响应，也包含一次可恢复非法 JSON/latent failure 场景。

`seed_demo_run.py` 写入虚构但完整的输入依赖：

- demo jobs/chunks；
- anonymized seed cases；
- case_job_links；
- fake provider response fixtures。

`APP_MODE=demo` 时首页显示 “Run guided demo”，从上传测试简历开始走完整流程，不调用真实供应商。可以另外保留“Open emergency snapshot”，但必须显著标注它只验证结果渲染，不算 E2E 验收。生产模式必须隐藏两种入口并拒绝 demo fixture endpoint。

### 15.2 同源部署

浏览器始终访问同一 origin：

```text
GET /             -> frontend static files
GET /api/v1/...   -> reverse proxy to FastAPI
```

`frontend/nginx.conf` 同时处理 SPA fallback 和 `/api/` proxy。前端使用相对 `/api/v1`，因此不需要把 Vite build-time env 当 runtime env 注入。开发环境由 Vite proxy 实现同样路径。

Compose 至少包含：

- `db`: pgvector PostgreSQL + healthcheck + named volume；
- `app`: 非 root 用户、等待 DB ready、运行 migration、提供 readiness；
- `frontend`: 构建静态文件并反向代理；
- 可选 `demo-seed` profile：显式运行，不在生产自动执行。

Release 0 不宣称 TLS/公网安全；只提供 localhost/受控网络 Demo。

### 15.3 启动自检

FastAPI readiness 检查：

- 当前模式必填配置：demo fixture 模式不要求 provider key，live 模式必须有 DeepSeek/Qwen 配置；
- DB `SELECT 1`；
- migration version；
- 关键表；
- pgvector embedding 维度与 `EMBED_DIM`；
- active case link version 是否存在（research/latent 开启时）。

维度或 migration 不匹配时拒绝 ready，并给运维日志明确修复提示；健康响应不泄露 connection string。

### 15.4 CI

CI 顺序：

```text
python -m compileall app scripts + pytest
OpenAPI export drift check
frontend npm ci + api:check + unit tests + build
docker compose config
Playwright against demo fixture
```

CI 使用 fake provider 和 demo data，不需要真实 API key。任何真实 secret 只能存在于部署 secret store，不进入 workflow 文件。

### 15.5 README / Runbook

从零复现顺序固定：

```text
copy .env.example -> .env
docker compose up -d db
run migrations
load jobs
seed cases
build case_job_links
seed demo run
docker compose up -d --build app frontend
open http://localhost
```

同时写“live provider 模式”和“deterministic demo 模式”的区别，避免用户误以为 demo 指标来自实时模型。

### 15.6 测试

- [ ] demo seed 重复执行幂等。
- [ ] fake-provider demo 从 `POST /sessions` 开始，真实执行 resume -> brief -> run -> result，而不是直接插 completed run。
- [ ] demo result 的所有 evidence IDs 可解析。
- [ ] `docker compose config` 成功。
- [ ] 前端容器 `/api/v1/health/ready` 可代理。
- [ ] 直接访问深层前端 route 不 404。
- [ ] production mode 不显示或访问 demo 入口。
- [ ] EMBED_DIM 错误时 readiness 失败，liveness 仍用于判断进程存活。
- [ ] Playwright 可在无外部 API 环境跑完整真实工作流；emergency snapshot 单独测试且不计作 E2E。

**验收：** 新机器按 README 可打开完整产品；答辩演示不依赖网络模型；CI 锁定 API、后端、前端和容器配置。

**建议提交：** `build: add deterministic demo and reproducible stack`

---

## Step 16：Release 0 Gate（必须全部通过）

**依赖：** Core Step 0–6、9–15。若 Extension Step 7/8 已开始，则二者也必须完成并通过，不能留下半接入状态。

本 Step 不增加功能，只修复验收中发现的问题。任何一项失败都不能把 Release 0 标记完成。

### 自动验证

```text
python -m pytest tests -q
python scripts/export_openapi.py --check
npm --prefix frontend ci
npm --prefix frontend run api:check
npm --prefix frontend test -- --run
npm --prefix frontend run build
docker compose config
python scripts/release0_smoke.py --mode demo
npm --prefix frontend run test:e2e
git diff --check
```

### 手动场景

- [ ] A：普通 data analyst 简历 -> review -> brief -> result -> evidence -> feedback。
- [ ] B：模糊目标 -> 一次 clarification -> 新 brief -> execute。
- [ ] C：严格地点导致结果不足 -> 只放宽 soft preference，hard constraint 不变。
- [ ] D：latent 路径故障 -> explicit 结果 + warning。
- [ ] E：非法/超大上传 -> 正确错误与恢复动作。
- [ ] F：刷新 progress/results -> 状态可从服务器恢复。
- [ ] G：Evaluation View 能展示 explicit/latent rank、context manifest、recovery event。
- [ ] H：375、768、1024、1440px 页面无重叠、水平滚动或按钮文字溢出。
- [ ] I：只用键盘完成上传后的主流程；focus 与 drawer 行为正确。
- [ ] J：demo 模式断网后仍可打开预置结果。

### 论文证据包

- [ ] 保存实验配置和指标表，不保存真实用户简历。
- [ ] 截图至少包含 Resume Review、Review your search、统一 Results、Evidence Detail、Evaluation View。
- [ ] 必须记录 explicit-only vs dual-space；只有 Step 7/8 完成时才记录 context baseline vs builder、recovery off vs on。
- [ ] 论文方法图与实际 API/状态机一致。
- [ ] 明确哪些属于已实现、哪些属于 Release 1 future work。

### Release 0 Definition of Done

```text
P0 主链路可运行
P1 双空间走真实路径
结果全部有 evidence
用户能确认 plan
系统失败可解释且有界
前端完整可用
实验可复现
Demo 可离线演示
```

**建议提交：** `release: validate dissertation mvp`

---

# Release 1：Small Public Beta

> 只有 Step 16 全部通过后才开始。Release 1 是独立加固轨道，不得为了“看起来更完整”牺牲论文主线和答辩稳定性。
>
> **默认停止点：** Codex 完成 Step 16 后必须停止并向用户汇报，不得自动继续 Step 17。Release 1 属于毕业设计之后的 Future Implementation Track，只有用户再次明确批准“开始 Public Beta”才执行。

## Step 17：Opaque Web Session、属主隔离与 CSRF

**依赖：** Release 0 Gate。

**目的：** 普通用户不复制 API Key；浏览器使用不可读的 opaque session cookie，服务端保存 hash 并校验所有资源属主。

**新增：**

- `app/db/migrations/0005_web_identity.sql`
- `app/api/auth.py`
- `app/db/identity_store.py`
- `scripts/grant_examiner.py`
- `tests/test_web_identity.py`
- `tests/test_resource_ownership.py`

### 17.1 数据模型

```text
actors
  actor_id UUID PRIMARY KEY
  is_examiner BOOLEAN DEFAULT FALSE
  created_at
  deleted_at

web_sessions
  web_session_id UUID PRIMARY KEY
  actor_id FK
  token_hash TEXT UNIQUE
  csrf_hash TEXT
  expires_at
  revoked_at
  created_at / last_seen_at
```

同一 migration 在创建 `actors` 后执行：

```sql
ALTER TABLE session_state
    ADD COLUMN IF NOT EXISTS owner_id UUID REFERENCES actors(actor_id);

ALTER TABLE match_runs
    ADD CONSTRAINT fk_match_runs_owner
    FOREIGN KEY (owner_id) REFERENCES actors(actor_id);
```

添加约束前先查询 `pg_constraint`，保证 migration 可重复执行。`session_state.user_id` 暂时保留给内部 SharedState 兼容，但所有 v1 属主查询改用 `owner_id`；不得把二者混用。

同一 migration 给现有所有用户数据补权威 ownership：

- `feedback_memory.owner_id UUID REFERENCES actors`；
- `private_memory.owner_id UUID REFERENCES actors`；
- `case_candidates.owner_id UUID REFERENCES actors`（审批匿名化后按 Step 4 清除来源）；
- 为这些 owner 列建立查询索引和删除策略。

Step 18 新建的 `upload_artifacts`、`work_items` 必须从第一天带 owner_id，或通过 mandatory session/run FK 证明属主。生产查询禁止回退到自由文本 `user_id`；旧数据迁移无法确定属主时隔离为 legacy，不对公网暴露。

浏览器只收到高熵随机 token；数据库只存 SHA-256/HMAC hash，不存明文。Cookie 属性：`HttpOnly`、`Secure`（公网强制）、`SameSite=Lax`、限定 Path。认证 secret 不写 localStorage/sessionStorage。

### 17.2 API 行为

- `POST /api/v1/auth/guest` 创建 actor/session 并设置 cookie。
- `GET /api/v1/auth/csrf` 在有效 web session 下签发短期 CSRF token；响应使用 `Cache-Control: no-store`。页面刷新后前端重新获取，不把 token 长期持久化。
- `GET /api/v1/me/runs` 返回当前 actor 最近的 run 摘要，供同一浏览器之后补充 application outcome；分页且不返回 raw state。
- 所有 Session/Run/Feedback 查询都带 `actor_id` 属主条件。
- 资源不属于当前 actor 时返回 404，不透露资源存在。
- 写操作要求 `X-CSRF-Token` 与 server session 匹配；同源仍保留 CSRF 防线。
- API key 仅保留给 CLI/admin 脚本，不出现在普通前端。
- `APP_MODE=production` 且 Cookie 不可 Secure 时启动失败。
- `/capabilities` 只在 `APP_EVALUATION_MODE=true` 且当前 actor `is_examiner=true` 时返回 `evaluation_view=true`；Explain 的 evaluation 区块执行相同服务端检查，未授权按 404 处理。Examiner 权限只由管理脚本授予，不提供自助 UI。

### 17.3 Session 生命周期

- guest session 有明确过期时间；活动时滚动更新但有绝对上限。
- 退出/删除会 revoke 当前 web session。
- 前端遇到 401 显示“Session expired”，保留非敏感页面状态并允许新建身份；不能无限重试。

### 17.4 测试

- [ ] token 明文不进入数据库或日志。
- [ ] Cookie 属性在 production 配置正确。
- [ ] Actor A 无法读取/执行/反馈 Actor B 的 Session/Run。
- [ ] Actor A 也无法访问 Actor B 的 feedback/private memory/case candidate/upload/work item。
- [ ] 不带 CSRF 的写操作被拒绝。
- [ ] 页面刷新后可通过 `/auth/csrf` 获取新 token，旧/过期 token 被拒绝。
- [ ] 过期/revoked session 返回 401。
- [ ] 404 不泄露其他用户资源存在性。
- [ ] 前端不再渲染 ApiKeyGate，也不持久化 auth token。
- [ ] 普通 actor 即使手工访问 Evaluation URL 也拿不到研究字段；examiner actor 可以。

**定向命令：** `python -m pytest tests/test_web_identity.py tests/test_resource_ownership.py -q`

**验收：** 普通用户无需密钥；所有业务资源都由服务器身份绑定；跨用户读取和写入被测试阻断。

**建议提交：** `feat: add secure guest web sessions`

---

## Step 18：PostgreSQL 持久任务、Worker Lease 与重启恢复

**依赖：** Step 17。

**目的：** 替换 Release 0 的进程内 BackgroundTasks，使 API 重启、worker 崩溃和多实例下的任务仍可恢复且不重复执行。

**新增：**

- `app/db/migrations/0006_work_items.sql`
- `app/db/work_queue.py`
- `app/storage/upload_store.py`
- `app/worker.py`
- `tests/test_work_queue.py`
- `tests/test_worker_recovery.py`

### 18.1 Work Item

```text
work_items
  work_item_id UUID PRIMARY KEY
  kind = resume_parse | match_run | feedback_closure | case_link_build
  resource_id TEXT
  status = queued | leased | completed | failed | cancelled
  priority INT
  attempts INT
  max_attempts INT
  available_at
  lease_owner TEXT
  lease_version BIGINT
  lease_expires_at
  heartbeat_at
  idempotency_key TEXT
  last_error_code TEXT
  created_at / updated_at
```

唯一约束使用 `(kind, idempotency_key)` 的 partial unique index（key 非空时），避免不同任务类型偶然使用同一个 key 时互相冲突。

同一 migration 创建 owner-bound `upload_artifacts`：`upload_id UUID`、`owner_id`、`session_id`、`checksum`、`size_bytes`、`mime_type`、`storage_key`、`status`、`expires_at`、timestamps。生产上传先流式写入 app/worker 都能读取的共享 volume 或 object storage，再在一个事务中写 upload metadata + resume_parse work item。API-local 临时 Path 不能作为 durable resource ID。

### 18.2 Claim 协议

worker 使用一个短事务执行：

```sql
SELECT work_item_id
FROM work_items
WHERE status = 'queued' AND available_at <= now()
ORDER BY priority DESC, created_at ASC
FOR UPDATE SKIP LOCKED
LIMIT 1;
```

随后写 `leased`、owner、lease expiry。业务执行不占用 claim 事务。运行中定时 heartbeat；完成时以 owner + leased status 做 CAS。

每次 claim 原子增加 `lease_version`。handler 的每一次数据库副作用都必须提交 `(work_item_id, lease_owner, lease_version)` fencing token；lease 过期的旧 worker 即使仍在运行，也不能再写 run state、event、feedback、link 或 result。

### 18.3 失败与恢复

- 可重试外部错误使用指数退避 + jitter，尊重 provider `Retry-After`。
- validation、auth、hard constraint contract 等确定性错误不重试。
- worker 崩溃后 lease 到期，reaper 将任务重新 queued；attempts 达上限则 failed。
- run 状态与 work item 状态一起更新，避免 UI 永久 running。
- 任务 handler 必须幂等：重复执行同一 run 不重复生成反馈、case 或 link。
- Pipeline Semaphore 只控制单个 worker 内资源，不再承担全局队列语义。
- `execute_and_enqueue_run()` 在一个事务中完成 plan_ready -> queued 与 work item insert。
- `complete_work_and_run()` 在一个事务中完成 result snapshot、terminal run event、run terminal status 与 work item completed。
- resume artifact 只在 parse terminal 状态后删除；失败/worker crash 时保留到 expiry 供重试，cleanup 再删除。

### 18.4 进程

```text
python -m app.worker --concurrency 3 --worker-id <hostname-pid>
```

使用 asyncio task group 启动固定数量消费者；不引入 Celery/RQ/Redis。API 只入队并返回 202；不直接运行完整 pipeline。

### 18.5 测试

- [ ] 两个 worker 并发 claim 同一任务，只一个获得 lease。
- [ ] lease 中 worker crash，过期后另一 worker 恢复。
- [ ] heartbeat 阻止健康长任务被误回收。
- [ ] lease 过期的旧 worker 使用旧 lease_version 写任何副作用都被拒绝。
- [ ] attempts 到上限后进入 failed，不无限重试。
- [ ] 同一 idempotency_key 只创建一个 work item。
- [ ] 重复 handler 不创建重复 feedback/case links/result snapshot。
- [ ] API 重启不影响已排队任务。
- [ ] 取消 queued/leased 任务行为明确，结果不被晚到 worker 覆盖。
- [ ] upload metadata 与 resume_parse enqueue 原子；worker 重启后仍能读取 artifact。
- [ ] 使用真实 PostgreSQL 跑至少一组双 worker integration test，不只验证内存 fake store。

**定向命令：** `python -m pytest tests/test_work_queue.py tests/test_worker_recovery.py -q`

**验收：** kill worker/API 后任务可恢复；多 worker 无双执行；公网模式不再使用 BackgroundTasks。

**建议提交：** `feat: add durable postgres work queue`

---

## Step 19：外部调用可靠性、配额、成本和隐私生命周期

**依赖：** Step 18。

**目的：** 控制公开试用最常见的事故：供应商超时、费用失控、恶意提交和敏感数据无限保留。

**新增：**

- `app/llm/reliability.py`
- `app/db/migrations/0007_usage_and_retention.sql`
- `app/db/usage_store.py`
- `app/privacy/data_lifecycle.py`
- `app/api/v1/privacy.py`
- `scripts/run_retention_cleanup.py`
- `tests/test_external_reliability.py`
- `tests/test_usage_limits.py`
- `tests/test_data_deletion.py`
- `frontend/src/features/privacy/PrivacySettingsPage.tsx`
- `frontend/src/features/privacy/DeletionStatus.tsx`
- `frontend/src/features/feedback/ApplicationOutcomeForm.tsx`

`0007_usage_and_retention.sql` 同时创建独立 `deletion_requests` 表；它在 actor 删除期间保存 request ID、状态和非敏感错误码，不依赖即将被删除的 Session/Run 外键。

### 19.1 外部调用策略

所有 DeepSeek/Qwen 调用共享一个 wrapper：

```python
async def call_with_policy(
    operation: Callable[[], Awaitable[T]],
    *, timeout_seconds: float,
    max_attempts: int,
    retryable_codes: set[str],
    budget: UsageBudget,
) -> T: ...
```

- connect/read/total timeout 分开配置；
- 只重试 timeout、429、特定 5xx；
- auth error、invalid request、schema violation不重试；
- 默认最多 2 次总尝试；
- 每次调用写 usage ledger：provider、model、operation、tokens/characters、duration、status，不写 prompt 内容；
- run 达到 call/token/cost budget 时停止后续非必要调用并返回明确 warning/failure。

价格随供应商变化，配置从环境或管理表读取；未知价格只记录 usage，不伪造 cost。

### 19.2 配额与滥用边界

- 每 actor 的并发 run 上限；
- 每日 resume upload 和 match run 上限；
- guest identity 创建还要有短期 edge/IP 滥用限制；IP 仅做短期 keyed hash/桶计数，不写永久分析日志；
- 全局 queued work item 上限；
- upload size、feedback note、goal 长度继续受限；
- 超限返回 429 + `retry_after_seconds`；
- 限额查询和递增必须原子，不能使用进程内 counter 作为生产事实来源。

### 19.3 数据保留

默认建议：

- 原始上传：解析完成立即删除；
- Session/run state：可配置短期保留，例如 30 天；
- event：只保留 allow-list metadata；
- feedback：按用户同意和产品政策保留；
- pending case candidate：超期未审核自动删除；
- approved anonymous case：必须通过不可关联匿名化检查。

确切天数写入 Privacy Policy 和 Settings，部署者可改，但 UI 必须读取后端公开配置，避免文案与实际不一致。

### 19.4 Profile Retention

只有用户显式开启“Remember my profile”后才写 `private_memory`。关闭或删除时清理 private memory。Release 0 遗留的自动写入逻辑不得恢复。

Release 1 前端在 recent runs 中允许用户提交 canonical application outcome 和独立 learning consent；没有可恢复 actor session 时不显示“稍后反馈”承诺。Privacy Settings 从后端 capabilities/retention config 展示实际保留天数、Remember profile 开关和删除入口。

### 19.5 删除接口

`DELETE /api/v1/me/data`：

1. 二次确认 + CSRF；
2. 创建 deletion request，将 actor 标为 deleting 并拒绝新业务任务；
3. cancel queued work，等待/终止 leased work 的安全点；
4. 删除 Session、Run、Events、Feedback、Private Memory、uploads；
5. 对 pending case candidate 一并删除；
6. approved case 若真正不可关联则不保留来源映射；若仍可追溯，则必须支持删除；
7. 完成后 revoke web sessions 并把 deletion request 标为 completed。

数据库删除与文件删除采用可重试 job，并返回 deletion request ID。当前 session 在删除完成前只能读取该 request 状态；完成后 cookie 失效。部分失败必须保持 failed/retryable 状态，不能谎报完成。

前端删除流程要求输入 `DELETE` 二次确认，随后显示 deletion request 的 queued/running/completed/failed；completed 后清空本地非敏感草稿并跳到会话过期页。失败时显示重试/联系管理员路径，不把内部错误返回浏览器。

### 19.6 测试

- [ ] 429 + Retry-After 被正确退避，非 retryable 4xx 只调用一次。
- [ ] timeout 不超过配置上限。
- [ ] budget 用尽后不再调用 provider。
- [ ] 并发配额原子，只允许配置数量的 run。
- [ ] usage 日志不含 prompt/resume/evidence text。
- [ ] retention cleanup 只删除到期资源。
- [ ] delete request 清理所有属主数据并 revoke cookie。
- [ ] private_memory 只有 consent=true 才写入。
- [ ] returning user 只能给自己的历史 run 提交 application outcome。
- [ ] Privacy 页面展示的 retention 天数来自 API，删除状态 UI 覆盖成功和失败。

**定向命令：** `python -m pytest tests/test_external_reliability.py tests/test_usage_limits.py tests/test_data_deletion.py -q`

**验收：** 公开试用有费用和滥用上限；数据保留与 UI 声明一致；用户删除请求可验证完成。

**建议提交：** `feat: enforce usage and privacy lifecycle`

---

## Step 20：生产可观测性、备份恢复、TLS 与发布运维

**依赖：** Step 19。

**目的：** 让管理员能够发现、定位和恢复故障，并建立最小可用的单机公网部署流程。

**新增：**

- `app/observability/logging.py`
- `docs/operations_runbook.md`
- `docs/incident_runbook.md`
- `scripts/backup_db.py` 或明确的 `pg_dump` wrapper
- `scripts/restore_db_test.py`
- `deploy/Caddyfile`
- `docker-compose.production.yml`
- `tests/test_health_endpoints.py`
- `tests/test_log_redaction.py`

**修改：** `app/api/v1/health.py` 和 Release 0 的健康测试，加入 worker、identity 与 production 配置检查；不要创建第二套 health router。

### 20.1 结构化日志

JSON 日志统一字段：

```text
timestamp, level, service, event,
trace_id, actor_hash, session_id, run_id, work_item_id,
stage, duration_ms, outcome, reason_code
```

`actor_hash` 使用部署 secret HMAC，便于关联但不能反推出 actor。日志 redaction 递归过滤 Authorization、Cookie、CSRF、API key、DATABASE_URL、prompt、resume/evidence text 和 provider raw body。

### 20.2 Health 与最小指标

- `/health/live`：只表示进程 event loop 存活，不查外部 provider。
- `/health/ready`：DB、migration、worker heartbeat、active link version；失败返回非 200。
- `/health/startup` 或启动检查：配置、表、embedding 维度。

产品指标从事件/usage 聚合，不接复杂 analytics：upload success、run completion、p50/p95 latency、recovery rate、warning rate、feedback rate、quota reject rate。禁止记录简历内容作为 analytics property。

### 20.3 备份与恢复

- 定时 `pg_dump`，文件加密并限制访问；保留周期有文档。
- 至少完成一次恢复到独立临时数据库的演练。
- 检查 row counts、migration version、demo smoke；只生成备份但从不恢复不算通过。
- 上传默认不保留，因此不依赖本地 upload volume 备份。

### 20.4 TLS 与生产 Compose

生产入口使用 Caddy（或部署平台托管 TLS）终止 HTTPS，并把 `/api` 和静态前端保持同源。数据库不暴露公网端口；app/worker 使用内部网络；容器非 root；read-only filesystem 能启用的服务尽量启用。

Secrets 从部署环境/secret store 注入，不打进镜像。`APP_MODE=production` 启动时强制检查：

- HTTPS/secure cookie 配置；
- durable worker backend；
- demo mode off；
- evaluation mode 按部署决定，默认 off，并要求服务端授权；
- auth enabled；
- CORS 不使用 `*`；同源部署通常不需要跨域。

### 20.5 发布与回滚

Runbook 固定顺序：备份 -> migration dry check -> 部署 app/worker/frontend -> readiness -> smoke -> 切流量。回滚需区分应用回滚和不可逆 migration；每个 migration 在注释中写 forward-fix 或 rollback 方法。

Production migration 由一次性的 `migrate` service/job 在 app replicas 启动前执行；禁止每个 app/worker 容器同时自动跑 migration。Release 0 单实例 compose 可自动 bootstrap，但 production compose 必须使用 one-shot gate。

### 20.6 测试

- [ ] 日志 redaction 对嵌套 dict/list 有效。
- [ ] liveness 不因 provider 故障失败；readiness 因 DB/worker 故障失败。
- [ ] production + in_process_demo 启动被拒绝。
- [ ] production + insecure cookie 启动被拒绝。
- [ ] DB 端口未暴露在 production compose。
- [ ] 备份可恢复到空数据库并通过 smoke。
- [ ] readiness 和日志均不泄露 secret。

**验收：** 管理员能按 run_id 定位问题；备份恢复经过演练；公网入口 HTTPS；错误配置 fail fast。

**建议提交：** `ops: add production readiness and recovery controls`

---

## Step 21：Public Beta Gate（上线前最终门）

**依赖：** Step 17–20。

本 Step 只做验证、修复和发布记录。

### 安全与隔离

- [ ] Actor A 对 Actor B 的 Session、Run、Result、Explain、Feedback、Delete 全部得到 404。
- [ ] 浏览器存储中不存在 API key、auth token、resume content。
- [ ] CSRF 缺失/错误的写请求被拒绝。
- [ ] Cookie 为 Secure/HttpOnly/SameSite，退出后立即失效。
- [ ] 上传伪装文件、路径穿越、超大文件均被拒绝。
- [ ] Error/Log/Trace 不含 secret、prompt、完整简历或 SQL。

### 任务与并发

- [ ] 10 个并发用户提交时，全局 active worker 不超过配置，API 仍能返回 status。
- [ ] 同一 run 双 execute 只执行一次。
- [ ] kill API 后 queued/running work 不丢失。
- [ ] kill worker 后 lease 到期可恢复，结果不重复。
- [ ] provider 429/5xx/timeout 按策略恢复，attempt 不超上限。
- [ ] stale/failed task 对用户有恢复路径。

### 隐私与成本

- [ ] learning consent 默认 false。
- [ ] 未审核 candidate 不进入 `career_cases`。
- [ ] `DELETE /me/data` 完成后旧资源不可访问。
- [ ] retention cleanup 在测试时钟下行为正确。
- [ ] 每 actor 配额和 run budget 生效。
- [ ] usage records 无敏感正文。

### 部署与恢复

- [ ] production compose config 有效且 DB 不暴露公网。
- [ ] HTTPS、secure cookie、demo off、durable worker gate 全部通过。
- [ ] 从最新备份恢复到空库并通过 smoke。
- [ ] migration 在当前生产快照副本上成功。
- [ ] app/worker/frontend 各自有健康状态与结构化日志。
- [ ] 回滚/forward-fix 流程由另一人或新的 Codex 会话照文档走通。

### 产品体验

- [ ] 首次用户无需 API key，能在 5 个主要界面内完成匹配。
- [ ] 普通模式不显示研究开关或内部模型术语。
- [ ] 结果是一份统一列表，每条岗位/建议均有 evidence。
- [ ] 失败、空结果、warning、session expired、quota exceeded 都有下一步动作。
- [ ] 375/768/1024/1440px 与键盘回归通过。

**Definition of Done：** 所有 checkbox 有测试输出或人工验证记录；`APP_MODE=production` 的启动门通过；operations runbook、privacy policy、retention 配置和实际实现一致。

**建议提交：** `release: validate small public beta`

---

## 6. 明确不做

以下内容不属于本计划，Codex 不得擅自加入：

- 不引入 LangGraph、AutoGen、CrewAI、Celery、RQ、Redis、Kafka 或 Kubernetes。
- 不做 cross-encoder、在线 RAPTOR 主链路、案例权重自动学习。
- 不做支付、订阅、营销 landing page、复杂 admin dashboard。
- 不做在线富文本简历编辑器、自动代投或招聘方 CRM。
- 不做 WebSocket；Release 0/1 先使用带 `retry_after_ms` 的轮询，除非有数据证明必须换 SSE。
- 不在普通用户 UI 暴露模型选择、RAPTOR、latent、fusion alpha。
- 不把 raw prompt、chain-of-thought、provider response 当 Explain 功能返回。
- 不从一次正向反馈直接自动发布公共案例。
- 不承诺“大规模生产”或合规认证；Release 1 目标仅为小规模受控 Beta。
- 不为“代码更现代”重写现有通过测试的 retrieval/agent 模块；只在当前 Step 的职责边界内提取接口。

---

## 7. 论文结构映射

### 方法贡献

1. **Supervisor-guided Dual-space Retrieval**
   - explicit job space
   - latent anonymized case space
   - versioned case-job precomputation
   - hard-filtered score fusion

2. **Evidence-preserving Agent Runtime**
   - task-specific ContextPacket
   - typed bounded recovery
   - claim/evidence verification
   - user-confirmed Match Brief

### 系统工程贡献

- Session/Run 分离与可恢复状态机；
- public explain projection；
- typed OpenAPI frontend；
- deterministic demo；
- reproducible deployment；
- consent-aware feedback pipeline。

### 评估章节

- RQ1：dual-space 是否改善 ranking/coverage，同时保持 hard constraint 与 evidence correctness？
- RQ2：context selection 是否降低上下文成本而不损害输出质量？
- RQ3：bounded recovery 是否提高 run completion，并保持循环上限？
- 工程指标作为 supporting evidence，不冒充算法精度。

---

## 8. Codex 执行速查

| 顺序 | Step | 主要产物 | 进入下一步的硬门 |
|---:|---|---|---|
| 0 | 基线 | baseline 文档 | 全量测试真实结果已记录 |
| 1 | Run/Event | migration + CAS store | 并发更新不会覆盖 |
| 2 | API v1 | DTO + OpenAPI | raw state 不出 API |
| 3 | Resume Review | 安全上传 + confirm | 未确认不能匹配 |
| 4 | Feedback Consent | pending candidate | 默认不学习 |
| 5 | Case Links | versioned links | provenance + 幂等 |
| 6 | Dual Space | unified candidates | hard filter + evidence |
| 7 | Context | ContextPacket | 预算和 evidence 可测 |
| 8 | Recovery | typed policy/events | 无开放循环 |
| 9 | Match Brief | plan hash + run orchestration | approved plan 不被覆盖 |
| 10 | Result/Explain | public projections | 无敏感内部状态 |
| 11 | Evaluation | 真实消融 | 评估调用生产路径 |
| 12 | Frontend Core | generated client + shell | contract drift 可检测 |
| 13 | Pre-match UX | upload/review/brief | 用户可完整进入 queued |
| 14 | Result UX | progress/result/research/feedback | 主流程 E2E |
| 15 | Demo/Deploy | fixture + compose + CI | 无外部 API 可演示 |
| 16 | Release 0 Gate | dissertation MVP | 全部验收通过 |
| 17 | Identity | opaque cookie ownership | 跨用户隔离 |
| 18 | Durable Worker | PostgreSQL queue | 崩溃恢复无重复 |
| 19 | Limits/Privacy | budget + retention/delete | 成本和数据可控 |
| 20 | Operations | logs/backup/TLS | 恢复演练通过 |
| 21 | Beta Gate | release evidence | 才允许公网试用 |

执行时一次只打开当前 Step 需要的文件。每完成一个 Step，在本表对应行旁记录 commit、测试命令和结果；不要提前创建后续空壳文件。若实现与 `AGENTS.md`/`CLAUDE.md` 冲突，以根目录硬约束为准并停止请求用户决策。
