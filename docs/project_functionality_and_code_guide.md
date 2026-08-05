# Career-RAG 功能与代码详解（V2 终版 · Word 文档源稿）

> 这份文档回答两个问题：**这个系统到底做了什么**（功能篇，给任何人看），
> **每一部分是怎么实现的、代码在哪**（代码篇，给读代码的人看）。
> 所有描述以当前 `langgraph` 分支代码实查为准，不是设计愿景。
> 行号引用以 2026-08-05 HEAD 为准，重构后以函数名检索为准。

---

# 第一篇 功能：这个系统做什么

## 1. 一句话与一段话

**一句话**：一个"職业顾问团队群聊"——你上传简历、聊几句想法，四个 AI 角色协作着
给你可验证的岗位推荐和职业建议。

**一段话**：用户用邮箱或手机验证码登录，进入"职业规划服务群"。群里四个角色各司其职：
**小意**（意图顾问）负责多轮启发式咨询，把模糊想法聊成结构化目标；**小检**（岗位顾问）
负责在 31,879 条岗位库里做混合检索与匹配；**小策**（策略顾问）负责简历修改建议、
能力缺口与职业路径；**PM**（项目经理）在每个环节前后做质量把关，不合格就打回重做。
最后交付：三层岗位推荐（现在就投 / 值得冲刺 / 跳板岗位），每条都附 JD 原文和简历
原文的证据片段——系统的核心承诺是**不编造**：说你匹配，就指得出原文依据。

## 2. 一次完整的使用旅程（页面级）

1. **着陆页**（claude.com 风格）：右侧登录卡，邮箱/手机验证码二选一，首次登录自动
   注册。服务端只展示可用通道（如生产环境未接短信，手机 tab 自动隐藏）。
2. **应用壳**：左侧边栏是会话历史（每人 3 个会话额度，超出弹付费墙）、个人档案、
   答辩用的评估/监控入口。点「新的咨询」进群。
3. **群聊工作台**（核心页面，一条时间线完成所有事）：
   - PM 开场 → 上传简历（PDF/DOCX/TXT）→ 小意报告归一化结果（几段教育/经历/技能，
     全部带原文出处）→ 用户点「确认简历档案」；
   - 与小意多轮咨询：前几轮问必填槽位（目标、地点、签证），中段深挖偏好，
     信息够了 PM 提示可生成 **Match Brief 确认单**；继续聊会作废旧确认单（防过期确认）；
   - 点「确认无误，开始匹配」→ 后台跑完整管线，四角色在群里实时播报进度；
   - 结果卡片：岗位分层、匹配解释、「查看证据」抽屉（JD 原文片段 + 简历原文片段）、
     反馈表单；演示语料岗位带「演示数据 · CN/UK」虚线徽章。
4. **刷新恢复**：运行 id 写在 URL 里，中途刷新/换设备登录都能回到原进度。

## 3. 系统承诺（产品可信度的四根柱子）

1. **硬条件不交给 AI**：签证、地点、岗位开放状态由 SQL WHERE 子句判定，模型无权放宽。
2. **证据可追溯**：每条推荐的解释都锚定 JD 原文片段；每条简历建议只能引用真实经历
   （evidence_spans 机制）；发布门检测到无证据推荐直接拦下。
3. **过程受监督**：Supervisor 在规划与终核两个关口核查，允许一次有界的重检索/修复
   循环，全程留痕（supervisor_log），答辩可回放。
4. **演示语料全程亮牌**：31,879 条岗位是真实 LinkedIn JD 经确定性变换的合成演示语料
   （公司/城市映射、签证合成、薪资不伪造），demo_synthetic 标记从数据库列一路带到
   前端徽章，生产模式未显式声明就拒绝启动。

---

# 第二篇 代码：每一部分怎么实现

## 4. 架构总览

```
浏览器  React 19 + Vite + TanStack Query（frontend/src/v2 群聊界面）
   │ /api/v1 · openapi-typescript 生成类型 · __Host- Cookie 会话
   ▼
FastAPI  app/serve.py（Windows 强制 SelectorEventLoop）→ app/api/main.py lifespan
   ├── auth 层：OTP → JWT Cookie → 属主依赖 → Origin 同源校验
   ├── v1 路由：sessions / runs / feedback / monitoring
   ▼
LangGraph 1.2.9 StateGraph（app/graph）
   intent → lock_brief → retrieve_match → strategy → verify →(有界循环)→ publish
   检查点 AsyncPostgresSaver（psycopg3 独立池；终态删检查点保护隐私）
   ▼
PostgreSQL 17 + pgvector（vector(1024) HNSW 余弦 + GIN tsvector + advisory locks）
```

## 5. 六阶段管线（app/graph + app/agents）

图装配在 `app/graph/build.py`：七个节点、START→intent 起步、`route_after_verify`
决定 publish 还是回 `prepare_reretrieval`（有界一次）。`GraphState`（graph/state.py）
是 TypedDict：shared（SharedState）+ brief + retrieval_plan + verification +
loops 计数器 + stage_timing（存墙钟不存 perf_counter，跨进程续跑不出错——nodes.py 头注释）。

| 阶段 | 节点/代码 | 干什么 |
|---|---|---|
| Stage0 归一化 | `normalization/resume_intake.py` | PDF/DOCX/TXT 抽文本 → 切 evidence_spans（≤120 段）→ LLM 结构化（pydantic 白名单校验）→ 落库。这是"不编造"的地基 |
| Stage1 意图 | `agents/intent_agent.py` | 咨询已完成时跳过（skip_agent=intent_consulted）；否则从 brief 目标文本抽取画像 |
| Stage2 规划 | `agents/supervisor.py::plan_retrieval` | 构造 retrieval_plan（含 include_raptor / use_cross_encoder 等开关快照），写 planning 日志 |
| Stage3 检索匹配 | `agents/matching_agent.py` → `retrieval/` | 见 §6 |
| Stage4 策略 | `agents/strategy_agent.py` | 简历修改计划 / 缺口 / 路径，每条建议过证据白名单（_filter_supported_items） |
| Stage5 终核 | `supervisor.py::final_verification` + `supervisor_harness.py` | 确定性核查（硬约束违例、证据缺失、demo 标记缺失即拦）+ 发布门；可触发一次 re-retrieval/repair |

编排双轨：`agents/orchestrator.py` 是原生 harness（LangGraph 关闭时的回退与
characterization 基准），`graph/runner.py::run_graph_match` 是 LangGraph 主轨——
启动/续跑/幂等读一体，崩溃后从检查点续跑（tests/test_run_recovery 系列在真实 PG 验证）。

## 6. 检索栈（app/retrieval）——本系统的技术心脏

`hybrid_search.py::hybrid_search` 的完整流水：

1. **硬过滤**（SQL）：`query_builder.py` 把 hard_constraints 翻译成 WHERE
   （locations/role_clusters/visa/学历/年限/is_open），产出 allow_ids 白名单；
2. **双路召回**（asyncio.gather 并行）：BM25（Postgres tsvector `ts_rank`）∥
   dense（pgvector HNSW 余弦，Qwen embedding 1024 维）；开 RAPTOR 时第三路走
   摘要节点树（见下）；
3. **RRF 融合**：`rrf.py`，倒数排名融合多路 chunk 命中，塌缩到 job 粒度；
4. **bi-encoder 加权排序**（`_rerank_candidates`）：
   `0.30×RRF + 0.10×BM25 + 0.60×max(dense, raptor) + 软偏好加分(≤0.28) + 字段加分(≤0.20)`；
5. **cross-encoder 精排**（可选，默认关；`app/llm/reranker.py` + hybrid 集成）：
   DashScope `gte-rerank-v2` 把「查询+JD」拼一起打分（bi-encoder 是双塔各自编码，
   看不见词级交互；cross-encoder 能看出"要求 5 年 Java"≠"我有 5 年 Python"）。
   设计要点（经子 agent 与 Codex 四轮对抗评审双 APPROVE，docs/cross_encoder_plan.md）：
   - 只精排融合池前 N（默认 20）个候选，**applied_window 单调分数重映射**——
     窗口内顺序完全由 cross 决定，但分数仍落在原区间内（与窗口外同尺度、全局单调，
     双空间 β 混合语义不被破坏）；provider 全平分时保持基线惰性；平分场景靠新增
     cross_rank 平局键；
   - **懒降级**：任何可降级失败（超时/5xx/预算不足/文档 SQL 异常）直接以关闭开关
     复跑同一检索路径——"降级 = 关闭路径"由构造保证，绝不让精排故障弄坏主线；
     配置错误（端点缺失/401）则响亮报错不静默；
   - **单请求红线**：DashScope 分数禁止跨请求比较，预算按 CJK 感知三层核算
     （中文 1 字符/token），requested/effective 双记账；
   - 真机实测：经典公共端点单次 135–237ms，中英 query 契约一致；开着精排跑
     P1 persona，5 条结果 cross 字段全落袋且 Top-5 重排（SQL Developer 等
     强相关岗被提前），关闭回归与基线一致。
6. **双空间融合**（`dual_space_search.py`）：显式空间（JD 匹配）β 混合隐式空间
   （匿名案例库的相似简历成功轨迹），有案例证据时可调整排序并附 implicit 证据；
7. **三分层**：matching_agent 按分数与缺口把 Top-K 标为 now_fit / stretch_fit /
   bridge_role，并为 Top 岗位并行生成带证据的匹配解释（Semaphore 限流）。

**RAPTOR-lite**（`raptor.py`，674 行）：离线为每个岗位建"摘要节点"（标题+元数据+
关键职责的确定性压缩文本 + 向量），再按 role_cluster 建 7 个角色汇总节点；检索时
先命中节点再展开到原文 chunk（propagate 时按层级衰减 0.65）。全量索引 31,886 节点。
两个已修缺陷：全量重建做代际清理（旧语料节点不残留）；role 节点受 allow_ids
交集约束（不绕硬过滤）。消融实测（15 查询 LLM 池化标注）：hybrid P@5 0.720 →
+RAPTOR **0.853**，MRR 0.822 → **0.967**。

## 7. 咨询引擎（agents/consult_engine.py）

- **阶段机由代码定**（determine_phase）：template（必填槽位：目标、地点或远程、
  签证布尔）→ deepen（偏好不足 2 项或未表态避雷时追问）→ explore（发散引导）。
  LLM 只提供话术，流程不交给它。
- **完成度公式**：必填覆盖率×0.6 + min(软偏好数,4)/4×0.4；can_finalize=三槽全满。
- **轮次有界**：软上限 8（可配）、硬上限 15；并发安全靠 expected_round CAS（409）。
- **真实 LLM 加固**（真机测试换来的三课）：①单复数键变体归一化（location:["上海"]
  不再炸整轮）；②role_clusters 锁定 11 词受控词表，词表外丢弃（防中文自由文本
  进 SQL 硬过滤清零结果）；③坏输出有界重试一次（CONSULT_LLM_ATTEMPTS=2），
  失败轮次不留 state 痕迹。
- 转录逐轮落库（consult_transcript），刷新可恢复；finalize 产出 Brief 草稿。

## 8. 认证与多租户（app/api/auth）

- **OTP**：CSPRNG 六位码，HMAC+pepper 哈希存库；签发限流三层（目标 1/分 5/时 10/天、
  IP 20/时、全局 1000/天，advisory-lock 串行化）；验证限速 + 5 次尝试上限；
  发送失败打 delivery_failed 标志（保留限流计数、验证选取跳过、旧码不被遮蔽）；
  通道可配 console/smtp/disabled，生产拒 console、smtp 必须配全、至少一通道启用。
- **会话**：JWT（PyJWT，token_version 支持全端登出）进 `__Host-app_session` Cookie
  （HttpOnly/Secure/SameSite=lax）；局域网演示可开 AUTH_COOKIE_INSECURE 换无前缀
  Cookie（生产拒绝）；Origin 同源校验中间件防 CSRF。
- **属主**：require_owned_session/run 依赖注入——登录用户跨用户访问一律 404；
  兼容模式（AUTH_ENFORCED=false）允许匿名与无主会话，但登录用户不能认领无主数据。
- **配额**：每账号 3 会话（SESSION_QUOTA_PER_USER），超出 402 → 前端付费墙弹窗
  （升级按钮为占位，支付未接）。

## 9. 数据与演示语料（scripts + migrations）

- 迁移 0001–0007（读模型、运行生命周期、监控、RAPTOR 表、认证、演示语料列、
  OTP 发送失败标志），全部幂等 + 带回滚脚本。
- **W5 语料链**：`transform_jobs_cn_uk.py`（33,246 行源 → 31,879 接受，SHA-256 排序
  精确配额 CN 22,315/UK 9,564，公司/城市/签证确定性映射，薪资只存 source_metadata，
  两次运行字节一致）→ `import_cnuk_demo.py`（500 行窗口断点续跑、embedding 指纹
  锁定，全量 32.2 分钟九项对账全中）→ `cutover_cnuk_demo.py`（活跃 run 拒绝 +
  入队共享锁 ↔ 切换排他锁围栏 + 逐行快照回滚 + 干净部署哨兵行）。
- **标记链**：jobs.demo_synthetic → 检索 SELECT → ranking_scores → 发布门拦缺标 →
  RecommendationResult 字段 → 前端徽章；生产开放 demo 行必须 DEMO_CORPUS_ENABLED=true。

## 10. 记忆与反馈（app/memory）

- `private_memory.py`：用户简历画像私有记忆（咨询首轮可展示"上次确认过的画像"草稿，
  需用户确认才生效）。
- `feedback_loop.py`：投递反馈闭环——reaction 落库（幂等键）→ Supervisor 评估
  是否沉淀 → 去标识化后写匿名案例库（PII 检测拦截）；闭环失败记录错误可重试。
- `case_base.py`：匿名案例的 embedding 检索（隐式空间数据源）。
  已知边界：写入链与隐式读取链是两套表（known_issues #1，有意暂缓）。

## 11. 评估体系（app/evaluation + scripts）

两套口径，论文必须分开写：
- **原口径**：arshkon-1000 语料 + 15 查询人工标注（离线词法基线 + 50 岗种子库）；
- **演示语料口径**：`evaluate_demo_corpus.py`——同 15 查询在真实 31,879 库上
  TREC 池化 + DeepSeek 评审标注，Recall 为池内口径偏乐观、主要看通道相对差。
  指标实现在 `evaluation/metrics.py`（P/R/MRR/NDCG@K，宏平均）。
  **四级消融阶梯**（2026-08-06，852 对判定）：BM25 池内 P@5 0.413 → dense 0.707 →
  混合 0.720 → +RAPTOR 0.800 → +Cross 0.907 → **+两者 0.920（MRR 1.000，
  15 查询首位全中）**——每级增强独立可归因，答辩最硬的一张表。

## 12. 前端（frontend/src）

- `v2/LandingPage.tsx` 登录卡（通道由 capabilities.otp_channels 门控）；
- `v2/AppShell.tsx` 侧栏 + 付费墙弹窗 + 401 全局出口；
- `v2/WorkbenchPage.tsx` 群聊工作台（上传/确认/咨询/确认单/播报/结果一条时间线；
  409 双义消歧、CAS 轮次、确认单作废、URL 携带 run id）；
- 复用件：EvidenceDrawer（证据抽屉）、ReactionForm（反馈）、评估/监控页（答辩模式）；
- `api/generated.ts` 由 OpenAPI 快照生成（不手改），`api:check` 门禁防漂移；
- e2e（Playwright，mock 网络）：全流程之旅、未登录重定向、刷新恢复、付费墙、监控页。

## 13. 测试体系（tests/，515 项）

五类读法：**单元**（模块行为）、**契约**（OpenAPI 快照、DTO extra=forbid、路由
所有权不变量——13 条资源路由每条都必须挂对属主依赖）、**特征**（旧编排执行顺序
逐条锚定，图实现必须复现）、**恢复**（真实 PG 崩溃续跑）、**隐私**（响应序列化后
不得出现简历原文/user_id）。另有真机脚本两支：`global_smoke.py`（32 项全局矩阵）
与 `demo_rehearsal.py`（三 persona 彩排），答辩前各跑一遍。

## 14. 配置速查（.env，全部见 .env.example）

| 组 | 关键键 |
|---|---|
| 数据库 | DATABASE_URL、DB_POOL_MIN/MAX |
| LLM | DEEPSEEK_API_KEY/BASE_URL/MODEL_FAST/PRO、LLM_MAX_CONCURRENCY |
| Embedding | QWEN_API_KEY、QWEN_EMBED_MODEL、EMBED_DIM、EMBED_MAX_CONCURRENCY |
| 精排 | RERANK_ENABLED(默认 false)/MODEL(gte-rerank-v2)/ENDPOINT(启用必填)/TOP_N(20)/TIMEOUT(5s)/MAX_CONCURRENCY(4)/DOC_MAX_CHARS(1500)/QUERY_MAX_CHARS(600) |
| 认证 | APP_ENV、AUTH_ENFORCED、AUTH_SECRET_KEY、OTP_PEPPER、AUTH_COOKIE_INSECURE、EMAIL/SMS_OTP_PROVIDER、SMTP_* |
| 产品 | SESSION_QUOTA_PER_USER、MAX_CONSULT_ROUNDS、DEMO_CORPUS_ENABLED |
| 有界循环 | MAX_CLARIFICATION/RERETRIEVAL/REPAIR_LOOPS（各默认 1） |

## 15. 运行手册

```
.\start.ps1                     # 后端（-m app.serve，SelectorEventLoop）
cd frontend ; npm run dev       # 前端（跨机器演示加 -- --host 并开 AUTH_COOKIE_INSECURE）
.venv\Scripts\python -m pytest tests/ -q                  # 后端全量
cd frontend ; npm run typecheck ; npm test ; npm run build ; npx playwright test
$env:AUTH_ENFORCED="true" ; .venv\Scripts\python -u -m app.serve *> tmp\s.log   # 真机彩排前置
.venv\Scripts\python scripts\global_smoke.py tmp\s.log
.venv\Scripts\python scripts\demo_rehearsal.py tmp\s.log
```

## 16. 边界与不足

见 `docs/limitations_and_future_work.md`（14 条，四维度，每条含取舍理由与展望）——
合成语料声明、LLM 标注口径、短信网关、账号删除、任务队列、支付占位等均在列。
