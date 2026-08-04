# V2 改造计划书（v3 终审稿 · 已合并子 agent 与 Codex 三轮双审意见）

> v1 双审判定均为"修订后执行"。本 v2 已吸收全部阻断项与遗漏项；再经双方确认后按 W0→W5 执行。
> 每个工作流：实现 → 全量测试 + OpenAPI 快照 + 前端四件套（api:check/typecheck/test/build）→ Codex 代码审查与修改循环直至收敛 → 独立 commit + push 双远端。

---

## W0 宪法修订 + 基线（新增，先行）

v1 计划只声明突破"一个月范围"，双审指出与宪法的冲突远不止此。W0 做四件事：

1. **CLAUDE_LANGGRAPH.md 增补"V2 修订案"章节**，逐条声明替代：
   - `/api/v1` 契约冻结 → 改为"每工作流可有意变更一次，随附快照+前端类型再生"
   - 279/314 测试冻结 → 改为"删除仅限旧 API 专属用例，删除项逐一列账"
   - clarification ≤1 → 改为"图外咨询轮次上限 `max_consult_rounds`（默认 8，1–15 钳制）；图内三类恢复计数不变，咨询轮次**不与图内恢复混算**"
   - SharedState 冻结 → 允许 V2 新增字段（transcript/rounds），单一事实来源流程不变
   - "本轮不删旧入口/行为完全一致" → V2 明确废止（旧 API 删除是本计划目标）
   - evidence 边界 → 新增"演示语料条款"：`demo_synthetic=true` 语料的公司/城市/签证为**合成场景事实**（薪资不合成），必须全链路（DB 列→API 投影→UI 水印）标示；真实用户简历的证据边界不变
2. **CLAUDE.md 与 AGENTS.md 同步加"V2 阶段指引"**（AGENTS.md 是 Codex 实际读取的宪法，也载有旧约束——一个月范围/clarification≤1/禁 LangGraph，全部指向修订案替代）；明确"一次一个模块"条款**保留**，由垂直切片满足
3. 修宪的"演示语料条款"合成事实仅限**公司/城市/签证**——薪资明确**不**合成（与 W5 一致，避免给实施者错误授权）
4. 基线固定：当前 314 绿基线报告存档；git tag `v2-baseline`；**数据库备份存仓库外受控目录（含简历与 checkpoint PII，不得入 git/push）**，git 只提交不含内容的 hash/计数 manifest；独立 commit

## W2 删除旧 API（拆两步，修正 v1 清单错误）

**W2a 抽取共享代码（先做，保证无红灯中间态）**
- `_persist_upload` + 上传常量 → 新模块 `app/api/uploads.py`（v1 sessions.py 改引；旧 routes 同步改引）；对应上传安全测试迁到 `tests/test_uploads.py`
- 反馈闭环的幂等/错误记录逻辑抽为可复用函数；v1 reaction 在持久化后调用 `process_feedback_closure_for_session`（**定性为"接线迁移"**：case 仍写 `career_cases`，known_issues #1/#5 依旧暂缓；`ReactionResponse` 响应模型**不变**——闭环结果只进 state/日志，保证 OpenAPI 零漂移）
- `tests/test_api_routes.py` 中反馈闭环语义用例（约 538 行后）迁为 v1 反馈测试

**W2b 删除旧 HTTP 面**
- 删：旧 router 挂载 + 5 个旧 endpoint + `MatchRequest`/`FeedbackRequest` + `_run_resume_task`/`_run_match_task` + 旧响应辅助 + `run_persisted_agentic_match_from_session` + `_load_required_state`
- **保留（v1 清单错误，双审一致指出）**：`plan_retrieval`/`PLANNING_PROMPT`/`_planning_payload`/`_is_vague_goal`（被保留的 `run_agentic_match_from_state` L219 调用、5 个编排测试依赖）——其退役推迟到 W1 完成后单独评估；`_loads_or_empty`（final_verification 共用）；`_persist_stage_state`（harness 与持久化测试共用）
- 删除测试仅限纯旧 endpoint 用例（test_api_routes 旧接口部分、test_api_concurrency 第 1 例、phase_c 的 L199/L249 规划两例暂保留随 plan_retrieval 走）
- 文档同步：README、code_guide、known_issues #2 的旧 API 表述更新

## W3 双 OTP 登录 + 记忆绑定（兼容模式交付）

**安全红线继承声明**：除 OAuth/微信章节外，`docs/auth_technical_design.md` 全部红线**按引用整体继承**，不再人工摘要。本节只列 V2 特有决策：

- **数据模型（显式，不留给实施者临场决定）**：`user_identities.provider CHECK IN ('email','phone')`；通用 `otp_challenges(id, channel CHECK IN ('email','phone'), normalized_target, purpose, code_hash, attempts, expires_at, consumed_at, client_ip, created_at)`，索引 `(channel, normalized_target, created_at DESC)` 与 `(client_ip, created_at DESC)`
- **HTTP 契约（显式，路径带 v1 前缀以纳入既有 OpenAPI 导出）**：`POST /api/v1/auth/otp/request {channel, target}` → 202 统一响应；`POST /api/v1/auth/otp/verify {channel, target, code}` → 登录成功签 Cookie + `MeResponse`；`POST /api/v1/auth/logout` → 清 Cookie；DTO 进 v1/schemas.py 与 OpenAPI（export_openapi.py 只收集 /api/v1/）
- 双通道拆分：`EMAIL_OTP_PROVIDER=console|smtp`、`SMS_OTP_PROVIDER=console|twilio|aliyun`，各自独立启用；限流与服务商预算按 channel **各自独立**的 target/IP/global 命名空间；演示期邮箱走 SMTP、短信可 console
- 规范化：邮箱 lower+trim（唯一键/限流键/HMAC 输入均用规范值）；手机 E.164
- HMAC message = `channel||target||purpose||code`，compare_digest 比对
- OTP 过期清理：**独立无条件** lifespan 周期任务（不搭 checkpoint sweeper 的车）
- **属主校验矩阵全覆盖**：sessions 7 条（含 resume-preview/consult/brief）+ runs 5 条（execute/status/conversation/result/explain）+ reaction，统一 `require_owned_*` helper，非属主一律 404；`/monitoring/*` 定级为答辩/管理员能力（独立开关 `MONITORING_ADMIN_MODE`，默认关）
- 旧 TEXT user_id 历史数据：登录用户猜 ID 不可达（无 user 关联的 session 在鉴权模式下一律 404），保留期策略写入 known_issues
- **W4 依赖的新 API 一并交付**：`GET /me`、`GET/PATCH /me/profile`（记忆画像）、`GET /me/sessions`（会话列表，带分页/稳定排序/最大页 50）
- **兼容模式（带防误部署边界）**：`AUTH_ENFORCED=false` 仅限 development/test——production 环境启动时若为 false **直接拒绝启动**；有合法 Cookie 时**永远**按 Cookie 用户做属主校验（不退回 body user_id）；仅"无 Cookie 且兼容模式开"才接受 legacy user_id；`SessionCreateRequest.user_id` 标记 optional/deprecated，W4 切换后从 OpenAPI 删除；CI 同时覆盖 enforced/compatibility 两种模式
- `MONITORING_ADMIN_MODE` 不是裸布尔：开启后仍需管理员身份判定（用户表加 `is_admin` 位），或明确仅限隔离的本地答辩部署使用
- **路由清单不变量测试**：断言"每条带 session_id/run_id 参数的 v1 路由都套了 ownership helper"（自动扫描路由表，防止 W1 新增路由后人工计数失效）
- 测试基建：登录 fixture（console OTP 取码钩子）+ 跨用户 404 授权矩阵测试；现有测试的 user_id 直传路径在兼容模式下继续工作

## W1 咨询多轮化（新增 API 并行，旧端点适配过渡）

状态机设计同 v1（Phase A 模板引导 → B 定向深挖 → C 发散启发；每轮 LLM 输出 reply/next_question/profile_updates/phase/completeness，确定性白名单合并）。v2 补齐双审全部缺口：

- **波及面如实入账**（实测清单）：`schema.py` CareerState、`_INTENT_CAREER_FIELDS` 持久化白名单（**新字段必须同步加入，否则静默丢失**）、`domain/intent.py` 投影、`v1/schemas.py` DTO、OpenAPI 快照、`generated.ts`/`queries.ts`/MatchBriefPage、`test_intent_consultation.py` 12 例等
- **轮次定义**：一轮 = 一次**成功**的 LLM 回合；失败重试不计数；`consult_rounds_used` 服务端计数
- **并发安全**：POST /consult 带 `expected_round`，服务端 CAS（复用 mutate_state_atomically），冲突 409
- **上下文有界**：单条消息 2000 字符钳制；transcript 构造上下文用"画像摘要 + 最近 N 轮"，总预算复用 context_budget
- **finalize 语义**：只产 Brief **草案**；用户经既有 match-brief 端点确认后才创建 run——`intent_consulted=True` 与 `user_profiles` 写入都发生在**确认时**（未确认的画像不得成为长期记忆）；兼容模式下 `user_profiles` **仅对已认证用户写入**，legacy 无主会话跳过
- **记忆预填充**：下次咨询首轮把 remembered profile 作为**带来源标注的草稿**呈现给用户口头确认，绝不静默升级为硬约束
- **新增 `GET /sessions/{id}/consult`**：返回 transcript + 当前画像 + 轮次（刷新恢复/群聊回放数据源）
- **MatchBrief 键契约声明**：`career_goal/hard_constraints/soft_preferences/avoid_roles/result_count` 与 hash/version 语义不变（群聊 Brief 播报读 approved_plan，特征测试锚定不动）
- **过渡策略**：新 `/consult` 与旧 `/intent-consult` 并存（旧端点内部适配到新引擎的单轮模式），W4 切换后删旧端点——保证本工作流收尾时旧前端仍全绿；过渡端点的旧响应模型**显式投影映射**：`clarification_used = min(consult_rounds_used, 1)`（旧 DTO `le=1` 约束不漂移）
- **新端点属主校验**：`POST /consult`、`POST /consult/finalize`、`GET /consult` 三条全部接入 `require_owned_session`（W3 矩阵的 W1 增量），验收含跨用户 404 用例
- 验收扩展：旧 state 快照反序列化兼容、CAS 并发、GET 回放、finalize 幂等、Brief 投影兼容、OpenAPI+类型再生、现前端测试仍绿

## W4 前端重构（垂直切片迁移，不产生不可构建提交）

形态同 v1（claude.com 风格落地页+登录、群聊工作台为唯一中心、评估/监控入设置菜单）。实施方式修正：

- **不做"一删一建"两 commit**：新工作台以新路由/feature flag 并行开发，按登录→会话列表→群聊（上传/咨询/Brief/运行/结果/反馈）逐垂直切片迁移，全部就绪后一次切换（此时打开 `AUTH_ENFORCED`），最后一个 commit 删除旧实现
- **群聊时间线合流契约**（结构性边界，非内容去重）：前端按"consult transcript（GET /consult，按 round 排序）→ run conversation（既有端点，按 seq）"拼接；**Brief 不单独插卡**——run conversation 中既有的 `kind=brief` 消息由前端渲染为富确认卡片（避免 conversation_projector 已生成的 Brief 播报与手插卡片重复展示）；两段各自稳定排序键，不交叉
- 数据源依赖：W3 的 /me、/me/sessions、/me/profile
- e2e 决策（写死）：Playwright **沿用网络 mock 模式**覆盖全流程（含 OTP 登录 mock）；另加 1 条可选真后端冒烟（console OTP 取码钩子）不阻塞 CI
- 验收补充：api:check、credentials include、401 统一跳登录、刷新恢复（会话/咨询/运行三态）、证据抽屉可访问性、监控页权限
- **不与 W5 的语料切换同时进行**

## W5 三万岗位 CN70/UK30（重写为既有迁移设计的"差异补丁"）

**与既有设计（docs/superpowers/specs/2026-07-27）的差异声明**：
1. **新数据集标识 `linkedin_ml_cnuk_demo_v1`**：不复用 31879_v1 的门禁数字与 manifest。**行数策略（消除内部矛盾）**：保留全部 31,879 条唯一源记录，**不**按变换后的展示字段二次删行（变换只改展示字段，源唯一性不变，固定配额得以成立）；变换后的公司/标题/城市碰撞只生成**碰撞报告**入 manifest 供核查，不删除数据。chunk 数因加背景头会变化：**120,248/12,025 仅为原始迁移设计基线参考**，最终门禁一律以 post-transform manifest 的 `N_jobs/N_chunks/ceil(N_chunks/10)` 为准
2. **证据边界的演示语料条款（W0 已修宪）**：
   - 公司/城市按策展池替换（用户明确决策：映射到真实公司名，仅本地演示不发布不上线）；`demo_synthetic=true` 为 `jobs` 表实列，API 投影带出，UI 所有岗位卡/证据卡持续显示"合成演示岗位"水印
   - **签证为合成场景字段**：源 CSV 无签证列（`is_sponsored` 是推广帖含义，不得误用）。方案：`visa_sponsor` 按国家场景规则合成（CN 岗约 5% true、UK 岗约 35% true，确定性哈希分配），列注释与文档明确"合成场景值"；演示叙事依赖签证硬过滤，此为有意取舍
   - 薪资：源值三列+计薪周期原样存 `source_metadata`；**不生成** CNY/GBP 事实区间（缺币种，不编造）；结果卡不展示薪资
3. **确定性与精确比例**：国别分配用 `SHA-256(source_record_hash)` 排序后精确切分 **22,315 CN / 9,564 UK**（不用 job_id——它含公司/城市，存在循环依赖；不用 Python str hash——跨进程随机化）；验收核对完整 manifest 计数而非抽样
4. **管线如实定位**：既有设计的 staging/window/lease 等仅是设计，无现成代码。W5 实现其**最小可用子集**：验证归档+SHA-256 manifest → 100 条隔离 trial → 3,000 条内部 preview（staging 表，不对外）→ 全量分窗可续跑导入 → 计数对账 → **严格离线 cutover**（进入 maintenance：拒绝新 execute、排空/转移全部 QUEUED/RUNNING run、停 worker → 事务切换 corpus 指针 → 重启验证；替代 corpus_epoch/写者围栏的复杂方案，防止切换前启动的 run 写旧 job ID）→ 回退演练（同 maintenance 流程切回旧 1000 语料）。**embedding 指纹在批次创建时冻结**（model/dimension/splitter/build fingerprint 四元组入 manifest），续跑必须完全匹配，运行时查询 embedding 同指纹
5. **embedding 基线参考**：120,248 chunks / 约 12,025 次批请求（批 10）为原设计基线；实际数量与预算门禁一律以 post-transform manifest 为准；先用 100/3000 pilot 实测延迟与 token 再外推总时长；`_embed_specs` 现为串行循环——实现**有界 worker 池 + 超时重试**；语料与查询 embedding **模型指纹统一**（与当前运行时同模型同维度，cutover 时一致性校验）
6. **合成标记的确定性数据通路**：`demo_synthetic` 与新增 `country_code` 从 DB 列 → 检索候选 → ProductResult **确定性透传**（不依赖 LLM 复制）；publication gate 增加校验"属于 demo 语料但缺 demo 标记的结果拒绝发布"；`visa_sponsor` 的 provenance 标注 `synthetic_scenario`；**production 环境默认禁止激活 demo 语料**（需显式 `DEMO_CORPUS_ENABLED`）；源 CSV/变换产物/归档/DB 备份一律不入 git
7. **评估叙事保全**（最重风险）：新语料无标注，Recall/MRR/NDCG 不可算。策略（降级为存档口径）：旧 1000 行语料的评估工件在 cutover 前跑一次完整存档，**仅供论文与验收归档，不接入评估页**（现 EvaluationRunPage 只展示单 run explain，不为历史报告新建 API/UI）；新语料标注列为后续工作

## 执行顺序（v2，采纳 Codex 重排）

**W0 修宪+基线 → W2a 抽取 → W2b 删除 → W3 登录（兼容模式）→ W1 咨询（并行新 API）→ W4 前端（垂直切片，切换时开鉴权、删旧适配）→ W5 数据（trial→preview→全量→cutover，不与 W4 切换并行）**

回退设计：每工作流 push 双远端 + W0 的 git tag；W3/W5 各自有 DB 迁移回退脚本；W5 有 corpus 指针切回演练；W4 切换前旧前端始终可用。

## 风险清单（v2 增补）
- 咨询多轮化 LLM 成本：每轮 1 调用，15 轮封顶；上下文预算钳制
- W5 总时长以 pilot 实测为准，"数小时"仅为风险区间；DashScope RPM/TPM 双限流约束并发
- OpenAPI 连续**三次**有意变更（W3 鉴权、W1 咨询、W5 结果投影加 demo_synthetic）：每工作流固定"快照+类型再生"步骤，W5 验收含快照再生
- 真实公司名映射到合成 JD 的声誉风险：本地演示、不发布、全链路水印（用户明确决策）
