# Career-RAG 功能与代码详解

> Supervisor-guided Dual-space Agentic RAG for Career Matching

# 第一部分：系统功能与设计

## 1. 项目定位与答辩主张

Career-RAG 是一个 Supervisor 监督的双空间 Agentic RAG 职业匹配系统。**Agentic RAG** 的白话解释是：先从岗位数据库找出可核对的证据，再让分工明确的 AI 角色基于这些证据完成咨询、匹配和规划；它不是让一个聊天模型从头猜到尾。

系统面向多人使用：每位用户先认证，再在自己的会话中上传简历、完成咨询、批准 Match Brief，最后查看岗位、证据、差距和路径。服务进程不保存用户业务状态；所有 SharedState、run、事件和 checkpoint 都按 ID 写入 PostgreSQL。

答辩时应把贡献收敛为四点：

1. 硬约束和生成式推理分工明确：SQL 负责不可违反条件，模型负责软性理解与表达。
2. 简历原文 `R###` 与澄清原话 `C###` 构成可追溯证据链，策略建议不能脱离事实。
3. 三个业务 Agent 之外，Supervisor 同时覆盖正式运行与咨询期 PM 督导，并且所有恢复都有上限。
4. RAPTOR 与 Cross-Encoder 是两个独立开关，四组合有回归和真机验收，评估产物版本化保存。

本文只描述已经存在于冻结代码或版本化实测工件中的能力。离线指标不解释为个人求职成功率；外部模型质量、网络和上游岗位数据仍会影响结果。

## 2. 用户、角色与职责边界

群聊工作台展示四个角色：

| 角色 | 用户看到的职责 | 代码中的职责 |
|---|---|---|
| 需求顾问·小意 | 问清目标、地点、签证和含糊经历 | 咨询引擎 + Intent Agent |
| 岗位顾问·小检 | 找岗位并解释为什么推荐 | Retrieval + Matching Agent |
| 规划师·小策 | 说明差距、简历修改和职业路径 | Strategy Agent |
| 项目经理·PM | 监督咨询质量、确认里程碑、终审核查 | Consult Coach + Supervisor/Harness |

三个业务 Agent 是三类不同 system prompt 的模型调用，它们共享一份结构化状态，不是三个微服务。PM 也不是一个无上限自由循环的“总控模型”：咨询期先做确定性 L1 判断；正式运行由确定性检查和有界模型核查共同组成。

**确定性检查** 指相同输入一定得到相同判断的 SQL 或 Python 规则，例如版本相等、证据 ID 存在、岗位是否在允许集合。模型只处理规则难以覆盖的语义任务。

## 3. 端到端业务流程

```text
认证与额度
  → 创建 session
  → 上传简历（API 立即返回 202）
  → 后台解析、归一化、建立 R### 证据
  → 预览并确认 resume_version
  → 咨询：三项必需信息 → 可选 resume_clarify → deepen
  → PM note（可选、有预算、fail-open）
  → finalize → Match Brief 双栏确认
  → plan_version + plan_hash 锁定
  → LangGraph 七节点执行
  → SQL 硬过滤 → BM25 ∥ Dense ∥ RAPTOR → RRF → Cross-Encoder
  → 三层岗位 + JD/简历证据 + 差距 + 修改计划 + 路径
  → 用户反馈 → 私有记录 / 满足条件后匿名案例
```

长任务采用“提交—轮询”而不是让 HTTP 请求一直等待。用户批准确认单后，前端创建并触发 run，再轮询状态和群聊播报。run 的状态、计划、事件和结果都持久化，因此浏览器刷新后可以重新读取。

## 4. Shared Structured State

`app/state/schema.py:68` 的 `SharedState` 是单一事实来源。新增字段必须先进入这里，避免 Agent 之间靠隐含约定传字符串。

```text
SharedState
├─ session_id / user_id
├─ resume_state
│  ├─ education / experience / projects / skills
│  ├─ resume_quality_issues
│  ├─ original_evidence_spans        R###
│  ├─ clarification_targets          待处理目标
│  ├─ pending_clarification          当前问题锚点
│  ├─ clarifications                 回答/跳过记录
│  └─ clarification_evidence_spans   C###
├─ career_state
│  ├─ goal / hard_constraints / soft_preferences / avoid_roles
│  └─ consult_transcript / consult_rounds
├─ retrieval_state
├─ strategy_state
├─ feedback_state
├─ coach_reservations
└─ supervisor_log
```

`app/state/resume_view.py:11` 的 `effective_resume_text` 和 `:38` 的 `all_resume_evidence_spans` 是新增证据的统一消费视图。澄清开关关闭时，旧简历文本和证据行为保持不变；开启时，只把已经完成验证的 `C###` 证据加入本人匹配与策略链。

## 5. 群聊工作台的真实页面结构

产品不是多页向导，而是一条群聊时间线。实际顺序是：

1. `frontend/src/v2/LandingPage.tsx:16`：登录/注册卡；验证码通道由能力接口控制。
2. `frontend/src/app/router.tsx:11`：无会话空态，用三步说明引导新建咨询。
3. `frontend/src/v2/WorkbenchPage.tsx:818`：职业规划服务群主时间线。
4. `frontend/src/v2/ResumeProfileAccordion.tsx:12`：归一化档案手风琴与重传入口。
5. `frontend/src/v2/consultSlots.ts:10`：目标、地点、签证三个 chip；需要澄清时追加第四个进度 chip。
6. `frontend/src/v2/WorkbenchPage.tsx:945`：用户、小意和 PM note 气泡。
7. `frontend/src/v2/WorkbenchPage.tsx:238`：Match Brief，显示“硬条件（SQL 锁定）”和“检索方向 / 排序参考”。
8. `frontend/src/v2/WorkbenchPage.tsx:139`：服务进度卡；`:1004` 开始展示运行阶段播报。
9. `frontend/src/v2/WorkbenchPage.tsx:310`：结果三分层、证据、策略与后续动作。
10. `frontend/src/features/feedback/ReactionForm.tsx:18`：岗位反馈。
11. `frontend/src/v2/AppShell.tsx:134`：移动端导航抽屉。

工作台只展示公开投影。完整 SharedState、模型提示词、供应商错误、用户原始简历全文和内部 CAS 信息不作为页面内容。

## 6. 认证、配额与多人隔离

认证入口位于 `app/api/auth/routes.py:75`、`:119`、`:148`、`:155`，分别负责请求 OTP、核验、退出和查询当前账号。**OTP** 是一次性验证码；可用邮箱或短信通道由配置和 `/capabilities` 一起决定。

认证会话使用 HttpOnly Cookie。账号、会话和 run 在数据库中建立所有权关系；前端请求携带 Cookie，后端依赖负责拒绝跨用户读取。每账号会话额度由 `SESSION_QUOTA_PER_USER` 控制，超出返回 402，前端显示额度弹窗。支付只是占位提示，当前没有支付闭环。

`app/db/pool.py:18` 复用 `asyncpg` 连接池。业务状态不进模块级可变字典；`app/db/state_store.py:327` 用行锁下的原子 mutation 处理咨询和简历并发更新。这是多人同时使用时不互相覆盖的基础。

## 7. generation 生命周期：202 窗口、重确认洞与 409 契约

### 7.1 两个编号解决两个问题

- **resume_generation**：第几次上传尝试。每次接受上传立即加一，不要求归一化成功。
- **resume_version**：第几份成功归一化并写入的简历。只有当前 generation 成功时才增加。

区分两者后，旧后台任务即使晚到，也不能覆盖较新的上传。

### 7.2 两步确认制与 202 窗口（v3 B2）

上传现在分两步（防烧钱确认制）：

1. **上传（200）**：`POST /resume` 存库（`resume_uploads` BYTEA）+ 本地
   提取，状态置 `resume_uploaded`，**零 LLM 成本**；返回页数/字数/预览与
   本会话解析额度（`RESUME_PARSE_LIMIT`，默认 3 次）。
2. **确认解析（202）**：`POST /resume/parse` 带 `{generation}`，单事务
   FOR UPDATE 分类后扣一次额度、置 queued，并把字节读进内存交给后台任务。

**202** 的白话解释是”服务器已经接单，但工作还没做完”。从 202 返回到后台
保存结果之间就是”202 窗口”：预览接口以稳定 detail=`resume_processing`
返回 409，前端每 2.5 秒轮询。等待确认解析期间则是 `resume_unparsed`，
由「确认解析」卡驱动，不轮询。

后台任务 `_normalize_resume` 携带 `expected_generation`；成功保存
`save_normalized_resume` 与失败保存 `mark_resume_error` 都先锁行核对
generation **和** `status='resume_queued'` 双前置；不满足说明自己已过期，
直接丢弃写回。LLM 外呼发起前失败会自动返还解析额度。

### 7.3 重确认洞如何被堵住

“重确认洞”指用户上传新简历后，旧版仍短暂被当作已确认，导致咨询或确认单继续使用旧事实。当前实现从三个位置封闭它：

1. 接受新上传的事务立刻把旧确认置空。
2. `app/db/state_store.py:292` `confirm_resume` 在行锁内同时核对 ready 状态和期望 resume_version。
3. 咨询、finalize 和 Match Brief 路由再次核对简历版本；冲突时不提交本轮。

### 7.4 稳定 409 契约与三态恢复

**409** 表示请求依据的资源状态已经过期。预览接口使用 `resume_missing`、
`resume_unparsed`（B2：已上传待确认解析）、`resume_processing`、
`resume_error`；动作接口还会使用 `resume_changed` 与
`resume_parse_limit`（B2：解析额度用尽）。前端统一清空过期 Brief，并同时
失效 preview 与 consult 查询。

| 恢复态 | 固定文案 | 行为 |
|---|---|---|
| unparsed | （确认解析卡） | 展示预览与额度，等待用户确认解析。 |
| processing | 新简历处理中 | 保持轮询，不提交旧轮次。 |
| error | 这份文件我没能整理成功，旧档案已作废 | 停止轮询，引导用 📎 重传。 |
| parse_limit | 本会话解析次数已用完（3/3） | 新建会话继续或联系管理员重置。 |
| updated | 简历已更新，本轮未提交；请确认新档案后重试 | 新预览 ready 后要求重新确认。 |

三段文案定义在 `frontend/src/v2/WorkbenchPage.tsx:38`。这是一份前后端恢复合同，不是普通 toast。

## 8. 简历澄清回路：从质量信号到 C### 证据

### 8.1 触发来源

`app/normalization/resume_intake.py:281` `build_clarification_targets` 用确定性顺序建立目标：先处理高/中优先级质量问题，再看过短经历是否缺职责或成果，最后看项目是否缺技能。`RESUME_CLARIFY_MAX` 限制目标数；功能门位于同文件 `:612`。

咨询阶段 `app/agents/consult_engine.py:174` `determine_phase` 先保证目标、地点、签证三个模板槽位完成；若开关开启、存在 open target 且仍有轮次预算，进入 `resume_clarify`。没有目标时不会为了展示功能凭空提问。

### 8.2 pending 锚点

每次只追问一个目标。`app/agents/consult_engine.py:292` `run_consult_round` 在轮次开始读取 `pending_clarification`；新提问时一起保存：

```json
{
  "target_ref": "experience[0].achievements",
  "asked_round": 4,
  "baseline_version": 1
}
```

`target_ref` 说明在补哪一个字段，`asked_round` 防止错轮消费，`baseline_version` 防止跨简历版本消费。版本核验位于 `app/api/v1/sessions.py:759` `_pending_baseline_matches_version`。

### 8.3 C### 证据与消费闭环

`app/api/v1/sessions.py:816` `_record_clarification_turn` 负责闭环：

```text
open target
  → 问题与 pending 一起持久化
  → 用户实质回答：target=answered，保存 C###，清 pending
  → 用户明确跳过：target=skipped，清 pending
  → 选择下一个 open target，或进入 deepen/finalize
```

编号由 `app/api/v1/sessions.py:893` `_next_clarification_span_id` 生成。有效回答保存为 `source=user_clarification`，`span.text` 与用户原话逐字相等。`app/agents/consult_engine.py:586` 的 `validated_answer_summary` 只允许从原话抽取 token，不能悄悄加入新的事实。

统一消费链是：

- `app/state/resume_view.py:11` 把 `C###` 加入有效简历文本；
- `app/retrieval/query_builder.py:40` 让显式检索读取该文本；
- Strategy Agent 基于 `all_resume_evidence_spans` 过滤无证据建议；
- Supervisor 用 evidence IDs 核查发布；
- 对外结果只投影实际被引用的允许字段。

批次 9 P4 真机路径记录了 `C001` 原话证据，并在公开 run result 中出现该 evidence 引用。该结论来源为 `docs/validation/2026-08-07-batch9-acceptance.md`。

### 8.4 隐私边界

`app/retrieval/implicit_search.py:43` `build_implicit_query_text` 只读取结构化教育、经历、项目和技能，不读取 `clarification_evidence_spans` 或 pending 原话。因此，澄清内容可以服务当前用户的显式匹配和策略，但不会被直接拼进匿名案例检索查询。

“不直接拼入查询”不等于承诺任何系统绝对无风险；公开接口仍通过投影、所有权检查和隐私回归共同防护。

## 9. PM 咨询督导：L1、L2、reservation 与 fail-open

正式匹配前的咨询原本主要由需求顾问推进。PM 咨询督导补上这段监督空白，但不让模型每轮任意插话。

### 9.1 L1：零模型成本的状态判断

`app/agents/consult_coach.py:62` `evaluate_consult_l1` 读取已持久化事实：当前阶段、三项槽位、完整度变化、连续停滞、是否可 finalize、澄清是否结束、剩余预算。**L1** 就是“只用代码规则做第一层筛选”。

`app/agents/consult_coach.py:118` `select_coach_trigger` 从三类触发中选一个：

- `finalizable`：条件已齐，提醒进入确认单；
- `stagnation`：连续轮次没有有效增量，建议换一种问法；
- `deepen_entry`：刚进入深挖，确认下一步方向。

优先级、同类一次、每轮一次和总预算都由确定性状态约束。澄清阶段会暂停停滞 streak，避免用户认真补简历时被误判为“对话没进展”。

### 9.2 reservation：先占预算再调用

两个并发请求可能同时判断“应该叫 PM”。若都先调用模型再扣次数，就会双花预算。`app/agents/consult_coach.py:155` `reserve_coach_attempt` 先生成 attempt ID 并写 `reserved` 记录；`app/api/v1/sessions.py:537` 的第一次 CAS 同时提交用户轮次和 reservation。只有预约成功的一方能进入 L2。

**CAS** 是 compare-and-swap，白话说就是“数据库仍是我刚才读到的版本时才允许写”。它让并发轮次不会重复消费 pending 或 PM 预算。

### 9.3 L2 与 fail-open

`app/agents/consult_coach.py:331` `run_consult_coach` 执行受超时保护的模型调用。**L2** 是“基于 L1 给定原因，把真实状态组织成一条用户可读的 PM note”。`app/agents/consult_coach.py:247` `finalize_coach_reservation` 把 reservation 单调变成成功或错误终态，并写 `supervisor_log`。

用户轮次先提交，L2 后调用。超时、服务错误或解析失败时，第二次 CAS 只记录错误，不回滚用户输入和小意回复。这是 **fail-open**：辅助监督不可用时主咨询仍可继续。它不表示错误被隐藏；错误留在监督日志中供审计。

前端把成功 note 投影成 PM 气泡，见 `frontend/src/v2/WorkbenchPage.tsx:761`。`finalizable` note 下方直接出现整理确认单按钮；若没有该 note 但状态已可 finalize，页面仍有确定性兜底卡片，见同文件 `:970`。

批次 9 P4 记录了 `stagnation`、`finalizable`、`deepen_entry` 三类各一次，并在配置预算内耗尽 3/3。该数字只用于描述这条已执行的演示路径，不代表每个用户都会收到三条 PM note。

## 10. Match Brief：SQL 锁定与方向双栏

Match Brief 是运行前必须经用户确认的不可变计划。`app/agents/orchestrator.py:428` `_lock_approved_brief` 计算计划内容、`plan_version` 与 `plan_hash`，并把检索开关快照进本次 run。

| 栏位 | 数据去向 | 例子 |
|---|---|---|
| 硬条件（SQL 锁定） | metadata WHERE/允许集合 | 地点、签证、学历、经验、岗位开放状态 |
| 检索方向 / 排序参考 | 查询构造、软偏好加权、avoid_roles | 目标岗位、行业倾向、希望避开的方向 |

用户确认时看到的公开投影由 `app/agents/orchestrator.py:507` 生成。执行请求必须携带匹配的 version 和 hash，防止前端确认 A、后台执行 B。简历 generation/version 变化会使旧 Brief 失效。

## 11. 三 Agent、Supervisor 与有界循环

| 模块 | 核心职责 | 主要文件 |
|---|---|---|
| Intent Agent | 根据已确认咨询状态整理当前与长期目标 | `app/agents/intent_agent.py` |
| Matching Agent | 调检索、过滤 avoid roles、生成 Top 岗位解释并三分层 | `app/agents/matching_agent.py` |
| Strategy Agent | 技能差距、简历修改计划、职业路径；无简历证据建议被删除 | `app/agents/strategy_agent.py` |
| Supervisor | 规划/终审语义判断，加确定性 ID、数量、证据与约束核查 | `app/agents/supervisor.py` |
| Harness | Agent 前后及发布门的纯代码合同检查 | `app/agents/supervisor_harness.py` |

clarification、re-retrieval 和 repair 都有最大次数，没有开放式 `while True`。模型说“岗位符合硬条件”不能代替 SQL；模型说“建议有依据”也不能代替 evidence ID 核查。

## 12. 混合检索、双空间与证据链

**混合检索** 是把关键词和语义两种找法合并：BM25 擅长明确词汇，Dense embedding 擅长语义相近表达。`app/retrieval/hybrid_search.py:867` 是主入口：

1. `:918` 先用 SQL/metadata 得到 `allow_ids`。
2. RAPTOR 开启时，`:924` 并行 BM25、Dense、RAPTOR；关闭时 `:945` 并行前两路。
3. `:950` 把文本块命中折叠为岗位级排名；`:956` 用 RRF 融合。
4. `:984` 做 bi-encoder、字段和软偏好打分。
5. `:1005` 可选 Cross-Encoder 精排；运行时失败由 `:1042` 回落到关闭 cross 的同参数路径。

**RRF** 是 Reciprocal Rank Fusion，白话说就是“看各路名次而不是硬拼不同尺度的分数，多路都靠前的岗位得到更高融合分”。

**双空间** 包含显式岗位空间和隐式匿名案例空间。`app/retrieval/dual_space_search.py:27` 在 `:51` 并行两路；隐式空间只能对显式允许岗位有限调序，不能引入 SQL 已过滤的岗位。隐式失败从 `:108` 起退回显式结果。

JD evidence IDs 随排名进入 Matching Agent；简历 evidence IDs 随有效简历视图进入 Strategy Agent。发布投影会剔除缺岗位 ID、缺 JD 证据或引用无效简历证据的内容。

## 13. RAPTOR 与 Cross-Encoder：双开关语义和四组合等价

**RAPTOR** 在本项目中是离线建立的岗位层级摘要检索：先召回摘要节点，再把命中传播回原始岗位块。建树入口为 `app/retrieval/raptor.py:300`，在线搜索为 `:352`，且始终受 `allow_ids` 约束。

**Cross-Encoder** 是把查询和某个候选文本放在同一个模型输入中评分的精排器，比单独计算向量相似度更细，但需要额外外部调用。客户端与 Semaphore 限流在 `app/llm/reranker.py:24`，主调用在 `:99`。

两个功能独立配置：`app/config.py:61` `RAPTOR_ENABLED`，`:62` `RERANK_ENABLED`。每次批准 Brief 时，`app/agents/orchestrator.py:443-444` 把值写进 retrieval plan，避免运行中途环境变化偷换路径。

| RAPTOR | Cross | 路径语义 |
|---|---|---|
| 关 | 关 | BM25 + Dense → RRF → 确定性重排 |
| 开 | 关 | BM25 + Dense + RAPTOR → RRF → 确定性重排 |
| 关 | 开 | 两路 RRF → 确定性重排 → Cross-Encoder |
| 开 | 开 | 三路 RRF → 确定性重排 → Cross-Encoder |

“四组合等价”是运行时回滚语义：某开关关闭后，未启用功能不会改变对应基线的状态合同和公开结果结构；它不是说四种组合的岗位顺序相同。批次 9 后端回归包含四组合矩阵，关闭态真机 P1–P3 为 3/3，通过开启态 P1–P4 为 4/4。来源：`docs/validation/2026-08-07-batch9-acceptance.md`。

`.env.example` 为安全起步把两个增强都设为 false；批次 9 验收配置快照中二者都为 true。澄清与 PM 也是独立开关：`app/config.py:88` 和 `:90`。当前 `.env.example` 已列 PM 键，但没有列澄清键；复现开启态时需在本地 `.env` 明确加入 `RESUME_CLARIFY_ENABLED=true` 与 `RESUME_CLARIFY_MAX=2`，不改代码默认值。

## 14. LangGraph、checkpoint 与恢复边界

**checkpoint** 是“每个图节点完成后，把流水线托盘存进数据库”。`app/graph/build.py:20` `build_graph` 连接七个节点：intent、lock_brief、retrieve_match、strategy、verify、prepare_reretrieval、publish；verify 后只有受上限约束的恢复分支。

`app/graph/runner.py:25` `run_graph_match` 负责 checkpoint 读取、执行、结果幂等保存和终态隐私清理。同一 run 再次触发时，如果 checkpoint 可用，可以从记录位置继续；已经保存的结果不会重复写。

能力边界：服务重启时可以回收超时旧 run，runner 也能在再次触发时续跑，但当前没有外部队列自动重新派发所有中断 run。答辩时应说“持久化断点 + 再触发续跑”，不说“任意故障后全自动恢复”。

## 15. 反馈、画像记忆与匿名案例

用户确认过的职业画像写入 `user_profiles`，新咨询可以把它作为待确认草稿，不会无条件覆盖当前目标。岗位 reaction 先以幂等键落反馈，再由 `app/memory/feedback_loop.py` 判断是否满足沉淀规则；通过 PII 检测和去标识化后才写匿名案例。

**PII** 是可以识别个人的信息，例如邮箱、电话和个人链接。匿名案例检索位于 `app/memory/case_base.py`，只为隐式空间提供有限调序信号。现有已知边界仍成立：反馈写入链和隐式读取链使用的表尚未完全统一，详见 `docs/limitations_and_future_work.md`；不能把它描述为已经验证的长期在线学习效果。

## 16. 评估管线与可引用数字

排名指标实现于 `app/evaluation/metrics.py:12` `evaluate_rankings`；硬过滤核验在 `:141`，证据忠实度在 `:169`。演示语料评估入口为 `scripts/evaluate_demo_corpus.py:136`。

版本化口径：`data/eval/demo_corpus_cross_v1/`，语料 `linkedin_ml_cnuk_demo_v1`，31,879 个岗位、15 条查询、852 个池化判定对。标签为 LLM 评审且未经人工复核；Recall 是池内口径，主要用于同一轮通道比较。

| run | P@5 | R@10 | MRR | NDCG@5 |
|---|---:|---:|---:|---:|
| BM25 within pool | 0.413 | 0.149 | 0.680 | 0.458 |
| Dense within pool | 0.707 | 0.244 | 0.900 | 0.726 |
| base 混合主线 | 0.720 | 0.262 | 0.822 | 0.720 |
| RAPTOR | 0.800 | 0.284 | 0.967 | 0.839 |
| Cross-Encoder | 0.907 | 0.310 | 0.900 | 0.897 |
| RAPTOR + Cross-Encoder | 0.920 | 0.323 | 1.000 | 0.939 |

这些数字只来自 `data/eval/demo_corpus_cross_v1/manifest.json`、同目录 rankings/labels，以及 `docs/validation/2026-08-06-cross-encoder-ablation.md`。不同池化轮次不能直接横比；MRR `1.000` 只表示这 15 条查询在该池化评审下首位均相关，不表示真实用户一定满意。

## 17. 批次 9 验收与测试计数

冻结验收唯一计数来源：`docs/validation/2026-08-07-batch9-acceptance.md`。

| 门禁 | 实测结果 |
|---|---|
| 后端 pytest | 642 passed |
| Vitest | 105/105 |
| Playwright | 14/14 |
| 全局冒烟 | 32 passed, 0 failed |
| pyflakes app scripts | 0 |
| 前端 typecheck / build | 0 / 成功 |
| OpenAPI export → generate → check | 0，冻结报告记录为加性 diff |

同一报告记录：关闭两项新咨询功能时 P1–P3 为 3/3，P4 跳过；开启后 P1–P4 为 4/4。配置快照同时开启 RAPTOR 与 rerank，并完成 P4 的澄清、PM 督导、finalize、Brief、run 与公开 `C001` 证据闭环。

报告内验收 SHA 是 `4cd5b287...`，报告和 rehearsal 修正随后入库；本源稿对齐用户指定的当前冻结 HEAD `2474e48`。两者角色不同：前者定位那次全量复跑，后者定位本文档实际读取的仓库状态。

## 18. 安全、隐私与能力边界

- 硬过滤由参数化 SQL/metadata 执行，模型不能覆盖允许集合。
- `R###` 和 `C###` evidence IDs 是建议发布门的一部分；无证据内容会被拒绝或删除。
- 所有 LLM、embedding、rerank 外部调用经过 asyncio Semaphore；不用线程或多进程扩展 I/O。
- 公开结果、群聊和监控都经过 allow-list 投影，不直接序列化 SharedState。
- 澄清原话不直接进入隐式匿名案例查询。
- Cross-Encoder 运行时失败可回落，但缺 endpoint 等配置错误会显式失败，避免“显示已开、实际没跑”。
- PM coach 失败保住咨询主线，但错误会进入 supervisor log，不把失败伪装成成功 note。
- 系统给出职业决策辅助，不承诺面试或录用；演示语料标签未经人工复核。

# 第二部分：代码实现与复现

## 19. 后端目录与调用关系

```text
app/api/main.py
  └─ app/api/v1/router.py
      ├─ auth/routes.py
      ├─ v1/sessions.py
      │   ├─ normalization/resume_intake.py
      │   ├─ agents/consult_engine.py
      │   ├─ agents/consult_coach.py
      │   └─ db/state_store.py
      └─ v1/runs.py
          └─ graph/runner.py
              └─ graph/build.py + graph/nodes.py
                  ├─ agents/intent_agent.py
                  ├─ agents/matching_agent.py
                  │   └─ retrieval/dual_space_search.py
                  │       └─ retrieval/hybrid_search.py
                  ├─ agents/strategy_agent.py
                  └─ agents/supervisor.py
```

配置集中在 `app/config.py`；数据合同集中在 `app/state/schema.py` 和 `app/domain/`；外部模型客户端集中在 `app/llm/`。这三类文件是代码走读的“入口地图”。

## 20. 模块—文件—关键函数索引

| 模块 | 文件:行 | 关键函数/对象 | 为什么看它 |
|---|---|---|---|
| 配置 | `app/config.py:59` | `Settings` 检索/新特性字段 | 两个检索开关、两个咨询开关和预算均从环境读取。 |
| 状态合同 | `app/state/schema.py:12` | `ResumeState` | R###、target、pending、C### 都在一个模型中。 |
| 上传受理 | `app/db/state_store.py:207` | `accept_resume_upload` | generation 增加和旧确认作废是同一事务。 |
| 成功写回 | `app/db/state_store.py:229` | `save_normalized_resume` | generation guard + resume_version 增加。 |
| 档案确认 | `app/db/state_store.py:292` | `confirm_resume` | 行锁内检查 ready/version。 |
| 归一化 | `app/normalization/resume_intake.py:642` | `intake_resume` | Stage 0 总入口。 |
| R### 证据 | `app/normalization/resume_intake.py:191` | `build_evidence_spans` | 模型调用前先切本地原文证据。 |
| 澄清目标 | `app/normalization/resume_intake.py:281` | `build_clarification_targets` | 质量信号到确定性追问目标。 |
| 咨询轮次 | `app/agents/consult_engine.py:292` | `run_consult_round` | phase、pending、动作和对话更新。 |
| 澄清消费 | `app/api/v1/sessions.py:816` | `_record_clarification_turn` | answered/skipped 与 C### 写回闭环。 |
| PM L1 | `app/agents/consult_coach.py:62` | `evaluate_consult_l1` | 不调模型的事实判断。 |
| PM 触发 | `app/agents/consult_coach.py:118` | `select_coach_trigger` | 优先级、去重和预算。 |
| PM L2 | `app/agents/consult_coach.py:331` | `run_consult_coach` | 超时保护与 note 输出。 |
| Brief 锁定 | `app/agents/orchestrator.py:428` | `_lock_approved_brief` | 版本、哈希、开关快照。 |
| 混合检索 | `app/retrieval/hybrid_search.py:867` | `hybrid_search` | 硬过滤、并行检索、RRF、两段重排。 |
| RAPTOR | `app/retrieval/raptor.py:300` | `build_raptor_index` | 离线摘要树。 |
| 双空间 | `app/retrieval/dual_space_search.py:27` | `dual_space_search` | 两空间并行与隐式失败回退。 |
| 图编排 | `app/graph/build.py:20` | `build_graph` | 七节点和唯一有界恢复分支。 |
| 图执行 | `app/graph/runner.py:25` | `run_graph_match` | checkpoint、幂等收尾与清理。 |
| 评估 | `app/evaluation/metrics.py:12` | `evaluate_rankings` | 四类排名指标的统一入口。 |

## 21. 前端数据流与竞态恢复

前端使用 React、TypeScript、TanStack Query 和 Vite。`frontend/src/api/client.ts:76` 统一处理带 Cookie 的请求；`frontend/src/api/queries.ts:44` 提供类型化 API 方法；`frontend/src/api/generated.ts` 来自 OpenAPI 快照，禁止手改。

工作台 `frontend/src/v2/WorkbenchPage.tsx:490` 同时维护三类服务端数据：resume preview、consult state、run status/conversation。mutation 成功后通过 query key 失效重取，而不是在多个组件复制服务器真相。

简历冲突路径：

```text
动作返回 409
  → resumeRecoveryState 解析稳定 detail
  → 清 briefDraft
  → invalidate resume-preview + consult
  → processing：继续轮询
  → error：停止并显示重传
  → ready：转 updated，要求重新确认
```

相关代码是 `frontend/src/v2/WorkbenchPage.tsx:31`、`:535`、`:689`。咨询输入在恢复、未确认、run 执行或请求 pending 时禁用，见 `:801`；这既避免双发，也让用户知道下一步该做什么。

移动抽屉的焦点约束位于 `frontend/src/v2/AppShell.tsx:56`。结果证据抽屉位于 `frontend/src/features/results/EvidenceDrawer.tsx:14`，关闭后恢复触发点焦点。

## 22. 配置与快速运行

从 `.env.example` 复制本地配置，不提交真实密钥：

```powershell
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m app.db.migrate
.\.venv\Scripts\python.exe -m app.serve --host 127.0.0.1 --port 8000
```

前端另开终端：

```powershell
Set-Location frontend
npm.cmd install
npm.cmd run dev
```

接受态需要的关键非秘密项：

```dotenv
AUTH_ENFORCED=true
SESSION_QUOTA_PER_USER=3
QWEN_EMBED_MODEL=text-embedding-v4
EMBED_DIM=1024

RESUME_CLARIFY_ENABLED=true
RESUME_CLARIFY_MAX=2
CONSULT_COACH_ENABLED=true
CONSULT_COACH_MAX=3

RAPTOR_ENABLED=true
RERANK_ENABLED=true
RERANK_MODEL=gte-rerank-v2
RERANK_ENDPOINT=...
```

数据库迁移必须先跑；当前迁移目录含 `0008_resume_upload_generation.sql`。`EMBED_DIM` 必须与 pgvector 列维度一致；rerank 开启时 endpoint 必须可用。开发用 console OTP 不能当作生产邮件/短信能力。

## 23. 测试、契约与评估命令

```powershell
# 后端与静态检查
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe -m pyflakes app scripts

# 前端
Set-Location frontend
npm.cmd test
npm.cmd run typecheck
npm.cmd run build
npm.cmd run e2e

# OpenAPI 契约
Set-Location ..
.\.venv\Scripts\python.exe scripts\export_openapi.py
Set-Location frontend
npm.cmd run api:generate
npm.cmd run api:check

# 版本化演示评估
Set-Location ..
.\.venv\Scripts\python.exe scripts\evaluate_demo_corpus.py --include-raptor --use-cross-encoder
```

真机服务和数据库准备好后，可执行 `scripts/global_smoke.py` 与 `scripts/demo_rehearsal.py`。脚本会产生真实外部调用或数据库写入，答辩前应在专用演示环境运行，而不是把版本化报告误当作本机此刻已经复跑。

## 24. 答辩问答与诚实表述

**问：为什么不用模型判断签证和地点？** 这些是可结构化、可验证的硬条件，SQL 更稳定，也能留下 filter log；模型只负责语义排序和解释。

**问：怎样证明澄清不是编造？** 回答必须对应 pending 目标和同一简历 baseline；`C###.text` 保存用户原话；摘要不能添加原话外 token；策略和发布门再核对 evidence ID。

**问：PM 模型挂了会怎样？** 用户轮次已在第一次 CAS 提交。第二次 PM 调用失败只终结 reservation 并记日志，主咨询继续，因此不会为辅助气泡丢失用户输入。

**问：双开最好，是否说明已经达到生产效果？** 不能这样说。双开在 15 条查询、852 个 LLM 池化判定对上取得本轮最高离线指标；标签未经人工复核，且 Recall 是池内口径。它支持通道相对比较，不支持录用效果结论。

**问：服务重启会自己恢复全部任务吗？** checkpoint 让同一 run 再次触发时可以续跑，结果保存幂等；当前没有外部队列自动重派所有中断 run。

**问：四组合等价是什么意思？** 关闭开关时，对应功能不应改变旧状态合同和公开结构；不是说开启与关闭的排名必须一样。后端矩阵和批次 9 两种真机开关态共同验证这一边界。

**问：还有哪些已知不足？** 外部模型和网络依赖仍在；LLM 标签未经人工复核；反馈写入与隐式读取表尚未统一；支付、账号删除和自动任务队列不在当前闭环。完整清单见 `docs/limitations_and_future_work.md`。

## 25. 可核来源清单

本文所有离线检索指标只使用：

- `data/eval/demo_corpus_cross_v1/manifest.json`
- `data/eval/demo_corpus_cross_v1/labels.jsonl`
- `data/eval/demo_corpus_cross_v1/rankings.json`
- `docs/validation/2026-08-06-cross-encoder-ablation.md`

测试计数、四组合与 P1–P4 真机结论只使用：

- `docs/validation/2026-08-07-batch9-acceptance.md`

功能和行号引用来自冻结 HEAD `2474e48` 的实际文件。若代码继续变化，应先更新 Markdown 源稿，再用 `scripts/render_guide_docx.py` 重新生成 Word，不能只手工修改 DOCX。
