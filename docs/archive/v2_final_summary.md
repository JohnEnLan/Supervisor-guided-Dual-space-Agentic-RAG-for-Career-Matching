# 全项目产品与代码总结（V2 终版）

> 定位：毕业设计「Supervisor 监督的双空间 Agentic RAG 职业匹配系统」V2 产品化阶段的收官文档。
> 写法遵循本仓库大白话传统：先说人话，再给文件坐标。所有数字来自真实测试输出，账本诚实——
> 做完的说做完，延期的说延期。
>
> 日期：2026-08-05。分支：`langgraph`。

---

## 1. 这个产品是什么（一段话）

用户打开网页，用邮箱或手机验证码登录，进入一个"职业规划服务群"：群里有四个 AI 角色——
意图顾问（小意）负责多轮启发式咨询、岗位顾问（小检）负责检索匹配、策略顾问（小策）负责简历
与路径建议、项目经理（PM）负责监督和播报。用户上传简历、聊几轮想法，系统生成一张 Match Brief
确认单，确认后后台跑完整的混合检索（SQL 硬过滤 → BM25 ∥ 稠密向量 → RRF 融合 → bi-encoder 排序)
加三 Agent + Supervisor 的 LangGraph 管线，返回分层岗位推荐（Now Fit / Stretch Fit / Bridge
Role），每条推荐都带 JD 原文与简历原文的证据片段，禁止编造。

## 2. V2 六个工作流的成果账本

| 工作流 | 内容 | 提交 | 状态 |
|---|---|---|---|
| W0 | 宪法修订案（CLAUDE_LANGGRAPH.md §5）、v2 执行计划双审终稿、基线清单+数据库快照 | 160973f + 4d25549 | ✅ |
| W2a | 抽取共享上传模块与反馈闭环（为删旧 API 做铺垫） | c444d91 | ✅ |
| W2b | 删除遗留无前缀 HTTP API，只保留 /api/v1 | ea00522 | ✅ |
| W3 | 邮箱+手机双通道 OTP 注册登录、用户记忆绑定、兼容模式 | c28f055 | ✅ |
| W1 | 有界多轮启发式咨询引擎（模板→深化→发散三阶段，8/15 轮上限） | bec9d4b | ✅ |
| W4 | 删旧前端，重建 claude.com 风格群聊应用 + 后端所有权切换 | a51ee02 | ✅ |
| W5 | 31,879 条 LinkedIn JD 转 CN 70% / UK 30% 演示语料并全量入库+切换 | 4a16983 | ✅ |
| 终审修复 | adversarial review 5 项发现全修复 | 5126bd4 | ✅ |
| 冒烟加固 | 全局真机测试暴露的 3 项真实边界缺陷修复 | 9ef078a | ✅ |
| 复审整改 | 修复复审 2 项 P1 + 6 项 P2 + 1 项 P3 全处置（迁移 0007） | 见 git log | ✅ |

每一步都走了「Claude 规划 → 子代理/Codex 双审 → 执行 → 对侧审查 → 收敛」的流程；
测试删减均逐条列账（宪法要求），无静默删除。

### W3 认证（大白话）
- 登录方式：邮箱验证码或手机验证码，二选一，同一个人可以绑两个。
- 验证码是密码学随机数（`secrets`），存库前用 HMAC + pepper 加盐哈希；防爆破用「全局→IP→目标」
  三层 advisory-lock 限速；验证码表有后台清扫协程；发送失败的 challenge 打标志作废
  （行保留供限流计数，验证选取跳过，先前送达的旧码不被遮蔽）。
- 登录成功发 `__Host-app_session` Cookie（JWT，PyJWT 签名），配同源 Origin 校验中间件防 CSRF。
- 兼容模式 `AUTH_ENFORCED=false` 允许无主会话（方便演示与旧测试）；production 强制开启认证，
  且通道配置有矩阵校验（smtp+disabled 合法、console 一律拒绝、双 disabled 拒绝）。
- 所有权矩阵：登录用户只能看自己的会话/运行；他人会话一律 404（防"捡漏接管"）。

### W1 咨询引擎（大白话）
- `app/agents/consult_engine.py`：固定咨询 prompt（顾问人设），阶段由代码决定不由 LLM 决定——
  前几轮走模板必填项（目标/地点/签证），中段针对回答深化追问，尾段发散引导。
- 完成度 = 必填槽位覆盖率×0.6 + min(软偏好数,4)/4×0.4；三个必填槽位（目标、地点或远程、
  签证布尔）填满才允许 finalize。
- 轮次有界：软上限 8 轮、硬上限 15 轮；并发安全用 expected_round CAS（版本不符返回 409）。
- 全部逐轮落库（consult_transcript），刷新页面可完整恢复。
- 真机加固（9ef078a）：LLM 输出的单复数键变体自动归一；role_clusters 锁定受控词表
  （词表外值丢弃，防错误硬过滤清空全部候选）；prompt 明确枚举全部合法键名与簇词表。

### W4 前端（大白话）
- 着陆页：claude.com 风格（米色画布、赭色点缀、衬线大标题），右侧 OTP 登录卡（双 tab、60s 冷却）。
- 登录后进入侧栏应用壳：会话历史、新的咨询、个人档案、评估/监控（答辩模式）、退出。
- 核心是一个"群聊工作台"：上传简历、确认档案、多轮咨询、Brief 确认卡、四角色运行播报、
  结果卡片（证据抽屉+反馈表单）全部发生在同一条群聊时间线里。
- 运行 id 写进 URL（?run=），刷新可恢复；401 全局监听自动回登录页；继续咨询会作废旧确认单
  （防确认到过期画像）；演示语料岗位卡带「演示数据 · CN/UK」虚线徽章。
- 旧前端（onboarding 电影页等 25 个文件）整体删除，复用证据抽屉、反馈表单、评估、监控四件。

### W5 演示语料（大白话 + 数据）
- 转换：源 33,246 行 → 接受 31,879（拒绝 703 公司哨兵、228 JD 边界行、436 规范化重复），
  SHA-256 排序精确配额 **CN 22,315 / UK 9,564**；策展公司池（CN 约 60 家 / UK 约 30 家）与
  城市池确定性映射；两次独立转换字节级一致（可复现）。
- 诚实备注：为对齐历史 31,879 口径，需两条 `Company Page` 伪公司与一条恰 300 字符 JD 的显式
  拒绝规则——规则写在代码与测试里，绝无随机删行凑数。
- 签证合成 CN 4.7815% / UK 34.2116% true；薪资一律不伪造（源值仅存 source_metadata）；
  展示字段碰撞 102 组 204 行，只记录不删行。
- 全链路标记：检索 SELECT → JobCandidate → ranking_scores → 发布门（demo 行缺标记拒绝发布）→
  RecommendationResult（demo_synthetic / country_code）→ 前端徽章。production 启动探测到开放
  demo 行且未显式 `DEMO_CORPUS_ENABLED=true` 即拒绝启动。
- 全量导入实测：**31,879/31,879 岗、120,584/120,584 块、64/64 窗口**（58 新 + 6 preview 复用），
  1,929.6 秒（32.2 分钟）。九项深度对账全部精确：国别配额、0 缺标记、0 空向量、0 异常维度、
  签证 CN 1,067 / UK 3,272 true。
- 正式 cutover 已执行：demo 31,879 条开放、legacy 0 条开放、快照表保留 50 行 legacy 原始
  开关状态可随时回滚；cutover 与运行入队之间有数据库 advisory-lock 围栏（终审修复 F2/F3）。

### 终审五项修复（5126bd4）
| 级别 | 发现 | 修复 |
|---|---|---|
| critical | production 无合法 OTP 配置（SMS 只有 console 却被禁）→ 生产永远起不来 | 双通道加 disabled；只校验启用通道；配置矩阵测试 |
| high | cutover 与新执行入队无围栏，可产生跨语料混合结果 | 入队共享锁 ↔ cutover 排他锁 + 事务内复查 |
| high | rollback 盲目重开原本已关闭的旧岗位 | 逐行快照 is_open，rollback 按快照恢复 |
| high | 前端旧确认单不随继续咨询作废，可确认到过期画像 | 咨询成功即作废草稿；Playwright 断言 |
| medium | OTP 发送失败的新 challenge 遮蔽仍有效的旧码 | 失败即删 challenge，对外仍统一 202 |

## 3. 系统架构总览

```
浏览器 (React 19 + Vite + TanStack Query)
   │  /api/v1（openapi-typescript 生成类型，__Host- Cookie 会话）
   ▼
FastAPI（app/serve.py 入口，Windows 上强制 SelectorEventLoop）
   ├─ auth 层：OTP → JWT Cookie → 属主依赖注入 → Origin 同源校验
   ├─ v1 路由：sessions / runs / feedback / monitoring
   ▼
LangGraph 1.2.9 StateGraph（app/graph/）
   Stage0 归一化 → Stage1 意图 → Stage2 规划 → Stage3 检索匹配 → Stage4 策略 → Stage5 终核
   检查点：AsyncPostgresSaver（psycopg3 独立池，终态删检查点保护隐私）
   ▼
PostgreSQL 17 + pgvector（vector(1024) HNSW 余弦 + GIN tsvector）
   同库存放：JD 向量（31,879 条 CN/UK 演示语料）、会话状态、用户账号、咨询转录、反馈、监控读模型
```

并发与安全要点：asyncpg 连接池；LLM/embedding 全部过 Semaphore；有界循环（clarification /
re-retrieval / repair 各最多 1 次，咨询 8/15 轮）；硬过滤只走 SQL 不过 LLM；证据片段全程可追溯；
语料切换与运行执行之间有数据库级围栏。

## 4. 代码文件地图（大白话逐目录）

### app/ 后端
| 位置 | 干什么的 |
|---|---|
| `app/serve.py` | 服务入口。Windows 上 uvicorn 默认事件循环与 psycopg 冲突，这里用 asyncio.Runner 换成 SelectorEventLoop |
| `app/config.py` | 读 .env 的集中配置 + production 安全校验（认证/密钥强度/OTP 通道矩阵/演示语料开关） |
| `app/api/main.py` | FastAPI 应用与 lifespan：安全校验、OTP 清扫协程、检查点池与清扫、演示语料探测、Origin 中间件 |
| `app/api/auth/` | W3 认证全家桶：`otp.py` 验证码生命周期、`sessions.py` JWT Cookie + Origin 校验、`deps.py` 属主依赖、`routes.py` 端点、`providers.py` 发送通道（console/smtp/disabled） |
| `app/api/v1/` | 对外 API：`sessions.py`（会话/简历/咨询/Brief）、`runs.py`（执行/状态/群聊播报/结果）、`schemas.py`（全部 DTO）、`feedback.py`、`monitoring.py` |
| `app/api/uploads.py` | W2a 共享上传模块（大小/类型校验、落盘） |
| `app/api/result_projector.py` / `conversation_projector.py` | 内部运行状态 → 前端结果卡片 / 群聊播报（含 demo 标记透传与拦截） |
| `app/graph/` | LangGraph 装配：`state.py` 图状态、`nodes.py` 六阶段节点、`build.py` 建图、`runner.py` 驱动与检查点 |
| `app/agents/` | 三业务 Agent + Supervisor（发布门在 `supervisor_harness.py`）+ 咨询引擎 `consult_engine.py` |
| `app/retrieval/` | 混合检索：`hybrid_search.py` 主流程（含 demo 列透传）、`rrf.py` 融合、`dual_space_search.py` 双空间、`raptor.py`（P2 留接口） |
| `app/normalization/resume_intake.py` | Stage0：简历解析→归一化→evidence_spans（禁编造的根基） |
| `app/db/` | `pool.py` 连接池、`state_store.py` 按 session_id 读写状态、`run_store.py` 运行生命周期（含入队围栏锁）、`corpus_lock.py` 语料切换锁键、`migrations/` 0001–0006+回滚 |
| `app/memory/` | 私有记忆、反馈闭环、匿名案例库（P1 机制演示） |
| `app/evaluation/` | Recall@K / MRR / NDCG 指标与评估工件 |
| `app/llm/` | DeepSeek 与 Qwen embedding 异步客户端 + Semaphore + 上下文预算 |
| `app/domain/` | 领域模型：意图、Match Brief、运行、结果（RecommendationResult 含 demo 字段）、监控 |
| `app/state/schema.py` | Shared Structured State 数据契约（单一事实来源） |

### frontend/src/ 前端
| 位置 | 干什么的 |
|---|---|
| `v2/LandingPage.tsx` | 着陆页 + OTP 登录卡（邮箱/手机双 tab，60s 冷却） |
| `v2/AppShell.tsx` | 登录后侧栏壳（会话列表、档案、评估/监控入口、登出） |
| `v2/WorkbenchPage.tsx` | 核心群聊工作台（上传→咨询→确认单→播报→结果→反馈一条时间线） |
| `v2/ProfilePage.tsx` | 账号信息 + 记忆档案展示 |
| `v2/theme.css` | claude.com 风格设计令牌 + 演示数据徽章样式 |
| `api/generated.ts` | openapi-typescript 自动生成的类型（不手改） |
| `api/client.ts` / `queries.ts` | fetch 封装（credentials + 401 监听）与全部 API 方法 |
| `features/` | 复用件：证据抽屉、反馈表单、评估页、监控页 |
| `e2e/` | Playwright：全流程之旅（登录→反馈，含确认单作废与演示徽章断言）、未登录重定向、刷新恢复、监控页 |

### scripts/ 与 docs/
| 位置 | 干什么的 |
|---|---|
| `scripts/load_jobs.py` | 原始 JD 入库（切块/embedding/tsvector） |
| `scripts/transform_jobs_cn_uk.py` | W5 确定性转换（配额/公司池/城市池/签证/碰撞报告/manifest） |
| `scripts/import_cnuk_demo.py` | 分窗可续跑导入（500 行窗口、4 worker、指纹锁定、断点续跑） |
| `scripts/cutover_cnuk_demo.py` / `rollback_cnuk_demo.py` | 严格离线切换（活跃 run 拒绝 + 围栏锁 + 快照回滚） |
| `scripts/global_smoke.py` | 31 项全局真机冒烟矩阵（演示前彩排可复跑） |
| `docs/v2_redesign_plan.md` | V2 执行圣经（v3 终审稿，双审通过） |
| `docs/code_guide.md` / `product_guide.md` | 大白话双册 |
| `docs/auth_technical_design.md` | 登录技术书（Google/微信/短信的后续路线） |
| `docs/validation/` | 基线清单、W5 语料 manifest 与验证报告（含 cutover 演练记录） |
| `docs/known_issues.md` | 诚实已知问题清单 |

## 5. 测试与验证记录（全部真实输出）

| 关口 | 结果 |
|---|---|
| 后端 pytest 全量 | **416 passed**（W4 时 375 → W5 +22 → 终审修复 +10 → 冒烟加固 +5 → 复审整改 +4） |
| pyflakes | 干净 |
| 前端 typecheck / vitest / build | 0 错误 / 12 passed / 通过 |
| Playwright e2e | **5/5 passed**（含确认单作废、演示徽章断言） |
| W5 trial 100 / preview 3000 | 通过（真实 PG + DashScope，0 异常维度、0 缺标记） |
| W5 全量导入 + 九项对账 | 31,879 岗 / 120,584 块，全部精确命中 |
| cutover 正反演练 + 正式切换 | 通过（混合开关行逐行还原验证；正式切换后 demo 全开 legacy 全关） |
| **全局真机冒烟（AUTH_ENFORCED=true）** | **32/32 passed**：双通道注册登录、错码拒绝、多轮真实 LLM 咨询、CAS 409、刷新恢复、plan_ready 阶段错 hash 409、真实向量检索出 5 条带证据推荐（demo 标记全可见）、四角色播报全量断言、反馈落库、非法值 422、双用户所有权矩阵 404、匿名 401、错误路径全套 |
| V2 全分支 adversarial review | needs-attention（5 项）→ 全修复（5126bd4） |
| 修复复审（Codex 二审） | 2 项 P1 + 6 项 P2 + 1 项 P3 → 全处置：OTP 失败行保留限流记录不再可绕过（迁移 0007 delivery_failed 标志）、production 缺 SMTP 配置拒绝启动、cutover 哨兵行保证干净部署可回滚、capabilities 暴露可用登录通道且前端隐藏禁用 tab、feedback 只对 outcome 词表错误回 422、冒烟脚本夹具自动生成/时序修正/四角色全量断言 |

全局冒烟还额外暴露并修复了三项只有真机才能发现的缺陷（LLM 键名变体、簇词表错配、
反馈 500），详见 9ef078a 提交说明——这正是"自己跑一次全局测试"的价值。

## 6. 诚实账本：边界与已知事项

- **演示语料是合成的**：CN/UK 公司映射纯为演示效果（不作为实际产品上线），全链路
  demo_synthetic 标记 + 发布门校验 + 前端徽章；薪资一律不伪造。
- **P2 仍是接口预留**：RAPTOR 层级树、cross-encoder 重排未进主线（符合一个月范围纪律）。
- **邮件/短信真实发送**：开发/演示模式走 console provider（验证码打印到服务器日志）；
  SMTP 已实现可配，真实短信网关是后续接线项（production 配置矩阵已把好关）。
- **__Host- Cookie 与 http**：浏览器对 localhost 有 Secure 豁免所以前端正常；非浏览器客户端
  （如脚本）需手动携带 Cookie 头（global_smoke.py 已内置处理）。
- **tmp/pt\* 残留目录**：Codex 沙箱 ACL 导致普通权限删不掉，需手动管理员清理（不影响运行）。
- **W5 转换产物**：145MB CSV 与 manifest 在 `outputs/w5/`（已 gitignore），源数据集不入库不入 git。
- **已知问题清单**：`docs/known_issues.md`（含 resume-preview 409 双义等，前端已消歧）。

## 7. 怎么跑起来

```
# 后端（Windows；start.ps1 内部走 python -m app.serve）
.\start.ps1

# 前端
cd frontend ; npm run dev

# 后端测试 / 前端四门
.venv\Scripts\python -m pytest tests/ -q
cd frontend ; npm run typecheck ; npm test ; npm run build ; npx playwright test

# 全局真机冒烟（演示前彩排；-u 防 stdout 缓冲吞掉验证码）
$env:AUTH_ENFORCED = "true" ; .venv\Scripts\python -u -m app.serve *> tmp\smoke_server.log
.venv\Scripts\python scripts\global_smoke.py tmp\smoke_server.log
```

环境依赖：PostgreSQL 17 + pgvector、`.env`（DeepSeek/DashScope 密钥等，模板见 `.env.example`）。
