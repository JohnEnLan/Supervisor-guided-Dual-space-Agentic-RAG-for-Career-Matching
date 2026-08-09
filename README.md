# Career-RAG：Supervisor 监督的双空间 Agentic RAG 职业匹配系统

Career-RAG 是一个面向毕业设计答辩的多人职业匹配 Web 系统。用户在群聊式工作台中上传并确认简历、完成目标咨询、批准 Match Brief（匹配确认单），随后得到分层岗位、JD 与简历证据、技能差距、简历建议和职业路径。

这里的 **Agentic RAG**，白话说就是“先从岗位库找证据，再让分工明确的 AI 角色基于证据完成任务”；**Supervisor** 是贯穿流程的项目经理，负责检查计划、约束、证据和发布条件。

历史批次 9 的代码与实测工件冻结基线为 `2474e48`；本轮 UI 收尾与清理基于
`langgraph@79af2dd` 的未提交工作树，验收口径见
`docs/validation/2026-08-09-final-polish-acceptance.md`。

## 当前真实能力

- **群聊工作台**：登录后在一条时间线上完成简历上传、档案确认、咨询、确认单、运行播报、结果查看与反馈；移动端使用可聚焦、可关闭的导航抽屉。
- **认证与配额**：邮箱或短信验证码通道由后端能力声明控制；认证会话使用 Cookie；每账号会话额度由 `SESSION_QUOTA_PER_USER` 配置，额度用尽时前端展示 402 付费墙。
- **咨询引擎与简历澄清回路**：咨询先收集目标、地点、签证三项必需信息；功能开启时，归一化阶段发现的含糊经历会生成澄清问题。有效回答按 `C001`、`C002`……保存为新的简历证据，跳过也会被明确记录。
- **三个业务 Agent + Supervisor + PM 咨询督导**：意图 Agent 整理需求，匹配 Agent 检索并解释岗位，策略 Agent 给出差距与路径；Supervisor 执行有界核查。咨询期 PM 督导先用纯规则 L1 判断是否需要介入，再在预算允许时调用 L2 模型生成一条提示；失败时不回滚已经提交的用户轮次。
- **混合检索与双空间**：SQL/metadata 先执行地点、签证等硬过滤；BM25 关键词检索、Dense 语义检索与可选 RAPTOR 层级摘要检索并行，经 RRF（按排名合并多路结果）融合，再做确定性打分。显式岗位空间与匿名案例空间并行，案例空间只能在硬过滤后的岗位集合内有限调序。
- **RAPTOR + Cross-Encoder 双开**：RAPTOR 用层级摘要补充召回；Cross-Encoder（把查询与每个候选放在一起精排的模型）重排候选池。批次 9 验收配置中 `RAPTOR_ENABLED=true`、`RERANK_ENABLED=true`；`.env.example` 为安全起步仍默认关闭，需显式开启。
- **持久化和恢复**：FastAPI 服务本身无状态，共享状态、run、事件与 checkpoint 均存 PostgreSQL。LangGraph runner 在同一 run 再次触发时可从 checkpoint 继续；服务重启不会自动重新调度未完成 run。
- **评估管线**：实现 P@K、R@K、MRR、NDCG@K、硬过滤准确率与证据忠实度；版本化演示语料可复现实验的排名、标签与 manifest。

## 架构

```text
React 群聊工作台
  │  登录 / 上传 / 咨询 / 批准确认单 / 轮询 / 反馈
  ▼
FastAPI v1（认证、配额、公开字段投影）
  │
  ├─ Resume Intake ── 解析 → 归一化 → R### 原文证据 → 可选 C### 澄清证据
  │
  ├─ Consult Engine ── 三项必需槽位 → 澄清回路 → 深挖
  │                    └─ PM Coach：L1 规则 → L2 提示（有预算、fail-open）
  │
  └─ Match Brief（版本 + 哈希锁定）
       ▼
     LangGraph runner / PostgreSQL checkpoint
       Intent Agent → Retrieval & Matching Agent → Strategy Agent
                                │
                                ▼
       SQL 硬过滤 → BM25 ∥ Dense ∥ RAPTOR → RRF → Cross-Encoder
                                │
                         Supervisor 有界核查
                                ▼
               Now Fit / Stretch Fit / Bridge Role + evidence

PostgreSQL + pgvector
  ├─ session_id 下的 SharedState 与 resume generation/version
  ├─ JD、全文索引、1024 维向量与 HNSW 索引
  ├─ run / event / checkpoint
  └─ 用户画像、反馈与匿名案例
```

关键边界：硬条件由 SQL/metadata 判断；对外建议必须能指回简历或 JD 证据；所有外部 LLM/embedding/rerank 调用均受异步并发限制。

## 快速启动

### 1. 环境与依赖

需要 Python 3.11+、PostgreSQL 17（安装 pgvector）、Node.js/npm，以及可用的 DeepSeek、Qwen/DashScope 凭据。

PowerShell：

```powershell
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

在 `.env` 中填写真实密钥和数据库连接。不要提交 `.env`。接受态演示需要在模板基础上显式设置：

```dotenv
DATABASE_URL=postgresql://user:password@localhost:5432/career_rag
AUTH_ENFORCED=true
SESSION_QUOTA_PER_USER=3

DEEPSEEK_API_KEY=...
QWEN_API_KEY=...
QWEN_EMBED_MODEL=text-embedding-v4
EMBED_DIM=1024

RESUME_CLARIFY_ENABLED=true
RESUME_CLARIFY_MAX=2
CONSULT_COACH_ENABLED=true
CONSULT_COACH_MAX=3

RAPTOR_ENABLED=true
RERANK_ENABLED=true
RERANK_ENDPOINT=...
```

`EMBED_DIM` 必须与数据库向量列一致；Cross-Encoder 开启时必须提供有效的 `RERANK_ENDPOINT`。验证码的 `console` provider 仅适合本地开发，生产配置会拒绝它。

### 2. 数据库迁移与服务

```powershell
.\.venv\Scripts\python.exe -m app.db.migrate
.\.venv\Scripts\python.exe -m app.serve --host 127.0.0.1 --port 8000
```

迁移必须先跑；批次 9 真机验收曾据此补齐 `0008_resume_upload_generation.sql`。

后端必须通过 `-m app.serve` 模块入口启动（而不是直接 `uvicorn`）：该入口会在
Windows 上强制切换到 SelectorEventLoop——psycopg 异步驱动与默认的
ProactorEventLoop 不兼容，绕过此入口会在 LangGraph 检查点写入时报错。

也可以使用根目录启动脚本一次拉起迁移、后端和前端：

```powershell
.\start.ps1
```

### 3. 前端

另开终端：

```powershell
Set-Location frontend
npm.cmd install
npm.cmd run dev
```

浏览器访问 `http://127.0.0.1:5173`。前端通过 OpenAPI 快照生成 TypeScript 类型，不应手改 `frontend/src/api/generated.ts`。

## 测试入口

2026-08-09 本轮最终实测结果为：后端 pytest **852 passed**、Vitest **206/206**、
Playwright **28/28**；pyflakes、TypeScript 类型检查与 Vite 生产构建均通过。来源为
`docs/validation/2026-08-09-final-polish-acceptance.md`。批次 9 的 **642 / 105 / 14 / 32**
数字仅是历史冻结口径，见 `docs/validation/2026-08-07-batch9-acceptance.md`。

```powershell
# 后端
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe -m pyflakes app scripts

# 前端单测、类型、构建、端到端
Set-Location frontend
npm.cmd test
npm.cmd run typecheck
npm.cmd run build
npm.cmd run e2e

# OpenAPI 契约链
Set-Location ..
.\.venv\Scripts\python.exe scripts\export_openapi.py
Set-Location frontend
npm.cmd run api:generate
npm.cmd run api:check
```

真机服务启动后，全局冒烟入口为：

```powershell
.\.venv\Scripts\python.exe scripts\global_smoke.py <server-log-path>
```

## 评估入口与已测口径

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_demo_corpus.py --include-raptor --use-cross-encoder
```

版本化产物位于 `data/eval/demo_corpus_cross_v1/`。该实验使用 31,879 个岗位、15 条查询和 852 个池化判定对；标签由 LLM 评审，未经人工复核，Recall 是池内口径，因此适合比较同一批实验通道，不等同于线上真实录用效果。

| 通道 | P@5 | R@10 | MRR | NDCG@5 |
|---|---:|---:|---:|---:|
| base 混合主线 | 0.720 | 0.262 | 0.822 | 0.720 |
| RAPTOR | 0.800 | 0.284 | 0.967 | 0.839 |
| Cross-Encoder | 0.907 | 0.310 | 0.900 | 0.897 |
| RAPTOR + Cross-Encoder | 0.920 | 0.323 | 1.000 | 0.939 |

数字来源：`data/eval/demo_corpus_cross_v1/manifest.json` 与 `docs/validation/2026-08-06-cross-encoder-ablation.md`。不要与不同池化口径的其他轮次直接横比。

## 进一步阅读

- `docs/product_guide.md`：答辩时按用户看到的页面与状态讲产品。
- `docs/code_guide.md`：按模块、文件和关键函数走读实现。
- `docs/project_functionality_and_code_guide.md`：完整功能与代码详解，也是 V2 Word 文档的唯一 Markdown 源稿。
- `docs/validation/2026-08-09-final-polish-acceptance.md`：本轮 UI、清理、交叉审查与最终门禁证据。
- `docs/validation/2026-08-07-batch9-acceptance.md`：历史批次 9 冻结验收与四项测试计数。
- `docs/validation/2026-08-06-cross-encoder-ablation.md`：四通道消融方法与限制。
