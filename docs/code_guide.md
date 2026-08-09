# Career-RAG 代码导览（冻结态 V2）

## B6-L3 i18n navigation and boundaries

1. `frontend/src/i18n/index.tsx` defines `Language` as `zh | en` and implements exact-key `translate`.
2. `frontend/src/app/providers.tsx` installs `LanguageProvider`; page call sites use `useLanguage()` for `lang`, `t`, and `setLang`.
3. `LanguageToggle` lives in the same i18n module and exposes current and target languages through its accessible label.
4. Actual placements are `HomePage` navigation, `WelcomePage` top bar before **Skip introduction**, `LandingPage` login card, and `AppShell`'s `v2-lang-float` desktop top-right plus `v2-lang-mobile` mobile navigation.
5. Chinese is the default; `LANGUAGE_STORAGE_KEY = "career_rag_lang_v1"` persists only `zh|en` in `localStorage`, with invalid values returning to `zh`.
6. When storage fails, `memoryLanguage` retains the selection only for the current loaded application/page lifecycle; it does not survive a full reload while storage remains unavailable. `resetLanguageForTests` clears both forms of state.
7. The provider also updates `document.documentElement.lang` (`zh-CN`/`en`) and the document title.
8. `frontend/src/i18n/en.ts` holds `EN_TRANSLATIONS`; unknown entries retain the source Chinese key rather than being guessed.
9. L1 covers front-end-owned static chrome, templates, and accessibility text at `t("…")` call sites.
10. L2 covers deterministic backend projection copy only; `// BACKEND_SOURCE_KEYS_START` and `// BACKEND_SOURCE_KEYS_END` delimit its checked dictionary section.
11. L2 approved sources are `app/api/conversation_projector.py` and `app/api/v1/sessions.py`; new L2 copy must update both source and marked dictionary section.
12. L3 is source-isolated: `user_message`, `assistant_reply`, `next_question`, dynamic `supervisor_notes`, job/resume data fields, JD evidence, and LLM-generated content render directly, never through `t`.
13. `frontend/src/v2/WorkbenchPage.tsx` sends every `runMessages` item through `t(item.text)`, including interpolated/dynamic error-detail items; those items are deliberately absent from the exact-match dictionary and therefore fall back unchanged. Consultation fields and dynamic Supervisor notes remain explicitly outside `t()`. `frontend/src/features/results/EvidenceDrawer.tsx` directly renders `reason` and `item.content`.
14. Fixed resume-progress narration is also deterministic L2 product copy and exact-match translated; it is not L3 user/model data.
15. `frontend/src/v2/AppShell.tsx` shows this English-only notice: `Some generated or data-dependent conversation content may remain in Chinese.`
16. `scripts/check_i18n_backend_drift.py`, invoked by `tests/test_i18n_backend_drift.py`, guards L2 drift; `frontend/src/i18n/i18n.test.tsx` covers persistence, fallback, desktop/mobile controls, and L3 isolation.
17. The same i18n test has three static-page no-Han guards: English `HomePage`, `WelcomePage`, and `LandingPage` bodies contain no Han characters.
18. `frontend/e2e/english-language-journey.spec.ts` covers mobile journey persistence, mobile toggle restoration, document-title changes, and invalid-storage fallback.

> 对齐代码：`de2fd83`（B5+B6 终审完成时点）。这份文档面向答辩走读：先说用户动作，再指出后端数据如何流动，最后给出可以当场打开的文件与行号；行号以该提交为准，后续批次可能漂移。

## 1. 一分钟理解代码

把系统想成一家线上职业咨询工作室：前台负责登录、收简历和展示进度；需求顾问先把求职目标问清；岗位顾问去数据库找岗位；规划师给出简历和职业策略；项目经理（PM）在咨询与正式运行两个阶段监督质量。

**RAG** 是“先检索证据，再基于证据生成答案”。本项目再加两条底线：签证、地点等硬条件由 SQL 判断；简历建议和匹配解释必须引用真实证据编号，不能只凭模型想象。

一次主流程如下：

```text
登录 → 建会话 → 上传简历（200，generation+1，零 LLM 本地提取）
→ 用户确认解析（202，扣一次解析额度）→ 后台归一化
→ 预览并确认 resume_version → 咨询三项必需信息
→ 可选简历澄清 → 可选 PM note → finalize
→ Match Brief 锁定 → run 执行 → 七阶段播报
→ 分层岗位/证据/策略 → 反馈
```

## 2. 代码地图

```text
app/
├─ api/              FastAPI、认证、会话与 run API、公开字段投影
├─ normalization/    简历解析、归一化、R### 证据和澄清目标
├─ agents/           咨询、三个业务 Agent、Supervisor、PM coach
├─ retrieval/        SQL 硬过滤、BM25、Dense、RAPTOR、RRF、Cross-Encoder
├─ graph/            LangGraph 七节点编排与 PostgreSQL checkpoint
├─ db/               连接池、迁移、SharedState/run/event 持久化
├─ state/            SharedState 单一事实来源与有效简历视图
├─ memory/           用户画像、反馈闭环、匿名案例
├─ evaluation/       排名、硬过滤和证据忠实度指标
└─ llm/              DeepSeek、Qwen embedding 与 reranker 客户端
frontend/src/
├─ app/              路由与空态
├─ v2/               登录、壳、群聊工作台、档案与运行进度
├─ features/         结果证据、反馈、评估与监控组件
└─ api/              Cookie 请求、查询封装、OpenAPI 生成类型
scripts/             迁移外的导入、评估、冒烟、彩排和文档渲染工具
tests/               后端单元/契约/竞态/隐私/恢复回归
frontend/e2e/        浏览器端流程回归
```

## 3. API、认证与无状态服务

**无状态服务** 的意思是请求处理完成后，业务状态不只留在 Python 内存，而是按 `session_id` 写进 PostgreSQL，因此多个用户或多个服务实例不会共用一份可变全局状态。

| 模块 | 文件与关键函数 | 走读重点 |
|---|---|---|
| 应用生命周期 | `app/api/main.py:89` `lifespan`；`app/api/main.py:165` 路由挂载 | 启动连接池与 checkpoint，关闭时释放资源；只挂正式 router。 |
| 路由装配 | `app/api/v1/router.py:15` `capabilities` | 前端从能力声明得知 OTP 通道、监控、评估等可见能力。 |
| 认证 API | `app/api/auth/routes.py:75` `request_otp`；`:119` `verify_otp`；`:148` `logout`；`:155` `me` | OTP 请求、核验、Cookie 会话和当前账号。 |
| 数据库池 | `app/db/pool.py:18` `get_pool` | `asyncpg` 连接池复用连接；请求不自行新建数据库进程。 |
| 状态原子变更 | `app/db/state_store.py` `mutate_state_atomically` | 行级锁 + MutationOutcome 协议（B2）：mutator 在锁内拿到 version/generation/status，可动态决定本次是否写 status 列。 |
| 对外投影 | `app/api/result_projector.py`；`app/api/conversation_projector.py` | 内部 SharedState 与监督日志不会原样发给浏览器；群聊播报由确定性模板投影。 |

长任务采用“提交后轮询”：run API 执行、查状态、读对话和取结果分别位于 `app/api/v1/runs.py:54`、`:83`、`:95`、`:135`。这不是进程内任务队列；run 状态和事件落数据库。

## 4. SharedState：所有 Agent 的共同数据合同

`app/state/schema.py:68` 的 `SharedState` 是单一事实来源。主要分区是简历、职业目标、检索、策略、反馈与 `supervisor_log`。简历新增的澄清字段位于 `app/state/schema.py:22-26`，PM 预约记录位于 `app/state/schema.py:77`。

两个只读视图避免消费者各写一套拼接逻辑：

- `app/state/resume_view.py:11` `effective_resume_text`：功能开启时把已验证的 `C###` 澄清证据纳入有效简历文本。
- `app/state/resume_view.py:38` `all_resume_evidence_spans`：把原始 `R###` 与澄清 `C###` 证据统一提供给策略和监督核查。

这样既保留旧字段兼容性，也让新增证据只有一条消费路径。

## 5. 简历上传、generation、parse_count 与 version（v3 B2 确认制）

三个编号各司其职：**generation** 是”这是第几次上传”（CAS 令牌），
**resume_parse_count** 是”本会话确认解析了几次”（防烧钱额度，默认 3，
`RESUME_PARSE_LIMIT`），**resume_version** 是”第几份成功归一化的简历”。
上传/预览零成本不计额；LLM 外呼发起前失败的解析自动返还额度。

| 阶段 | 文件与关键函数 | 行为 |
|---|---|---|
| 接受上传 | 上传路由 `POST /resume`（200）；`accept_resume_upload` | 单事务：状态置 `resume_uploaded`、generation+1、旧确认作废、文件与本地提取结果写入 `resume_uploads`（BYTEA，不落磁盘）；只留最新一代。非白名单后缀 415，损坏文件 422（不入库不占代）。 |
| 恢复待解析 | `GET /resume-upload`；`get_pending_resume_upload` | 仅 `resume_uploaded` 态返回元数据，刷新/换设备恢复确认卡。 |
| 确认解析 | `POST /resume/parse`（body `{generation}`，202）；`begin_resume_parse` | 单事务 FOR UPDATE 单快照分类（优先级：额度满→`resume_parse_limit` ＞ 换代→`resume_changed` ＞ 解析中→`resume_processing` ＞ 未上传态→`resume_unparsed`），扣一次额度、置 queued，并在同事务内把字节读进内存交给后台任务——并发重传的 DELETE 伤不到在途任务。 |
| 后台归一化 | `_normalize_resume` | 输入为上传时的提取文本；`external_started` 阶段标记在首个 LLM 外呼前置位，之前失败走 `refund_parse_count`（无 generation 谓词 + GREATEST 下限；每任务至多一次由唯一 except 调用点保证）。 |
| 保存成功 | `save_normalized_resume` | 行锁 + generation **和** `status='resume_queued'` 双前置；命中才 resume_version+1 并置 ready。 |
| 保存失败 | `mark_resume_error` | 同双前置；旧任务晚到一律 no-op。 |
| 收尾清理 | `clear_resume_upload_content` | 定向 `session_id+generation` 把 BYTEA 与提取副本置 NULL（隐私：原件不留存）。 |
| 预览状态 | `get_resume_preview` | 稳定 409 detail 增加 `resume_unparsed`（已上传待确认解析）；ready 返回 version 与确认态。 |
| 确认档案 | `confirm_resume` | 行锁内核对 ready 与版本；uploaded 态返回 `resume_unparsed`。 |

**无条件生命周期保护（与澄清开关解耦）**：consult/finalize 端点对
`resume_uploaded`/`resume_queued` 一律 409。consult 落库对"LLM 等待期间
发生换代"的处理分两层：**澄清开关开启时由 Feature A 既有契约优先**
（409 resume_changed，本轮 transcript 不落）；**开关关闭时**（原先无
任何保护的路径）经 `MutationOutcome`（mutator 第四参拿到行锁内 status）
降级为只追加 transcript、不覆盖 status。match-brief 的 generation CAS
无条件生效（version 比对维持 Feature A 门控）。

这套生命周期堵住“重确认洞”：用户上传新简历后，旧确认立即失效；即使旧请求稍后返回，也不能让旧档案重新变成 current。发生竞态时后端返回 409，前端统一失效并重取 preview 与 consult 数据，入口在 `frontend/src/v2/WorkbenchPage.tsx:535`。

## 6. 简历归一化与澄清回路

### 6.1 归一化先建立证据

`app/normalization/resume_intake.py:241` 的 `build_evidence_spans` 先在本地把原文切成 `R001`、`R002`……；模型只能基于这些片段结构化教育、经历、项目与技能。`app/normalization/resume_intake.py:331` 的 `build_clarification_targets` 再把质量问题和内容过短的经历转成确定性的澄清目标，功能门在 `app/normalization/resume_intake.py:701`。

### 6.2 视觉 OCR 兜底（B4）

`app/llm/qwen_vl.py` 是 Qwen VL 的异步边界：`timeout=60`（httpx 分段）之上
再套 `asyncio.wait_for(90s)` 总墙钟、`max_retries=0` 把一次逻辑调用钉死为
至多一次传输尝试；`Semaphore(VL_MAX_CONCURRENCY=2)` 同时限制调用与 base64
内存峰值；`on_attempt` 回调在真正发起传输紧前触发——解析任务据此置
external_started（§1.2 返还语义的置位点；可返还＝置位前被
`except Exception` 捕获的失败，任务取消不返还——重启丢任务烧一次由
§1.2 定价、admin 重置救济）。图像解码/光栅化/编码另有独立
的 prep 信号量（sessions.py `_OCR_PREP_SEMAPHORE`，与 VL 闸不嵌套持有）。

`app/normalization/image_prep.py` 的八步管线依次是：①校验容器并执行 4000 万
解码像素闸门；②JPEG 用 `draft()` 预缩；③按 EXIF 纠正方向；④缩到 400 万
输出像素内；⑤透明图在白底展平、其余转 RGB；⑥先按 JPEG quality 70 编码；
⑦核算 base64 后是否不超过 10MB；⑧超限只再按 quality 50 编码一次，仍超限
就拒绝。顺序不能颠倒：方向纠正必须早于最终缩放，透明像素必须铺白底，否则
会出现尺寸判断偏差或黑底。

`app/api/v1/sessions.py` 的 `_normalize_resume` 有两路：图片在确认解析后准备 JPEG
并做一次 VL；PDF 先逐页本地提取，只把少于 `RESUME_OCR_PAGE_MIN_CHARS` 的前
`RESUME_OCR_MAX_PAGES` 页光栅化补读，成功文本替换对应页后再按原页序拼接。
J1 熔断语义是：图片 VL 失败进入统一 `resume_error`；PDF 第一次 VL 异常即停止
余下视觉调用，保留此前成功 OCR 与失败/未处理页的原生文本，并发“识别中断/
未识别”汇总。

`RESUME_OCR_ENABLED=false` 会撤回图片上传白名单、固定预览与 0 页 PDF 的
上传 422，并完全跳过 VL，回到 B4 前文本路径；开启期上传的图片在关闭后
确认解析会在扣额度前被 `409 resume_ocr_disabled` 拒绝（回滚窗口守卫）。
`tests/test_extraction_golden.py` 用冻结 fixture 逐字节守卫 PDF/DOCX/TXT
的文本与页数等价线。上传边界跟随 capability 开关：开启时只增加
PNG/JPG/JPEG/WEBP（真实容器格式必须匹配后缀，.jpg 族含多帧 MPO），上传
阶段仅做本地校验和持久化、零 VL，图片的 POST/刷新恢复都返回固定预览
“图片简历，确认解析后将进行视觉识别（约几分钱）”。

### 6.3 pending 锚点防止答非所问

`app/agents/consult_engine.py:292` 的 `run_consult_round` 是咨询主函数。进入一轮时，它先读取上一轮保存的 `pending_clarification`（`:311`），只有当前问题、目标和简历基线仍对得上，回答才会被消费。新问题及其 `target_ref`、`asked_round`、`baseline_version` 在 `:460` 附近一起落状态。

`app/api/v1/sessions.py:759` `_pending_baseline_matches_version` 再核对版本；`app/api/v1/sessions.py:816` `_record_clarification_turn` 负责消费闭环：

```text
open target → 生成一个澄清问题并保存 pending
→ 用户有效回答 / 明确跳过
→ 回答按 C### 原文证据保存，或把 target 标成 skipped
→ 清空 pending → 下一目标或进入 deepen/finalize
```

有效回答的 `span.text` 保存用户原话，`source=user_clarification`；编号由 `app/api/v1/sessions.py:893` `_next_clarification_span_id` 生成。回答摘要还要经过 `app/agents/consult_engine.py:586` `validated_answer_summary`，它不能加入用户原话中没有的 token。

### 6.4 消费范围与隐私边界

显式检索从 `app/retrieval/query_builder.py:40` `build_resume_retrieval_query` 读取有效简历；策略 Agent 和 Supervisor 也读取统一证据视图，所以 `C###` 可以支撑结果解释。匿名案例的隐式查询由 `app/retrieval/implicit_search.py:43` `build_implicit_query_text` 构造，只读取结构化教育、经历、项目和技能，不拼入澄清原话。这是“新证据可用于本人匹配，但不直接流入匿名案例查询文本”的边界。

## 7. 咨询引擎与 PM 咨询督导

咨询阶段由 `app/agents/consult_engine.py:174` `determine_phase` 决定：先补齐目标、地点、签证三项模板信息；开关开启且仍有目标时进入 `resume_clarify`；随后才进入探索或深挖。是否已经可以 finalize 由同文件 `:159` 的 `can_finalize` 计算。

PM 咨询督导采用 L1/L2 两层：

- **L1** 是不调模型的规则检查。`app/agents/consult_coach.py:62` `evaluate_consult_l1` 只看轮次、槽位完整度、连续停滞、阶段与预算。
- `app/agents/consult_coach.py:118` `select_coach_trigger` 在 `finalizable`、`stagnation`、`deepen_entry` 中选择一个触发；每轮至多一次，同类至多一次，总次数受配置限制。
- `app/agents/consult_coach.py:155` `reserve_coach_attempt` 先在数据库原子变更中写 reservation，避免并发请求重复花预算。
- **L2** 是受超时保护的模型调用。`app/agents/consult_coach.py:331` `run_consult_coach` 生成 PM note；`app/agents/consult_coach.py:247` `finalize_coach_reservation` 把成功或错误写成单调终态。

咨询持久化分两次 CAS（比较并交换，即“仍是我读取的旧版本才允许写”）：`app/api/v1/sessions.py:537` 先提交用户轮次并预约，`:632` 再调用 L2 和回写 note。L2 超时、解析失败或服务失败时采用 **fail-open**：用户轮次已经成功，不因一条 PM 提示失败而报错或回滚。

## 8. Match Brief：运行前锁定合同

Match Brief 把咨询结论分成两栏：硬约束给 SQL，检索方向和软偏好给排序。`app/agents/orchestrator.py:428` `_lock_approved_brief` 生成不可变计划、版本和哈希，并把 `settings.raptor_enabled`、`settings.rerank_enabled` 快照进本次 retrieval plan（`:443-444`）。公开确认单投影位于同文件 `:507`。

锁定后，执行请求必须带当前 `plan_version` 与 `plan_hash`。这样用户看到并批准的内容，就是后台实际执行的内容。

## 9. 三个业务 Agent 与正式 Supervisor

| 角色 | 文件 | 关键职责 |
|---|---|---|
| 意图 Agent | `app/agents/intent_agent.py` | 把已确认目标整理进 SharedState；硬约束字段必须过白名单。 |
| 匹配 Agent | `app/agents/matching_agent.py` | 调检索主链，过滤明确避开的角色，并发生成 Top 岗位解释，输出三层岗位。 |
| 策略 Agent | `app/agents/strategy_agent.py` | 给技能差距、简历修改计划和职业路径；无有效简历 evidence ID 的建议被过滤。 |
| Supervisor | `app/agents/supervisor.py` | 终审岗位数、ID、JD 证据、简历引用和发布条件；重检索/修复均为有界循环。 |
| 确定性 Harness | `app/agents/supervisor_harness.py` | 在 Agent 前后和发布前做不依赖模型的合同检查。 |

三个业务 Agent 是三类带不同 system prompt 的模型调用，共享同一个状态，不是三个微服务。

## 10. 检索：从硬过滤到双增强

`app/retrieval/hybrid_search.py:867` `hybrid_search` 是主入口：

1. `:918` 先查询硬过滤允许的 job IDs；空集合直接返回。
2. RAPTOR 开启时，`:924` 用 `asyncio.gather` 并行 BM25、Dense 与 RAPTOR；关闭时 `:945` 并行前两路。
3. `:950-956` 把 chunk 命中折叠到 job 级，再用 RRF 融合，避免同一岗位多个块挤占榜单。
4. `:984` 做 bi-encoder/字段/软偏好确定性重排。
5. Cross-Encoder 开启时，`:1005` 对候选池精排；运行时不可用则 `:1042` 明确回到同参数、关闭 cross 的主链，配置缺失则直接报错，不静默伪装成功。

RAPTOR 离线建树入口是 `app/retrieval/raptor.py:300` `build_raptor_index`，在线检索是 `:352` `search_raptor_nodes`；它仍受 `allow_ids` 限制，不能绕开 SQL。

双空间入口 `app/retrieval/dual_space_search.py:27` `dual_space_search` 在 `:51` 并行显式岗位检索与隐式匿名案例检索。隐式空间失败时 `:108` 起安全退回显式结果；它只能给已经通过硬过滤的岗位有限加权，不能创建候选。

## 11. RAPTOR 与 Cross-Encoder 的四组合

两个开关是独立因子，不是“先开 RAPTOR 才能开 Cross”：

| RAPTOR_ENABLED | RERANK_ENABLED | 实际路径 |
|---|---|---|
| false | false | BM25 + Dense → RRF → 确定性重排 |
| true | false | BM25 + Dense + RAPTOR → RRF → 确定性重排 |
| false | true | BM25 + Dense → RRF → 确定性重排 → Cross-Encoder |
| true | true | 三路 RRF → 确定性重排 → Cross-Encoder |

“等价”指关闭某个功能后走冻结前的对应基线路径，而不是四种输出排序彼此相同。开关读取点在 `app/config.py:61-62`，每个 run 的快照点在 `app/agents/orchestrator.py:443-444`。批次 9 已用后端四组合矩阵、关闭态 P1–P3 和开启态 P1–P4 验证开关不污染不相关路径；实测来源是 `docs/validation/2026-08-07-batch9-acceptance.md`。

## 12. LangGraph 与恢复边界

`app/graph/build.py:20` `build_graph` 把 intent、lock_brief、retrieve_match、strategy、verify、prepare_reretrieval、publish 七个节点连成有界图。`app/graph/runner.py:25` `run_graph_match` 负责：

- 创建或读取 PostgreSQL checkpoint；
- 同一 run 再次触发时从可用 checkpoint 继续；
- 结果幂等保存；
- 终态清理包含私密状态的 checkpoint。

恢复边界要准确表述：系统具备“再次触发同一 run 时续跑”，不等于服务重启后自动重新派发所有中断任务。

## 13. 前端：一页群聊工作台

| 用户看到的区域 | 文件与锚点 |
|---|---|
| 登录/注册 | `frontend/src/v2/LandingPage.tsx:16` `LoginCard` |
| 无会话空态三步引导 | `frontend/src/app/router.tsx:11` `EmptyWorkbench` |
| 侧栏、额度、移动抽屉 | `frontend/src/v2/AppShell.tsx:26`；焦点管理 `:56`；额度 402 `:113` |
| 完整档案手风琴 | `frontend/src/v2/ResumeProfileAccordion.tsx:12` |
| 三项必需槽位 + 澄清槽位 | `frontend/src/v2/consultSlots.ts:10` `deriveConsultSlots` |
| 群聊主时间线 | `frontend/src/v2/WorkbenchPage.tsx:490` `WorkbenchPage` |
| 409 恢复分流 | `frontend/src/v2/WorkbenchPage.tsx:31` `resumeRecoveryState`；文案 `:38` |
| SQL 锁定/检索方向确认单 | `frontend/src/v2/WorkbenchPage.tsx:238` `BriefCard` |
| 运行进度卡 | `frontend/src/v2/WorkbenchPage.tsx:139` `ServiceProgressCard`；推导 `frontend/src/v2/runProgress.ts:86` |
| 证据抽屉与反馈 | `frontend/src/features/results/EvidenceDrawer.tsx:14`；`frontend/src/features/feedback/ReactionForm.tsx:18` |

所有请求统一经过 `frontend/src/api/client.ts:76`，方法封装在 `frontend/src/api/queries.ts:44`。`frontend/src/api/generated.ts` 由 OpenAPI 快照生成，不能手工维护。

## 14. B5：用量计量、管理员鉴权与 R9 收口

`app/llm/usage_context.py:35` 用 `ContextVar` 提供可嵌套的异步 `usage_scope(user_id, session_id, purpose)`；内层可只改 purpose，退出后恢复外层。DeepSeek、Qwen Embedding、Qwen VL 与 reranker 都通过模块属性调用 `record_llm_usage`，缺失或畸形 usage 只告警，不改变正常业务结果。

计量写入是 fail-open：`app/llm/usage_context.py:143` 在连续 5 次失败后静默 300 秒，到期只放一个探针；成功完全恢复，失败重新熔断，`CancelledError` 始终穿透。consult、normalize 和 run 在任务边界建 scope；`app/api/v1/runs.py:235` 的 wrapper 只按 `run_id` 联查一次属主，归因查询失败仍调用真实 executor，LangGraph async node、`BackgroundTasks` 与 `asyncio.to_thread` 继承同一上下文。

`app/api/auth/sessions.py:74` 给新会话 JWT 写入服务端验证通道产生的 `idp=email|phone`；旧 token 可缺省，非法枚举整票 401。`app/api/auth/deps.py:88` 的 `require_admin` 每请求核对四层：已登录、当前 token 的 `idp=email`、单条数据库快照中的实时 `is_admin`、该用户任一 email 身份命中 `ADMIN_EMAILS`；token_version 校验先于管理员身份查询。

管理员 API 全部由 `app/api/v1/admin.py:26` 的 router 级 `require_admin` 保护：

| API | 用途 |
|---|---|
| `GET /api/v1/admin/overview` | 用户/登录/会话/咨询/run 与 token 汇总。 |
| `GET /api/v1/admin/users?page=` | 分页用户和最近简历摘要。 |
| `GET /api/v1/admin/users/{user_id}/resume` | 跨用户读取最新完整结构化简历。 |
| `GET /api/v1/admin/runs/{run_id}/explain` | 读取终态 run 的公开 trace，不受 evaluation capability 门控。 |
| `POST /api/v1/admin/sessions/{session_id}/reset-parse-count` | 行锁内清解析次数，并收敛重启遗留 queued。 |

监控端点保留在 `app/api/v1/monitoring.py`，依赖顺序固定为 `require_monitoring_enabled` 后 `require_admin`，所以关 flag 时统一 404 且零身份查询。前端 `/admin` 壳在 `frontend/src/v2/AdminPage.tsx:116` 做无闪现 `/me` 门禁；Dashboard/用户/评估监控分别在 `frontend/src/v2/admin/`。`frontend/src/app/router.tsx:45` 把 R9 三条旧 settings 路径重定向到 `/admin` 对应 tab，并保留 evaluation 的 `runId` 查询参数。

## 15. 评估与测试如何读

`app/evaluation/metrics.py:12` `evaluate_rankings` 计算 P@K、R@K、MRR、NDCG；`:141` 核验硬过滤；`:169` 检查解释是否引用本岗位证据。演示评估入口是 `scripts/evaluate_demo_corpus.py:136`。

冻结态实测计数（V2 交付线）：pytest **642 passed**、Vitest **105/105**、Playwright **14/14**、全局冒烟 **32 passed, 0 failed**，来源 `docs/validation/2026-08-07-batch9-acceptance.md`。v3 各批的最新计数以 `docs/validation/` 下对应批次验收记录为准（B4：`2026-08-09-b4-acceptance.md`）。注：正文行号锚点对齐各批封版提交，个别锚点随后续批次会漂移，终局全量核对在 v3 五批完成后的三方 diff 阶段统一执行。

检索指标只引用 `data/eval/demo_corpus_cross_v1/` 与 `docs/validation/2026-08-06-cross-encoder-ablation.md`：15 条查询、852 个 LLM 池化判定对；双开结果 P@5 `0.920`、R@10 `0.323`、MRR `1.000`、NDCG@5 `0.939`。标签未经人工复核，Recall 是池内口径，不能解释成个人求职成功率。

## 16. 答辩时最值得现场打开的五处

1. `app/db/state_store.py:207`：一次原子更新如何建立新 generation 并作废旧确认。
2. `app/api/v1/sessions.py:816`：用户澄清如何变成逐字保存的 `C###` 证据。
3. `app/agents/consult_coach.py:118`：PM 为什么只在三类时机介入且不会超预算。
4. `app/retrieval/hybrid_search.py:918`：SQL 允许集合如何约束三路并行检索和精排。
5. `frontend/src/v2/WorkbenchPage.tsx:535`：409 后如何丢弃过期客户端状态并恢复。

这五处共同回答了评委最常问的三个问题：如何防并发错写、如何防 AI 编造、如何证明开关与恢复不是只写在文档里。
