# 代码导览（大白话版）——带你完整过一遍自己的项目

> 读完这份文档，你应该能回答三个问题：我的代码分成哪几块？每一块在干什么？一次完整的"匹配"背后到底发生了什么？
> 分支说明：`langgraph` 分支（本文档所在）用 LangGraph 图做编排；主线 `codex/v1-complete` 用自研编排。langgraph 分支以主线为基础，除编排层外还包含之后的审计修复、清扫与文档等配套修订，两边不是逐行相同。

---

## 一、这个项目是什么（一个比喻）

把它想象成一家**线上职业规划工作室**：

- 你把简历交给前台（上传），工作室先把它**誊写成标准档案**，并且每一条都标注"出自你简历原文第几段"（防止后面有人瞎编你的经历）；
- 然后一位**需求顾问**跟你聊清楚：想找什么工作、哪些条件是死的（签证/地点）、哪些只是偏好；
- 你签一张**确认单**（Match Brief），从这一刻起你的要求被"冻结"，谁也不能偷偷改；
- 后台三位同事开工：**岗位顾问**去岗位库里筛选和匹配，**规划师**写差距分析和简历建议，**项目经理（PM）**在每个环节前后检查他们的工作，不合格就打回（最多打回一次，不许无限返工）；
- 最后你拿到：分好档的岗位列表（现在就能投 / 冲一冲 / 跳板岗）、每个岗位"为什么推荐你"的原文证据、简历怎么改、未来路径怎么走。

代码里的一切都是在实现这个工作室，外加两条铁律：**硬条件只让数据库判断（不信 AI 的嘴）**、**所有建议必须能指回原文（不许编造）**。

## 二、代码地图

```
项目根/
├── app/                 后端主体（Python + FastAPI）
│   ├── api/             对外接口层（路由 + 投影）
│   ├── graph/           LangGraph 图编排（本分支默认执行路径）
│   ├── agents/          三个业务 Agent + 监督体系 + 旧编排
│   ├── retrieval/       检索（混合检索 + 双空间 + RAPTOR）
│   ├── normalization/   简历归一化（Stage 0）
│   ├── memory/          记忆与反馈（P1）
│   ├── evaluation/      评估指标
│   ├── llm/             大模型/向量化客户端
│   ├── db/              数据库层
│   ├── domain/          领域模型（数据结构定义）
│   ├── state/           共享状态定义（单一事实来源）
│   ├── config.py        全部配置（读 .env）
│   └── serve.py         启动入口
├── frontend/            React 前端工作台
├── scripts/             数据入库、评估、演示工具
├── tests/               314 项自动化测试
├── docs/                设计文档、计划书、报告
└── data/                岗位数据集、评估标注、演示简历
```

## 三、逐区讲解

### app/api/ —— 对外接口层（"前台+保安"）

| 文件 | 大白话 |
|---|---|
| `main.py` | 服务的总开关。启动时建两个数据库连接池（asyncpg 给业务、psycopg 给 checkpoint）、初始化 checkpoint 存储、回收上次崩溃残留的运行、起一个每小时清理隐私快照的后台钟；关闭时把这些都善后。 |
| `serve.py`（在 app/ 下） | 唯一正确的启动方式 `python -m app.serve`。存在的原因很具体：Windows 上 uvicorn 默认的事件循环跑不了 psycopg，这里强制换成兼容的循环再启动。 |
| `routes.py`（已删除） | W2b 已移除无前缀旧 API（/resume /match /status /result /feedback）及其专属测试；服务现在只挂载 `/api/v1` router。 |
| `v1/` 目录 | **正式 API**。`sessions.py`（建会话/传简历/确认简历/意图咨询/确认 Brief）、`runs.py`（提交执行/查进度/取结果/群聊消息流/评估解释）、`feedback.py`（对推荐岗位点赞点踩）、`monitoring.py`（运行指标）、`schemas.py`（所有请求/响应的数据格式——**前后端的合同**）、`router.py`（把它们拼起来+能力开关声明）。 |
| `result_projector.py` | **隐私守门员**。内部状态里有简历原文、监督日志等私密内容，这个文件负责把它"投影"成只含可公开字段的结果。硬约束违规剔岗只认确定性核查结论（AI 说某岗位违规不算数）；此外发布门还会过滤缺岗位 ID 或缺 JD 证据的条目。 |
| `conversation_projector.py` | **群聊导演**。把一次运行的进度、Brief、恢复事件、结果，翻译成"需求顾问·小意 / 岗位顾问·小检 / 规划师·小策 / PM"四个角色的群聊台词。纯模板代码生成，不调 AI，所以又快又稳还不会泄密。 |

### app/graph/ —— LangGraph 图编排（"新流水线"）

| 文件 | 大白话 |
|---|---|
| `state.py` | 定义"流水线上传递的托盘"（GraphState）：里面装着共享状态、确认单、检索计划、核查结果、重试计数等。 |
| `nodes.py` | 七个工位：intent（读需求）→ lock_brief（锁定确认单）→ retrieve_match（检索匹配）→ strategy（写策略）→ verify（终审核查）→ 若需要 prepare_reretrieval（准备重检索，最多一次）→ publish（发布）。每个工位都是旧编排函数的薄壳，不复制业务逻辑。 |
| `build.py` | 把工位连成图，定义"核查后往哪走"的分岔路。 |
| `runner.py` | 流水线厂长：接单（QUEUED→RUNNING）、开机（带 checkpoint 跑图）、断电续跑（探测 checkpoint，有就从断点继续、没有就重建初始托盘）、幂等收尾（结果只保存一次）、下班清理（终态删掉含隐私的 checkpoint）。 |

**checkpoint 是什么**：每个工位干完，整个托盘会被存进 PostgreSQL。进程崩溃后**再次触发同一个 run** 时，runner 能从最后一个存档点继续，已完成的工位不会重做。注意边界：这是"runner 级续跑能力"——服务重启本身不会自动重新调度这些 run（重启只把超时的旧 run 标记为 stale），自动重调度属于后续工作。

### app/agents/ —— 三个 Agent 与监督体系（"员工和 PM"）

| 文件 | 大白话 |
|---|---|
| `base.py` | 所有 Agent 的公共套路：读状态 → 拼提示词 → 调大模型 → 校验返回是不是合法 JSON 对象 → 写回状态。 |
| `intent_agent.py` | 需求顾问。两个形态：面向用户的咨询对话（Targeted/Explore 两种模式，最多追问一次），和内部的意图整理。特点：长期目标用关键词保守判定，你没明说就不瞎猜；AI 返回的约束字段要过白名单。 |
| `matching_agent.py` | 岗位顾问。调用检索层拿候选，然后并发为每个 Top 岗位写"为什么推荐"的解释，再分成三档。还负责把你明确说不要的岗位（avoid_roles）确定性地过滤掉并记日志。 |
| `strategy_agent.py` | 规划师。写技能差距、简历修改建议、职业路径。所有简历建议必须引用真实的简历原文片段编号，引用不上的直接丢弃。 |
| `supervisor.py` | PM 的两次出场：规划阶段（旧路径用）和终审阶段。终审调一次大模型做综合判断，然后**确定性复核**接管：数量、ID 合法性、证据完整性、隐性声明清理。修复动作（删除无证据建议）每次运行最多一次。 |
| `supervisor_harness.py` | PM 的检查清单：7 个纯代码检查点（每个 Agent 前后 + 发布门禁），不调大模型，发现锁定的硬约束被改动等严重问题会直接抛错拦截。 |
| `orchestrator.py` | **公共编排工具箱**。保留 `run_agentic_match_from_state`、`run_persisted_agentic_match_run`（图路径回退）及图工位复用的函数；旧 session 入口已在 W2b 删除。 |
| `trace.py` | 答辩解释器。把监督日志按白名单投影成"排名怎么来的、恢复发生过几次、每阶段多少毫秒"，供评估页展示。 |

### app/retrieval/ —— 检索层（"怎么找岗位"）

| 文件 | 大白话 |
|---|---|
| `hybrid_search.py` | 检索主链，四步走：① SQL 硬过滤（地点/签证/经验/学历，参数化查询，不给 AI 插嘴的机会）→ ② BM25 关键词检索和 Dense 语义检索**并行**跑 → ③ RRF **按岗位**融合（默认 BM25+Dense 两路；启用 RAPTOR 时它是第三路一起进 RRF；同一岗位多个文本块不会被当成多个岗位）→ ④ 加权重排：`0.6×语义分(取 Dense 与 RAPTOR 中较高者，RAPTOR 默认关) + 0.3×RRF 融合分 + 0.1×BM25 分 + 软偏好加分 + 字段感知加分`。还带类型钳制，防止"负数 top_k"这类怪输入。 |
| `rrf.py` | 12 行的融合公式：排名越靠前得分越高，两路都靠前的最吃香。 |
| `dual_space_search.py` | 双空间总闸：显性检索（真实岗位）+ 隐性检索（匿名案例）并行，隐性只能在显性结果内做**有限加权重排**（实际权重 = 配置的最大权重 × 案例置信度，最大权重默认 0.3、可配置），不能塞新岗位、不能绕过硬过滤，可一键关闭，失败自动退回纯显性。 |
| `implicit_search.py` | 隐性空间的具体实现：用脱敏后的画像查匿名案例库，聚合出"历史上相似的人投这个岗位走到了哪一步"。 |
| `query_builder.py` | 把结构化简历拼成检索用的查询文本。 |
| `raptor.py` | RAPTOR-lite：离线把岗位聚成摘要树，在线先召回摘要再传播到原文块。**默认关闭**，只在消融实验里开。 |

### app/normalization/ —— 简历归一化（"誊写档案"）

`resume_intake.py` 一个文件干完 Stage 0：解析 PDF/DOCX/TXT（DOCX 连表格都读）→ **先在本地**把原文切成带编号的证据片段（R001、R002…）→ 让大模型只基于这些片段做结构化 → 逐条校验每个事实引用的片段真实存在且文本对得上，对不上的标记 unverified 或拒绝。这是"防编造"铁律的第一道闸。

### app/db/ —— 数据库层（"仓库"）

| 文件 | 大白话 |
|---|---|
| `schema.sql` + `migrations/` | **业务表**结构：岗位表、JD 文本块表（带 1024 维向量 + HNSW 索引 + 全文索引）、会话状态表、run 生命周期表、记忆/案例/反馈表、RAPTOR 树表。另有四张 LangGraph 运行时自建表（`checkpoint_migrations`/`checkpoints`/`checkpoint_blobs`/`checkpoint_writes`，由 checkpointer.setup() 创建，不在 schema.sql 里）。 |
| `pool.py` | asyncpg 连接池单例（带锁防止并发重复建池）。 |
| `state_store.py` | 会话状态的读写核心：按 session_id 存取，行锁 + 字段级原子更新（防止两个请求互相覆盖），简历保存和版本号递增在同一个事务里。**服务无状态的关键**。 |
| `run_store.py` | run 的状态机（DRAFT→PLAN_READY→QUEUED→RUNNING→终态）、状态快照、结果快照、启动时回收僵尸 run、列出待清理的 checkpoint。 |
| `event_store.py` / `monitoring_store.py` | 运行事件与监控指标的读写。 |
| `vector.py` | 向量转数据库文本的唯一实现（以前四处各写一份，已合并）。 |

### app/memory/、app/evaluation/、app/llm/、app/domain/、app/state/

| 区 | 大白话 |
|---|---|
| `memory/` | P1 机制：`private_memory` 用户私有简历版本、`feedback` 投递反馈、`case_base` 匿名案例库（带邮箱/电话/链接的 PII 检测，脏数据进不来）、`feedback_loop` 反馈沉淀为案例的闭环（已接入 v1 reaction）。 |
| `evaluation/` | `metrics.py`：Precision/Recall/MRR/NDCG、硬过滤准确率（逐列核验，缺数据算 unknown 不算通过）、解释忠实度（按岗位对证据，A 岗不能借 B 岗的证据）；`load_validation.py` 压测统计。 |
| `llm/` | `deepseek.py` 聊天模型、`qwen_embed.py` 向量化。两者都有 Semaphore 限流（防止把 API 打爆）；上下文预算（超长输入自动压缩并标记 truncated）只在 DeepSeek 聊天边界做，向量化没有。 |
| `domain/` | 纯数据结构：`match_brief.py` 确认单（内容哈希 + 不可变）、`results.py` 对外结果 DTO（禁止多余字段）、`run.py` run 状态机定义、`intent.py`、`monitoring.py`。 |
| `state/schema.py` | **SharedState——整个系统的单一事实来源**。简历状态、职业状态、检索状态、策略状态、反馈状态、监督日志，全部 Agent 读写的就是它。加字段先改这里。 |

### frontend/ —— React 工作台

技术栈：React 19 + Vite + TypeScript + TanStack Query。类型从后端 OpenAPI 快照自动生成（`src/api/generated.ts`），后端改接口前端类型对不上会直接报错——这就是前后端不脱节的机制。

| 目录 | 页面/职责 |
|---|---|
| `src/features/onboarding/` | 落地页（电影化开场） |
| `src/features/session/` | 建会话+传简历、简历确认页 |
| `src/features/brief/` | 意图咨询 + Match Brief 确认单 |
| `src/features/run/` | 运行进度板（七阶段） |
| `src/features/chat/` | **服务群群聊视角**：四角色气泡直播运行过程 |
| `src/features/results/` | 结果页：三档岗位、解释、JD 证据抽屉、简历建议、路径 |
| `src/features/evaluation/` `monitoring/` | 排名溯源表、阶段耗时、恢复事件；运行大盘 |
| `src/features/feedback/` | 岗位反馈组件 |
| `src/api/` | 请求封装 + 自动生成的类型 |
| `e2e/` | Playwright 全流程浏览器测试 |

### scripts/ 与 tests/

| 内容 | 大白话 |
|---|---|
| `scripts/load_jobs.py` | 把 LinkedIn 数据集入库：抽结构化字段 → 切块 → 算向量 → 计算全文检索向量（tsvector；GIN 索引本身由 schema.sql 建）。 |
| `scripts/build_raptor_index.py` | 离线建 RAPTOR 摘要树（可选）。 |
| `scripts/seed_cases.py` | 灌演示用匿名案例。 |
| `scripts/generate_demo_resume.py` | 生成一份和岗位库匹配的演示简历 DOCX。 |
| `scripts/evaluate_system.py` / `evaluate_retrieval_ablation.py` | 跑评估指标 / 消融实验。 |
| `tests/`（314 项） | 分五类读：**单元**（各模块行为）、**契约**（OpenAPI 快照、DTO 白名单、公共别名）、**特征**（旧编排的执行顺序被逐条锚定，图实现必须跑出一模一样的顺序）、**恢复**（真实 PostgreSQL 上模拟崩溃续跑）、**隐私**（响应序列化后不得出现简历原文/user_id）。 |

## 四、一次完整匹配的旅程（跟着数据走）

1. **POST /api/v1/sessions** → `session_state` 表多一行，你有了 session_id。
2. **上传简历** → 文件以"会话哈希+随机 ID"存盘（防覆盖），后台任务开始归一化：`resume_intake.py` 切证据片段 → DeepSeek 结构化 → 逐条校验 → 结果和版本号在一个事务里写库 → 临时文件删除。
3. **你在前端确认简历** → 版本被标记 confirmed。
4. **意图咨询** → `IntentConsultAgent` 对话（最多追问一次），产出目标/硬约束/软偏好草案。
5. **确认 Match Brief** → 内容哈希锁定，**run 在这一刻创建**（先是 draft，保存 Brief 后变 plan_ready）。
6. **POST /runs/{id}/execute** → run 进入 queued，`runner.py` 把它推进 RUNNING，图开始跑：
   - intent 工位（已咨询过就跳过 AI 只记日志）→ lock_brief（用确认单覆盖状态，硬约束锁死）
   - retrieve_match：SQL 硬过滤 → BM25∥Dense → RRF → 重排 →（可选）隐性重排 → Top-K
   - strategy：缺口/建议/路径（全部证据绑定）
   - verify：PM 终审，需要时可分别触发至多一次重检索（只放宽软偏好）和至多一次修复（删无证据建议）
   - publish：发布门禁 + 投影成公开结果
   - 每个工位后都落 checkpoint；全部完成后结果入库、checkpoint 删除。
7. **前端轮询** status（按服务端给的间隔），同时群聊页把以上过程翻译成四角色对话。
8. **结果页** 展示三档岗位；你点某岗位的证据，看到的是**岗位入库阶段**切好的 JD 原文块（简历侧的 Rxxx 原文片段则来自第 2 步的归一化）。
9. **反馈** → 写入 `feedback_memory`，供 P1 闭环。

## 五、常用命令

```powershell
# 启动（唯一正确方式）；或一键 start.bat（含前端）
.venv\Scripts\python.exe -m app.serve --host 127.0.0.1 --port 8000

# 全量测试
.venv\Scripts\python.exe -m pytest tests/ -q

# 前端（在 frontend/ 目录下，按需选一条）
npm run dev
npm test
npm run typecheck
npm run build

# 数据入库
.venv\Scripts\python.exe -m scripts.load_jobs --stage all

# 回退到旧编排（不用图）：.env 里设
# LANGGRAPH_ORCHESTRATOR_ENABLED=false
```
