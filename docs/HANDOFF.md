# 交接文档：给下一位 AI 协作者（Codex）

> 更新时点：2026-08-10 本地品牌强化验收；当前 `langgraph@d423a4b`
> 已完成前端门禁与双审。最终 `d423a4b` **尚未推送**，当前分支没有 upstream；
> 并发任务曾意外把非最终 `a4a8e44` 推到 `origin`/`gitlab` 的 `main`/`langgraph`。
> 本轮没有执行服务器部署，也没有核验服务器当前版本。
> 本文回答三个问题：项目现在什么状态、改动怎么做才合规、上线怎么操作。
> 裁决链（冲突时从高到低）：`CLAUDE_LANGGRAPH.md` §5 V2 修订案 →
> `CLAUDE.md` / `AGENTS.md`（宪法，Codex 会自动读取 AGENTS.md）→
> `docs/v3_product_iteration_plan.md` → 本文。

## 1. 一句话与现状

Supervisor 监督的双空间 Agentic RAG 职业匹配系统（伯明翰 CS 硕士毕业设计）。历史资料记录的
站点为 https://zhangen.cn （香港服务器 45.153.131.127，Ubuntu 22.04）；本轮未核验服务器，
不能从远端 Git 状态推断线上代码。最终 `d423a4b` 品牌强化版尚未推送，本轮也未执行部署。

**产品品牌（B9 起）**：英文名 **Career Arbor**，中文名 **枝涯**，口号
「循枝见路，向远而生」，定位句「枝涯 — 你的 AI 职业路径智能体 /
Career Arbor — Your AI Career-Path Agent」。品牌串只存在于前端
（wordmark、document.title、index.html、i18n 词条），后端无品牌字样。
架构定性口径（答辩/文档统一）：supervisor 多智能体 + LangGraph 图编排
workflow（plan-and-execute，非 ReAct）+ verify 处单条有界自反回路。`langgraph` 分支只授权
LangGraph 作为编排/checkpoint 例外；三个业务 Agent 仍是共享状态的异步函数与独立 LLM 调用，
不引入 AutoGen、CrewAI 或 LangChain 应用栈。

历史批次（已封批；部署状态以对应发布记录为准）：

| 批次 | 内容 | 封批/关键提交 |
|---|---|---|
| W1-W4 | 主线 RAG + 三 Agent + Supervisor + FastAPI + 群聊前端 + 认证 | — |
| 批 9/10 | RAPTOR + cross-encoder 双增强、评估消融 | — |
| B2 | 上传确认制 + 解析限额 3 次/会话（防烧钱） | eba9148 |
| B1 | 前端体验包（消息逐条、对齐、折叠） | 3674b4d |
| B3 | 小意解析叙事 + 计时（migration 0010）+ 热情人设 | 173e018 |
| B4 | 视觉 OCR 兜底（qwen-vl，扫描件/图片简历） | 5940917 |
| B5 | LLM 用量计量 + 管理员控制台（migration 0011，R9/R10） | e9df282 |
| B6 | 全局中英文切换（右上角按钮） | 8db35d4 |
| B7 | 三缺陷热修（确认后连续性/预览滚动/宽屏列） | 2aa4037 |
| B8 | 结果呈现十项改进（表格化/去 JSON/小策播报等） | 5eac4f3 |
| 2026-08-09 收尾 | 顾问关系图、双语品牌主页链接、侧栏对齐、保守冗余清理 | 本地工作树，未部署 |
| 2026-08-10 品牌强化 | wordmark 枝条反馈、主页品牌层级、P3 英文分层防溢出 | `d423a4b`，本地验收；最终版未推送，本轮未执行部署 |

数据库迁移已应用至 **0011**（生产验证口径：查 `schema_migrations` 表，
migrate 脚本永远静默）。

## 2. 必读文档地图

| 文件 | 作用 |
|---|---|
| `CLAUDE.md` / `AGENTS.md` | **基础宪法**。无状态服务、asyncio、三 Agent 独立调用、有界循环、硬过滤走 SQL、evidence_spans 防编造、Semaphore 限流、一次一个模块；LangGraph 仅按上级修订案在本分支获得例外授权。 |
| `docs/v3_product_iteration_plan.md` | v3 十需求的权威方案（B2-B5 细节） |
| `docs/deploy_guide.md` | 部署/升级/运维手册（含 B5 运维段、break-glass、B3 红线） |
| `docs/product_guide.md` / `docs/code_guide.md` | 产品走读 / 代码走读（锚点 de2fd83，行号会漂移） |
| `docs/known_issues.md`、`docs/limitations_and_future_work.md` | 已知问题与展望 |
| `.env.example`、`deploy/env.production.template` | 配置模板（生产模板禁真实邮箱/密钥） |
| `docs/DEPLOY_FOR_AI.md` | **「上传服务器/部署」的确切含义与分工**——用户说"上线/部署/传服务器"时先读这个 |
| `README.md` | **本地启动方式**（`start.ps1` / `python -m app.serve` 模块入口）——dev 服务怎么跑起来看这里 |
| `docs/INDEX.md` | 仓库文档总地图（论文材料、validation 证据链） |
| `docs/validation/2026-08-10-career-arbor-brand-polish-acceptance.md` | 当前前端品牌强化验收、双审与发布边界 |
| `CLAUDE_LANGGRAPH.md` | §5 V2 修订案（裁决链最高层） |

## 3. 改动怎么做（工程约定）

### 3.1 验收门（每次改动全过才算完成）

```powershell
# 后端（venv + 短路径 basetemp，规避 Windows 260 字符与 ACL 残留）
.venv\Scripts\python.exe -m pytest tests -p no:cacheprovider --basetemp C:\Users\WIN11\AppData\Local\Temp\crtest_XXX -q
# 前端三门 + e2e
cd frontend; npm test; npm run typecheck; npm run build; npm run e2e; cd ..
```

当前最新前端验收基线：Vitest **207/207（16 files）**、e2e **43/43**、TypeScript
类型检查与生产构建（1858 modules）全绿；`final-06` 的 13 张截图已逐张复核。完整证据见
`docs/validation/2026-08-10-career-arbor-brand-polish-acceptance.md`。本轮纯前端，未重跑
后端；后端 **852 passed** 是 2026-08-09 的已知基线，见历史报告
`docs/validation/2026-08-09-final-polish-acceptance.md`。OpenAPI 有变更时：
`python scripts/export_openapi.py` 再 `cd frontend && npm run api:generate`，
快照在 `tests/snapshots/openapi_v1.json`。

### 3.2 红线（改坏必炸，测试有守卫）

- **i18n 三层口径**（B6）：前端静态串全译（中文原文为键，词典
  `frontend/src/i18n/en.ts`）；后端零插值固定串收录在词典
  `BACKEND_SOURCE_KEYS` 标记区，`scripts/check_i18n_backend_drift.py`
  做 AST 存在性校验——**改后端文案必须同步词典标记区**。注意守卫只扫
  两个白名单文件（`api/conversation_projector.py`、`api/v1/sessions.py`，
  见脚本 `BACKEND_SOURCE_FILES` 常量），在其他后端文件新增固定文案要
  进词典时需同步扩该常量；
  `user_message / assistant_reply / next_question / Supervisor note /
  数据字段 / LLM 内容` 永不入词典、渲染不包 t()（用户答"无"不能被译）。
- **evidence 红线**：简历建议/匹配解释必须指回 evidence_span_ids，
  contact 字段逐字 exact-substring 校验（`resume_intake.py`）。
- **B3 红线**：任何把同一代重新置回 `resume_queued` 的路径必须先
  `DELETE FROM resume_intake_progress`（详见 deploy_guide 原文）。
- **?raw 守卫**：`frontend/src/v2/WorkbenchPage.test.tsx:167-168`（行号会
  漂移，认断言内容）用源码断言钉住依赖数组
  `[status.data, runId, execute.mutate]` 的 effect，禁止重构该 effect。
- **B2 换代语义**：上传即换代，旧代亲历/补拉/done 缓存全作废
  （WorkbenchPage upload onSuccess 注释区）。
- 管理员鉴权四重（email 票 + 白名单 + 实时 is_admin + token_version），
  `ADMIN_EMAILS` 改动需重启+重登；break-glass 见 deploy_guide。

### 3.3 已知踩坑（本机 Windows 开发）

- 本地 dev 登录三件套：vite 代理需 `changeOrigin: false`（后端同源校验）；
  手机验证码走 console provider，验证码打在后端 stdout；浏览器隐藏时
  TanStack 轮询暂停（自动化复现需劫持 `document.visibilityState`）。
- 本地库欠迁移时 `python -m app.db.migrate` 补齐。
- 你的沙箱大概率跑不了 Playwright（chrome-headless-shell 崩溃/spawn
  EPERM）与 vite 默认 config loader（`--configLoader native` 绕过）；
  pytest 的 tmp_path 会遇 ACL WinError 5——用短路径 basetemp。跑不了的
  门禁要在交付说明里声明，由人工在非沙箱终端补跑。
- `git commit -m` 多行消息在 PowerShell 里易碎——写消息文件用 `-F`。
- 测试端口检查（test_windows_launcher）要求 8000/5173 空闲，跑全量前
  关掉本地 dev 服务。

## 4. 上线怎么操作（部署手册速览）

**铁律：服务器凭据永远由用户本人输入执行；你只产出可粘贴命令。**
完整流程见 `docs/deploy_guide.md`「升级部署」节；速览：

```bash
# ① 本机打包（项目根）
git archive --format=tar.gz -o app.tar.gz HEAD
cd frontend && npm run build && cd .. && tar -czf frontend-dist.tar.gz -C frontend/dist .
# ② 用户执行上传
scp app.tar.gz frontend-dist.tar.gz root@45.153.131.127:/opt/career-rag/
# ③ 服务器：后端先行 → 前端原子切换（顺序写死，防新前端撞旧后端）
cd /opt/career-rag && tar -xzf app.tar.gz -C app && chown -R career:career app
sudo -u career ./venv/bin/pip install -r app/requirements.txt   # 有新依赖时
(cd app && sudo -u career ../venv/bin/python -m app.db.migrate)  # 有新迁移时
sudo -u postgres psql -d career_rag -c "SELECT name FROM schema_migrations ORDER BY name DESC LIMIT 3;"
systemctl restart career-rag && sleep 8 && curl -s http://127.0.0.1:8000/api/v1/capabilities
REL=/opt/career-rag/releases/frontend-$(date +%Y%m%d%H%M) && mkdir -p "$REL" \
  && tar -xzf frontend-dist.tar.gz -C "$REL" \
  && ln -sfn "$REL" current.tmp && mv -Tf current.tmp frontend-current
```

回滚：前端把 `frontend-current` 软链指回上一 releases 目录；功能开关在
`.env`（重启生效）。管理员登录邮箱见 `.env` 的 `ADMIN_EMAILS`（生产已配）。

## 5. 挂账清单（都不阻塞，按需处理）

1. B8 微瑕：需求摘要里岗位簇枚举值未映射中文（如 `marketing_sales`）；
   run 结束后 composer 提示语仍"任务执行中"。
2. B5 备忘（scratchpad 已失效，此处为准）：计量熔断阈下失败无日志；
   探针单飞缺并发测试用例；contact 空串 vs null 前端显示边线；
   checkpointer 送达断言可加强；J-1 内层 purpose 细分（supervisor/
   strategy/explain）为可选增强未做。
3. B6 备忘：en 模式切换钮显示 "Chinese"（原案 "中"）；漂移守卫是单向
   （词典→源码），后端新增固定文案漏收词典不会预警；en-notice 键为英文
   原文（风格破例）。
4. 运维站桩：QQ SMTP 授权码答辩前轮换；R8 三档对齐截图待线上采集。

## 6. 终局快照与仓库现状（2026-08-10 品牌强化）

- 当前分支为 **langgraph**，实现与验证 HEAD 为 `d423a4b`，且没有 upstream。只读远端核验显示，
  并发任务曾意外把非最终 `a4a8e44` 推到 `origin/main`、`origin/langgraph`、
  `gitlab/main`、`gitlab/langgraph`；最终 `d423a4b` 尚未推送。
- 本轮没有执行服务器部署，也没有核验服务器当前代码；不能根据 Git 远端状态推断线上版本。
  需要发布时按 §4、`docs/DEPLOY_FOR_AI.md` 与 `docs/deploy_guide.md` 操作。
- 本轮已完成：全局“枝涯 / Career Arbor”放大与枝条反馈；主页品牌名/标语层级强化；
  P3 英文分层统一为 `Now Fit / Stretch Fit / Bridge Role` 并保持在分层列内；
  320/375/650/1280px、键盘焦点、低动态和对比度均有回归覆盖。
- 最终前端门禁：Vitest 16 files / 207 tests、typecheck、Vite build（1858 modules）、
  Playwright `career-arbor-20260810-011800996/final-06` 43/43 全绿；13 张截图人工检查通过。
  后端 852 项是 2026-08-09 已知基线，本轮未重跑。
- 冷态恢复测试曾暴露测试自身的时序竞态，已用 deferred mock 稳定化；它不是产品 bug，
  没有改变生产恢复逻辑。
- 实施前规格/计划与实施后代码均完成主审和独立复核，最终所有 severity 为 0，
  Spec compliance 与 Code quality 均通过。
- 2026-08-09 的 `.superpowers`、临时输出和过程文件归档仍是历史记录，路径为
  `C:\Users\WIN11\Desktop\毕业论文_birmingham\项目过程档案\2026-08-09_career_arbor_final_polish\`；
  不要把它误写成本轮归档。
- 本轮并发收尾时曾意外创建
  `C:\Users\WIN11\Desktop\毕业论文_birmingham\项目过程档案\2026-08-10_brand_emphasis\`。
  工作区已从副本恢复，但档案副本未删除、未合并；其保留、改名或清理必须由用户决定。
  本轮 cleanup dry-run manifest 已生成；计划归档目标 `2026-08-10_career-arbor-brand-polish`
  的用户批准、实际移动与最终交接仍 pending。
- 用户答辩 Word 材料的 2026-08-10 原子替换是上一任务的历史成果；本轮没有更新 Word。
- `frontend/dist`、`app.tar.gz`、`frontend-dist.tar.gz` 继续作为部署候选保留，不因清理候选而移动。
- 清理纪律：项目过程文件先列 dry-run 并由用户逐项批准；不直接删除，依赖项不得只凭静态扫描删除。

## 7. 工作方式约定（沿用）

- 一次一个模块，跑通再下一个；先写清输入/输出契约再动手。
- 改动面白名单制：只动说好的文件；执行者自查后由协调者/用户复核。
- 测试是行为契约：既有测试零改动零红是默认等价线，行为变更须逐处列出
  改了哪些断言、为什么。
- 提交规范：`type(scope): summary`，正文说清动机与验证结果。
