# v3 产品迭代方案（v2.7-final · 2026-08-08 · 唯一权威全文 · 三方评审收敛）

> **收敛声明**：本方案经九轮三方评审于 2026-08-08 收敛——Claude 自审 +
> 子 agent（第四至九轮连续六 PASS）+ Codex（第九轮 PASS，0B/0M/0m）。
> 自此进入执行阶段：每批四门 + 对侧抽查；五批完成后三方全量 diff 查 bug。

> 修订史：v1→v2.6 经八轮三方评审收敛（子 agent 四至八轮连续 PASS；Codex
> 第八轮残留 1M/3m/1nit 于本版处置，见 §15）。v1–v2.2 为未入库草稿；git 内
> 前版 v2.3/v2.4/v2.5。**正文自包含**；唯一跨文档指针：历史意见处置表存于
> git v2.3 §12（非规范性）。
> **规范性引用原则（评审裁定，v2.6 锚点修正版）**：保留型约束的权威源＝
> 现行代码与钉死它们的测试；本方案不复制字面值以防双源漂移（例外：引自
> 钉死测试的短子串可内联，如 §3.3 存活子串）。完成判据＝锚点测试全绿。
> **锚点表（经第七轮逐一核正）**：
> - role_clusters **咨询词表**：权威源 consult_engine.py:50（prompt 词表，
>   **不含 other**）。岗位侧聚类词表（含 other——consult_engine.py:818-831、
>   scripts/load_jobs.py:145-160）是**另一个集合**、用途不同，不属本约束；
>   两表并存非冲突，系有意分层（裁定记录于此）。现有测试只抽查三值，
>   **B3 新增全集钉死快照测试**（见 §3.1）。
> - clarify 后缀键名：test_resume_clarification_engine.py:**100-101**
>   （answer_summary/clarification_action 断言处；原引 94-99 有偏，已正）。
> - phase 枚举与 120/80 上限：定义源 consult_engine.py:24、94-95 +
>   schemas.py:204-206、225-227、**241（ConsultStateResponse 侧第三处
>   公开 DTO）**；现无全值测试，**B3 钉死快照一并覆盖**（四值枚举 +
>   120/80 常量 + 三处 DTO 声明一致性：ConsultTranscriptEntry/
>   ConsultResponse/ConsultStateResponse 与内部 ConsultPhase）。
> - 四开关矩阵：test_consult_coach.py:944-1116（第七轮验证有效）。
> - G17/G18 语义：docs/validation/2026-08-07-global-audit-findings.md:70。
> 宪法裁决（用户 2026-08-08，已入库 de88946）：`asyncio.to_thread` 卸载阻塞
> 库调用为"禁 threading"硬约束的明确允许例外（AGENTS.md §2.2 /
> CLAUDE_LANGGRAPH.md §2.2）；仍禁自建线程/线程池/共享可变状态。
> 原则：无状态服务（Postgres 单一状态源）、bounded loop、硬过滤走 SQL、
> evidence 不编造、外部调用过 Semaphore、一次一批跑通再下一批。

## 0. 需求映射与执行顺序

| # | 需求 | 批次 | | # | 需求 | 批次 |
|---|---|---|---|---|---|---|
| R1 | 图片/扫描识别 | B4 | | R6 | 小意热情人设 | B3 |
| R2 | 解析叙事+逐行+耗时 | B3 | | R7 | 首访先 /welcome | B1 |
| R3 | 质量提示/证据折叠 | B1 | | R8 | 对话框对齐 | B1 |
| R4 | 确认上传/解析+限3次 | B2 | | R9 | 移除评估/监控入口 | B5 |
| R5 | 逐条出现+用户气泡 | B1+B2 | | R10 | 管理员页 | B5 |

顺序 **B2 → B1 → B3 → B4 → B5**（裁决落地后五批均无前置阻塞）。
迁移：B2=0009、B3=0010、B5=0011。

**R4 口径（用户知悉）**：限额按解析次数（`RESUME_PARSE_LIMIT=3`）；重传不耗
额度；外部调用发起前失败不耗额度（§1.2 返还）。
**R1 裁减（用户知悉）**：纯扫描 DOCX 不做内嵌图 OCR，引导转 PDF/图片重传；
覆盖 PDF（原生/扫描/混合）+ 图片 + 文本 DOCX。

## 1. B2 上传确认流 + 解析限额（后端 + 前端，同批部署）

### 1.1 持久化（migration 0009，完整 DDL）

```sql
CREATE TABLE resume_uploads (
  session_id  TEXT NOT NULL REFERENCES session_state(session_id) ON DELETE CASCADE,
  generation  BIGINT NOT NULL,
  filename    TEXT NOT NULL,
  suffix      TEXT NOT NULL,
  content     BYTEA,
  extracted_text TEXT,
  pages       INT NOT NULL DEFAULT 0 CHECK (pages >= 0),
  chars       INT NOT NULL DEFAULT 0 CHECK (chars >= 0),
  ocr_suggested BOOLEAN NOT NULL DEFAULT FALSE,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (session_id, generation)
);
ALTER TABLE session_state ADD COLUMN resume_parse_count INT NOT NULL DEFAULT 0
  CHECK (resume_parse_count >= 0);
```

同步 schema.sql。上传不落磁盘（`persist_upload`/unlink 移除，
test_uploads.py 整文件重写）；10MB 上限在新持久化函数内**流式读入内存缓冲、
超限 413**。**上传时本地提取**：POST 处理器内经 `asyncio.to_thread(
extract_resume_text_bytes, ...)` 执行（裁决允许；与现行 intake 同边界）；
损坏/不可解析文件 → **422 `unreadable_file`**（不入库、不占 generation——
提取在 accept 事务之前执行，失败即返回）。**intake 输入契约**：
`extract_resume_text`/`intake_resume` 增 `bytes + suffix` 重载；CLI 保留
Path 适配。

### 1.2 状态机与原子操作（SQL 语义写死；不假设请求串行）

```
awaiting_resume → resume_uploaded → resume_queued → resume_ready / resume_error
```

- `accept_resume_upload`（单事务，行锁先行）：
  ① `UPDATE session_state SET resume_upload_generation =
     resume_upload_generation + 1, status='resume_uploaded',
     confirmed_resume_version=NULL, resume_confirmed_at=NULL
     WHERE session_id=$1 RETURNING resume_upload_generation`；
  ② `DELETE FROM resume_uploads WHERE session_id=$1`；③ INSERT 新行。
- `begin_resume_parse(session_id, generation, max)`（单事务，单快照分类）：
  ① `SELECT status, resume_upload_generation, resume_parse_count,
     owner_user_id FROM session_state WHERE session_id=$1 FOR UPDATE`
     （无行→404；owner_user_id 供 §5.1 归因）；
  ② 锁内分类，优先级 `parse_limit ＞ resume_changed ＞ resume_processing
     ＞ resume_unparsed`；
  ③ `UPDATE session_state SET status='resume_queued',
     resume_parse_count = resume_parse_count + 1 WHERE session_id=$1`；
  ④ 同事务 `SELECT filename, suffix, content, extracted_text, pages, chars
     FROM resume_uploads WHERE session_id=$1 AND generation=$2`——字节入
     内存传 BackgroundTask（行缺失→回滚，按 resume_changed）。
  已证：与 accept 的全部交错在行锁串行化下安全；双击单扣。
- `save_normalized_resume` / `mark_resume_error`（**改造为单事务 CAS +
  终态事件**）：两函数各增可选 `terminal_event` 参数，类型
  `TerminalEvent{step: Literal["done","error"], text: str,
  elapsed_ms: int}`；实现为**同一事务内**
  `UPDATE session_state ... WHERE session_id=$1 AND
  resume_upload_generation=$n AND status='resume_queued'
  RETURNING session_id` —— **RETURNING 命中才** INSERT 终态进度事件
  （不带 §3.1 的 EXISTS 守卫，正当性由 CAS 保证）；未命中整体 no-op、
  不写任何事件（补 CAS miss 全回滚测试）。**seq 分配协议**：非终态事件
  由任务内计数器分配 1..99；终态固定 `seq=100`（保留段）——每代仅一个
  任务（begin CAS 保证）且终态至多一次（本 CAS 保证），PK 冲突按构造
  不可达；万一发生则事务回滚整体 no-op。
  **跨批归属（B2 对侧抽查后澄清）**：`resume_intake_progress` 表属
  migration 0010（B3），故 `terminal_event` 参数与事件 INSERT **随 B3
  一并落地**；B2 只落 generation+status 双谓词 CAS（防重复落库），
  此为方案的批次归属勘误而非实现缺口。
- **返还**：`_normalize_resume` 单 try/finally 内维护 `external_started`
  （进度阶段 normalizing/ocr 置位）；失败且未置位 →
  `UPDATE session_state SET resume_parse_count =
  GREATEST(resume_parse_count - 1, 0) WHERE session_id=$1`（无 generation
  谓词；扣费先于任务启动已提交，归纳保证正常运行不触下限；每任务≤1 次
  返还由唯一任务体的唯一 except 调用点保证）。admin 重置与在途任务交错可多还 1 次
  （上界 1/任务，偏向用户，已接受）。restart 丢任务烧 1 次，救济 §5.3。
- 清理：任务 finally `UPDATE resume_uploads SET content=NULL,
  extracted_text=NULL WHERE session_id=$1 AND generation=$2`（清理范围＝
  上传原件与临时提取副本；resume_state 的证据/摘要属产品数据，保留）。
- `_RESUME_LIFECYCLE_DETAILS` 增 `resume_unparsed`、`resume_parse_limit`。
- **生命周期无条件保护（与 clarify flag 解耦）**：
  - consult/finalize 端点前置（无条件）：`resume_uploaded`→409 unparsed、
    `resume_queued`→409 processing；`resume_error` 留 flag 门控（基线）。
  - **consult 落库保护（generation 为主判据）+ 所需契约扩展（三件，
    实现前置写死）**：(i) `mutate_state_atomically` 向 mutator 增传
    locked.status（`_load_locked_state` 已 SELECT 该列，仅穿参）；
    (ii) **mutator 返回协议**：由"返回业务结果"改为返回
    `MutationOutcome{result: Any, status_override: str | None |
    KEEP_SENTINEL}`——`KEEP`（默认）＝沿用调用方传入的 persisted_status；
    `None`＝本次不写 status 列只落 state（该写路径已存在）；`str`＝覆写。
    既有调用点以 KEEP 语义零行为变化地迁移；(iii) flag-off consult 读路径
    由 `load_state` 换为带 generation 的 context loader。
    判定：行锁内 `locked.generation != loaded_generation ∨ locked.status ∈
    {'resume_uploaded', 'resume_queued'}`（全名，与状态机字面一致）→
    status_override=None 只追加 transcript（降级路径跳过
    `_merge_feature_a_resume_state`）。
    **双 flag 语义（B2 对侧抽查后澄清）**：flag-on 的 generation 失配由
    Feature A 既有契约**优先**处理（409 resume_changed、transcript 不落，
    五轮评审确认保持）；transcript-only 降级实际覆盖 flag-off 路径
    （原先无保护的那条）。两条路径各自有测试钉死。
  - **match-brief**：generation 比对提出 flag 门控（无条件生效，失配→409
    resume_changed）；**version 比对维持 flag 门控不变**（防打破
    test_api_v1.py:198 既有 fixture 基线；如该批顺手补 fake 实参亦可，
    二选一在实现时定，测试口径以此为准）。

### 1.3 API 契约

- `POST /sessions/{id}/resume`（202→200，require_owned_session）→
  `ResumeUploadedResponse{generation, filename, pages, chars,
  text_preview(≤600字·经 _redact_contact_text 脱敏), parses_used,
  parses_limit, ocr_suggested}`；415 `unsupported_file_type`；
  422 `unreadable_file`。
- `GET /sessions/{id}/resume-upload`（require_owned_session）：仅
  `status='resume_uploaded'` 返回上述同构元数据（不含 content），否则 404。
- `POST /sessions/{id}/resume/parse`（require_owned_session，202）：
  请求 DTO `ResumeParseRequest{generation: int}`——必须回传预览所得
  generation；旧标签页解析未预览新代 → 409 resume_changed。**响应复用
  现有 `ResumeAcceptedResponse{session_id, status:"resume_queued"}`**。
- `resume-preview` / `resume-confirm` 在 uploaded 态 → 409 `resume_unparsed`。
- OpenAPI 快照 + generated.ts + apiFixtures.ts 同批再生。
- **文档同步（B2 批内完成）**：project_functionality_and_code_guide.md、
  code_guide.md、product_guide.md 的上传/解析章节；**deploy_guide.md 的
  前端与 Caddy 章节**（全新安装路径改 releases/symlink 布局 + 首次
  bootstrap：创建初始 `frontend-current` 符号链接、旧 `frontend-dist`
  目录废弃说明），与 §7 部署布局保持一致。

### 1.4 前端（WorkbenchPage 上传 UX 整体迁移）

- Composer 左侧回形针按钮（`accept=".pdf,.docx,.txt"`；图片后缀 B4 放开，
  之前置灰提示"图片识别即将开放"）。选文件 → **用户侧气泡**（文件名+大小+
  「确认上传」「取消」）→ POST upload → 小意气泡预览（页数/字数/前 600 字
  + `parses_used/parses_limit` + ocr_suggested 提示）+「确认解析」→
  POST parse → 现有 processing 轮询。
- 挂载时 GET resume-upload 恢复确认卡；沿用会话切换 reset effect
  （WorkbenchPage.tsx L666-676）并覆盖 upload/parse 两个 mutation。
- 三处旧 `<input type="file">`（L851/L886/Accordion）收敛到 composer；
  `resume_error` 文案指向 composer；**PM 欢迎语（L841）与输入框占位符
  （L1112）同批改写指向 composer**。
- `resume_parse_limit` → 解析按钮禁用 + "本会话解析次数已用完（3/3）" +
  「新建会话继续」CTA + 附注"会话额度也用完时请联系管理员重置"。

### 1.5 测试

- 必改后端：test_resume_generation_lifecycle.py（L233/263/425/819 区）、
  test_api_v1.py（`PUBLIC_PATHS` 常量加 2 新端点 + 快照重生成）、
  test_uploads.py（整文件）、test_memory_phase_e.py:583、
  test_auth_ownership.py（GET resume-upload、POST parse）、
  test_config_env_boundary.py（RESUME_PARSE_LIMIT）。
- 必改前端：WorkbenchPage.test.tsx（~L409/700/706/716/1481/1510，6–10 个
  用例重写）、apiFixtures.ts、e2e/full-flow.spec.ts。
- 新增：双击 parse 单扣费；upload 零 LLM；第 4 次 parse 409；分类优先级；
  accept/begin 三时序交错；解析中重传→在途产物作废且新行完好；重传竞态下
  预外呼失败仍返还；外呼后失败不返还；415/422；刷新恢复；双清定向；
  flag=false 下 uploaded/queued 态 consult/finalize 409；consult LLM 等待
  期换代 → **flag-on 按 Feature A 契约 409 且 transcript 不落、flag-off
  降级为 MutationOutcome(status_override=None) 只追加 transcript**（两条
  路径各测）；match-brief flag-off 并发上传 → 409；parse 回传旧
  generation → 409；confirm uploaded→resume_unparsed；GET resume-upload
  非 uploaded→404；限额后新建会话可用。（终态事件 CAS-miss 回滚测试随
  terminal_event 归属 B3，见 §1.2 跨批归属澄清与 §3.1 测试清单。）
- 原样回归：四开关矩阵（test_consult_coach.py:944 起）、
  test_resume_clarification_api/engine、test_intent_consultation、
  test_api_concurrency、e2e/mobile.spec.ts。

## 2. B1 前端体验包（纯前端）

1. **R7 首访流**：`/` 在 `!hasSeenIntro()` 时 `<Navigate to="/welcome">`
   （CSR 同步判断）。/welcome 顶部「跳过介绍」与底部 CTA 均
   `markIntroSeen()` + `navigate("/", {replace})`（replace 防返回键重看）。
   **勘误（B1 三方审查）**：introSeen 的模块级内存旗标使 markIntroSeen 后
   hasSeenIntro 恒真——写失败场景由内存旗标保证本会话不成环，原"回读
   失败 → /login"分支不可达、予以移除。**已登录例外（B1 审查裁定）**：
   已登录且无标记的存量用户在 /welcome 自动补写标记后直达 /app（闪屏至多
   一次，此后首页可达）；已登录且有标记者显式访问 /welcome（首页「了解它
   如何工作」）正常观看。首页「进入应用」→ 已登录 `/app` 否则 `/login`。
   更新 HomePage/WelcomePage/router 测试与两条 e2e 剧本入口。
2. **R5 逐条出现**：`useStaggeredReveal` hook——仅对**本次轮询新增**消息
   按序 `animation-delay = i*450ms`（历史消息不重播）；PM 与小意两条欢迎语
   先 PM、600ms 后小意；`prefers-reduced-motion` 全部即时。
3. **R3 折叠**：ResumeProfileAccordion 内「档案质量提示」「原文证据」移至
   末尾各包 `<details>`（summary 带条数徽标）；vitest 断言默认收起、
   点击展开。
4. **R8 对齐（可量化）**：375/768/1280px 三档检查项——grouped 消息左缩进
   = 头像列宽+间距；气泡内卡片 padding 统一 16px；composer 行内元素垂直
   居中；stage divider 上下间距相等；确认卡按钮右对齐。
   **验收物口径（B1 审查裁定）**：工作台需真实后端渲染，三档截图于
   **B1 部署后在线上采集**交用户过目（本地仅覆盖 /、/welcome、/login）。

## 3. B3 小意解析叙事 + 档案逐行 + 计时 + 人设

### 3.1 进度事件（migration 0010，完整 DDL）

```sql
CREATE TABLE resume_intake_progress (
  session_id  TEXT NOT NULL REFERENCES session_state(session_id) ON DELETE CASCADE,
  generation  BIGINT NOT NULL,
  seq         SMALLINT NOT NULL,
  step        TEXT NOT NULL,
  text        TEXT NOT NULL,
  elapsed_ms  INT NOT NULL DEFAULT 0,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (session_id, generation, seq)
);
```

- 非终态事件（parse 任务体 `_IntakeNarrator` 发出：received/extracted/
  normalizing/ocr/validated）：首事件事务 = `DELETE ... WHERE
  session_id=$1 AND generation < $2` + 守卫 INSERT；每条 INSERT 带
  `WHERE EXISTS(SELECT 1
  FROM session_state WHERE session_id=$1 AND resume_upload_generation=$2
  AND status='resume_queued')`；EXISTS 为快照读，极端交错下旧代可残留
  无害孤儿行（上界＝该代非终态事件数，与 §8 口径一致；PK 含 generation、
  读端按当前代过滤）。
- **终态事件（done/error）**：由 save_normalized_resume/mark_resume_error
  经 `terminal_event` 参数在 §1.2 的单事务 CAS 内写入（RETURNING 命中才
  写）；任务体叙事**不落**终态事件，仅承载信息（含 §1.2 阶段标记信息源）。
- **进度发射点（B3 执行期三方复审勘误，替代原"intake_resume 增可选回调
  progress"要求——该要求作废）**：B2 已把生产解析任务体定为
  `sessions._normalize_resume`（begin CAS 后的唯一任务体，intake_resume
  仅存 CLI 路径、无进度消费方），叙事由任务体内 `_IntakeNarrator` 发射
  （fail-open 旁路，写失败仅告警不影响解析）；B4 的 OCR 事件在同一任务
  体内同点发射（suffix/content 输入契约已预先贯通）。
- **`GET /sessions/{id}/resume-progress`（require_owned_session）契约**：
  200 `ResumeProgressResponse{generation: int|null, status: str,
  events: [{seq, step, text, elapsed_ms, created_at}], done: bool}`——
  events 取 `session_state.resume_upload_generation` 当前代、`ORDER BY seq`
  全量返回（协议硬上界 ≤100 行（非终态 seq 1..99 + 终态 seq=100），常态
  ≤10，无需游标）；从未上传（列值 0）→
  `generation=null, events=[]`；**`done = status != 'resume_queued'`**
  （离开 queued 即终——ready/error/uploaded 全部停轮询，覆盖"解析中重传"
  交错：重传后状态为新代 resume_uploaded → done=true，前端停进度轮询并
  回落确认卡）。前端双保险：记录发起 parse 时的 generation，响应换代即
  清旧代归属并刷新上传态。**换代语义细化（B3 二轮复审勘误码定）**：
  ① 新代为 resume_uploaded（远端重传未确认）→ done=true 停轮询、回落
  确认卡展示新代；② 新代已 resume_queued（远端重传并确认解析）→ 共享
  会话**跟随新代叙事**（轮询继续渲染现行解析）；两种情形下叙事气泡
  key、stagger resetKey、亲历/耗时/自发流归属一律绑定
  `(session_id, generation)`，串代即失配。交错测试拆 uploaded 与 queued
  两个各自状态自洽的夹具（progress/upload GET/preview 三端一致）。
- 前端：事件按小意气泡逐条出现（复用 B1 stagger）；done 展示"用时 X.X 秒"。
- 测试：回调序列；DELETE 代数谓词交错（迟到旧任务删不掉新代）；终态事件
  仅随 CAS 命中写入；所有权；前端 1200ms 轮询渲染、done 停轮询、逐行
  动画 + reduced-motion；**契约钉死快照测试（B3 新增，补齐头部锚点表
  声明的缺失权威）**：CONSULT_PROMPT 内 role_clusters 咨询词表**全集**、
  phase 四值枚举、120/80 上限常量、五条存活子串——全部逐字断言。

### 3.2 档案逐行 print（前端动画）

- 解析完成后小意发"档案摘要"气泡：前端由 preview 数据合成行数组（教育/
  每段经历/每个项目/技能各一行），逐行显现（~350ms/行，reduced-motion
  即时）；末行指向「查看完整档案」。不引入 SSE。

### 3.3 小意人设（R6）

- CONSULT_PROMPT 语气段扩写（热情、称呼、先共情再提问、emoji ≤1/条）。
- **存活子串逐字保留**：开头 `PHASE_C2_CONSULT_ADVISOR\n`、
  `Current consultation phase: {phase}`、`Ask exactly ONE heuristic
  question per turn`、`question max 80 Chinese characters`、`Never invent
  facts about the user`、JSON 键 `assistant_reply/next_question/
  profile_updates/phase_suggestion`（test_consult_engine.py:112-121 钉死）、
  clarify 后缀键名（test_resume_clarification_engine.py:**100-101** 钉死）、
  role_clusters 咨询词表全集（由本批新增的契约钉死快照测试钉死，见 §3.1）。
  120/80 上限、phase 枚举、bounded retry 2 不动。
- 前端欢迎语/错误文案热情化（不回退 B2 的 composer 指向）；进度事件模板
  即小意口吻（"收到！我先把简历读一遍～"）。

## 4. B4 视觉 OCR 兜底（后端 + 前端 accept；无迁移）

- `app/llm/qwen_vl.py`：DashScope OpenAI 兼容，`QWEN_VL_MODEL=qwen-vl-ocr`
  （首日真实冒烟确认模型名/参数），`Semaphore(VL_MAX_CONCURRENCY=2)`。
- 阻塞卸载：光栅化/编码走 `asyncio.to_thread`（宪法裁决允许例外）。
- 提取契约页级重构：`extract_resume_text` → `[(page_no, text)]`（对外拼接
  兼容；evidence page 语义不变；test_resume_intake 回归）。
- 策略：
  - PDF：页文本 `< RESUME_OCR_PAGE_MIN_CHARS(50)` → 读 mediabox，
    `scale = min(RESUME_OCR_RENDER_SCALE(2.0),
    sqrt(RESUME_OCR_MAX_PIXELS(4_000_000)/(w*h)))` 光栅化 → JPEG q70 →
    base64 ≤10MB？否则 q50 重试 → 仍超则**跳过该页**（保留原生文本，
    不硬失败）→ OCR。**合并＝按页替换**，页序不变；
    `RESUME_OCR_MAX_PAGES(6)` 只限 OCR 页数，其后页保留原生文本；
    **全部跳页/截断说明合并为单条汇总进度事件**（控制每代事件行数）。
  - 图片：**解码防炸=显式尺寸检查**——`Image.open` 后读 header 尺寸，
    `width*height > RESUME_OCR_MAX_IMAGE_PIXELS_DECODE(40_000_000)` →
    硬拒绝（上传态 422 / 解析态 resume_error）；不依赖 Pillow
    `MAX_IMAGE_PIXELS`（其超限默认仅告警、超两倍才抛错）；JPEG draft
    降采样 → 归一化到 MAX_PIXELS → 同管线。
  - DOCX：仅文本；无文本 → resume_error + "转 PDF 或图片重传"。
- **图片的上传/解析阶段边界（B4 内定义）**：图片后缀（.png/.jpg/.jpeg/
  .webp，按后缀判定）加入白名单后，**上传阶段零 VL 调用**——仅做 header
  解码尺寸检查（>40M 像素 → 422 unreadable_file），入库
  `extracted_text=''、pages=1、chars=0、ocr_suggested=true`，
  text_preview 固定为"图片简历，确认解析后将进行视觉识别（约几分钱）"；
  合法图片**不会**因无文本被 422（422 的"不可解析"仅适用 pdf/docx 提取
  异常）。VL 只在确认解析后的任务内调用。
- 终止：归一化后无任何可用 evidence span → resume_error（G17）。
- pypdfium2、Pillow 入 requirements.txt；前端 accept 放开图片 +
  ocr_suggested 文案（前后端批，四门含 vitest + frontend-dist 包）。
- **B4 配置与文档同步**：`.env.example` 与 `deploy/env.production.template`
  增 §7 所列 8 个 VL/OCR 变量；deploy_guide（依赖安装）、
  product_guide（图片简历说明）、code_guide（OCR 管线）同批更新。
- 测试（oracle 与正文逐分支闭合）：混合 PDF 仅低文本页 OCR + 按页替换；
  **q70 合格→VL 恰调 1 次（payload 为 q70 编码）；q70 超→q50 合格→VL 恰
  调 1 次（payload 为 q50 编码，编码尝试恰 2 次）；双超→VL 0 次 + 保留
  原生文本 + 跳页事件**；MAX_PAGES 截断后原生文本页保留；
  **40_000_000 像素恰好通过、40_000_001 硬拒**（双边界）；scale 收敛内存
  有界；VL Semaphore 上限；图片上传阶段 VL 0 次；docx 无文本引导；
  `RESUME_OCR_ENABLED=false` 逐字节等价；无 span→error；前端图片全流程。

### 4.1 B4 执行期偏差备案（终审收敛后入库，终局三方 diff 援引本清单）

细化方案三方收敛于会话工作稿（子 agent 三轮/Codex 四轮 PASS），执行与
终审（子 agent 二轮 PASS、Codex 三轮至纯文档收尾）产生的超字面增量：

1. `extract_resume_text` 对外签名不变，页级化为内部函数（§4 括注"对外
   拼接兼容"的落实读法）。
2. J1 失败语义：页本地确定性失败跳页保原生；首个 VL 异常熔断整段 OCR、
   继续归一化、汇总非静默（§4 跳页字面仅授权尺寸双超，此为裁决扩展）。
3. flag-on 时 0 页 PDF 上传态提前 422（flag-off 逐字节回 B4 前行为）。
4. 409 Literal 增 `resume_ocr_disabled`（回滚窗口：开启期上传的图片在
   关闭后确认解析，扣额度前拒绝）。
5. 后缀-真实格式绑定严于收敛稿；.jpg/.jpeg 含 MPO（同族解码器）。
6. VL 墙钟 wait_for(90s) 叠加 60s 分段超时；external_started 置位点＝
   on_attempt（传输紧前）；**可返还＝置位前被 except Exception 捕获的
   失败**；任务取消不返还（重启丢任务烧 1 次由 §1.2 定价、§5.3 救济）。
7. base64 编码在 VL Semaphore 内但未经 to_thread（毫秒级，接受）。
8. 解码/光栅化/编码另设 prep Semaphore（与 VL 闸分离不嵌套）。

四门与被测 SHA 见 docs/validation/2026-08-09-b4-acceptance.md。

## 5. B5 计量 + 管理员（migration 0011，完整 DDL）

```sql
CREATE TABLE llm_usage (
  id BIGSERIAL PRIMARY KEY,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  user_id TEXT, session_id TEXT,
  provider TEXT NOT NULL, model TEXT NOT NULL, purpose TEXT NOT NULL,
  prompt_tokens INT, completion_tokens INT,
  total_tokens INT NOT NULL DEFAULT 0
);
CREATE INDEX idx_llm_usage_created ON llm_usage (created_at);
CREATE INDEX idx_llm_usage_user ON llm_usage (user_id, created_at);
CREATE TABLE product_events (
  id BIGSERIAL PRIMARY KEY,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  kind TEXT NOT NULL, user_id TEXT
);
CREATE INDEX idx_product_events_kind ON product_events (kind, created_at);
```

### 5.1 计量（任务入口 usage_scope，零签名改动）

- 两表均 **await 写入 + fail-open**（遥测异常不得影响 P0；单测覆盖）。
- `app/llm/usage_context.py::usage_scope(user_id, session_id, purpose)`
  （contextvars），**全部在任务体内设置**：`_normalize_resume`
  （owner_user_id 来自 §1.2 **begin_resume_parse 步骤①** 的 SELECT；
  normalize，OCR 段嵌套 ocr）、consult
  端点（consult）、coach（coach）、**run 统一包装器
  `_run_with_usage_scope(...)`——透传 executor 既有全部参数与注入（含
  LangGraph checkpointer，runs.py:68-74 注入原样保留），仅额外包 scope，
  覆盖经典 orchestrator 与 `run_graph_match` 两支**（内层 supervisor/
  strategy/explain 嵌套细分）、memory/case_base（case_embed）。
- 记录在客户端内部：deepseek.chat、qwen_embed（embed_one 复用 embed_texts
  时**只在最内层 provider 请求处写一行**；LRU 命中零行）、reranker
  （仅 total）、qwen_vl。所有函数签名不变，既有测试假件零冲击。
- product_events 写入点：login / session_created / consult_turn /
  run_started / resume_parse。
- 测试：双 executor 归因带 session_id/user_id 且 **checkpoint 写入断言仍
  生效**；嵌套 scope；fail-open；缓存零行；单 provider 请求单行。

### 5.2 管理员鉴权（fail-closed + 即时撤权）

- `require_admin`：任何配置下要求已登录 + `users.is_admin` + **每请求实时
  校验 email 身份 ∈ ADMIN_EMAILS**（一次 user_identities 索引查询；白名单
  移除即时生效）。登录时同步列 `is_admin = (email ∈ 白名单)`（升降权自动；
  phone 身份恒非 admin）。解析规范：逗号分隔、trim、casefold、去重。
  break-glass：SQL 直改列 + 临时加回白名单。
- monitoring：**先 flag（关闭→404 语义保留）再 require_admin**（开启后
  匿名 → 401/403）；test_monitoring_api.py 匿名 200/404 用例按新序重写。
- 评估页：/admin/evaluation 走新 admin 端点（跨用户）；用户自查
  `/runs/{id}/explain`（require_owned_run）保留不动。

### 5.3 管理端 API 与页面

- `GET /api/v1/admin/overview`：用户/登录/会话/consult/run 计数（今日/7日/
  30日）、按日 token 曲线、按模型 token 与估算成本（前端单价常量，标注
  "估算·价格版本 2026-08"）。
- `GET /api/v1/admin/users?page`：email、注册/最近登录（last_login_at 回填
  最近一次）、会话数、最近简历摘要列。**最新简历定序**：
  `resume_confirmed_at DESC NULLS LAST, resume_version DESC, session_id`
  取首；全空 → "未上传"。
- `GET /api/v1/admin/users/{id}/resume`：最新 resume_state 全量（不脱敏，
  仅 admin）。
- `GET /api/v1/admin/runs/{run_id}/explain`（require_admin，跨用户，复用
  现有 explain DTO）。
- `POST /api/v1/admin/sessions/{id}/reset-parse-count`（require_admin，
  **单事务 FOR UPDATE**）三态语义显式化：① `resume_parse_count=0` 恒定
  执行；② 仅当 status='resume_queued'（restart 遗留）→ 置 resume_error +
  清该会话 resume_uploads 的 content/extracted_text；③
  status='resume_uploaded'（合法待解析）及其余状态 → 仅清零计数、不动
  上传与状态。响应 `{session_id, resume_parse_count: 0, status}`。
  **运维备忘（B3 二轮复审收编）**：若未来任何救济路径把**同一代**重新置回
  resume_queued（当前端点不这么做；正常流每代至多一次入队），必须连带
  `DELETE FROM resume_intake_progress WHERE session_id=$1 AND
  generation=$2`——该代曾达终态时残留的 seq=100 行会让新任务的终态 CAS
  永久回滚、mark 兜底同撞 PK，会话卡死在 queued。写入 B5 运维手册。
- **admin 响应 DTO（OpenAPI 可生成级，字段名与空值类型写死）**：
  `AdminOverviewResponse{users_total: int, logins_today: int,
  logins_7d: int, logins_30d: int, sessions_total: int,
  consult_turns_total: int, runs_total: int,
  tokens_by_day: [{date: str, total_tokens: int}],
  tokens_by_model: [{model: str, prompt_tokens: int|null,
  completion_tokens: int|null, total_tokens: int}]}`；
  `AdminUsersPageResponse{items: [AdminUserRow{user_id: str,
  email: str|null, created_at: datetime, last_login_at: datetime|null,
  session_count: int, resume_name: str|null, resume_phone: str|null,
  resume_school: str|null, resume_degree: str|null}], page: int,
  page_size: int(=20), has_more: bool}`；
  `AdminUserResumeResponse{user_id: str, session_id: str|null,
  resume_state: object|null}`（无简历 → null 字段，200 不 404）；
  admin explain 复用现有 explain DTO；不存在的 user/session/run → 404。
- 前端 `/admin` 轻 shell（入口仅 `me.is_admin` 可见）：Dashboard + 用户表
  + 简历详情抽屉 + 重置按钮；「评估（答辩）」「监控（答辩）」入口移入
  /admin（旧路径 Navigate 重定向）；用户侧 sidebar 移除两入口（R9）。
- **B5 配置与文档同步**：`.env.example` 与 `deploy/env.production.template`
  增 ADMIN_EMAILS；product_guide.md 评估/监控用户入口章节（现 :170 附近）
  改为 admin 入口说明；code_guide/deploy_guide 增管理端路由与部署段。

### 5.4 简历联系人结构化

- `resume_state.contact = {name, phone, email, evidence_span_ids}`
  （additive）。落点全列：app/state/schema.py ResumeState 增字段、
  resume_intake.py SYSTEM_PROMPT JSON shape 增 contact 段、LLMResumePayload
  增字段、**逐字段 extractive 验证（name/phone/email 各自逐字命中所引
  span，否则该字段置空；不用身份锚点回退）**、tests/test_resume_intake.py
  新增用例。用户侧 preview 维持脱敏；admin 端点原样返回。

### 5.5 B3/B4/B5 测试清单

- B5：test_monitoring_api（匿名用例按新序重写）、test_auth_sessions
  （登录 SQL 改写 → fake DB 匹配更新，L101-140/198-223）、test_auth_api、
  test_auth_ownership（admin 端点矩阵 + 即时撤权：白名单移除后下一请求
  403）、admin API 新测试（reset 三态语义、admin explain 跨用户、R9 双端
  断言：用户 sidebar 无两入口 / admin 可见）、contact 验证、usage 双
  executor + checkpoint 断言。
- B3/B4：见 §3.1/§4 各自清单。

## 6. 锁定契约兼容清单

1. Feature A 自 resume_ready 起不变；四开关矩阵预期不改（新增状态由 B2
   无条件前置拦截，基线状态行为逐字节一致）。
2. 409 Literal 只加值（resume_unparsed/resume_parse_limit）+ 415/422 新
   detail；`_RESUME_LIFECYCLE_DETAILS` 同步增补；`resume_missing` 仍仅
   API 层抛。
3. consult 契约与 §3.3 存活子串不动。
4. G17/G18 语义不变。G17＝"解析失败 → 明确要求重传，不复活旧档案"
   （权威源见头部锚点表）：B2 的限额与返还**不触碰** resume_error →
   重传这条路径本身；"resume_error 留 flag 门控"条款关乎 consult 可达性、
   与 G17（重传要求）无涉。
5. `-m app.serve`、Semaphore、无状态沿用；in-flight 字节与任务同实例，
   不跨实例寻址。
6. 每批 OpenAPI 快照 + generated.ts + apiFixtures 再生。
7. to_thread 按宪法裁决条款执行（AGENTS.md §2.2）。
8. consult/match-brief 落库保护是新增防御；基线状态转移不变。

## 7. 部署与迁移

- 常规批：四门 → commit → 打包 → scp → 解包 → 迁移（0009/0010/0011 批）→
  restart → curl 健康检查。
- **B2 部署顺序（写死）**：
  ① 后端先行：解包 app → migrate → `systemctl restart career-rag` →
     curl capabilities；此窗口＝旧前端×新后端，已验证无害（upload 200 被
     旧端忽略，preview 收到未知 409 `resume_unparsed` 后回落上传入口，
     零 LLM 零崩溃）；**杜绝反向窗口**（新前端×旧后端会绕过确认自动烧
     LLM）——前端必须后于后端；
  ② 前端版本目录 + 符号链接切换：解包到
     `/opt/career-rag/releases/frontend-<版本>` →
     `ln -sfn <目录> /opt/career-rag/current.tmp && mv -Tf
     /opt/career-rag/current.tmp /opt/career-rag/frontend-current`
     （绝对路径、同文件系统保 rename(2) 原子；`-f` 使中断残留的
     current.tmp 可幂等覆盖；Caddy v2 file_server 默认跟随 symlink 并按
     请求解析，翻链即时生效）；Caddyfile root 改指 `frontend-current`
     （B2 批一并改，含 index.html `Cache-Control: no-store`）；
  ③ `caddy validate --config /etc/caddy/Caddyfile` →
     `systemctl reload caddy`（仅因 Caddyfile 本身变更）；
  ④ 已打开的旧标签页刷新即恢复（已接受残留）。
  首次切换 bootstrap 与全新安装布局写入 deploy_guide.md（§1.3 文档同步）。
  B2 服务器 env 增 `RESUME_PARSE_LIMIT=3`（写入两份 env 模板）。
- B4：`pip install -r requirements.txt` + env（QWEN_VL_MODEL、
  VL_MAX_CONCURRENCY、RESUME_OCR_ENABLED、RESUME_OCR_PAGE_MIN_CHARS、
  RESUME_OCR_MAX_PAGES、RESUME_OCR_MAX_PIXELS、RESUME_OCR_RENDER_SCALE、
  RESUME_OCR_MAX_IMAGE_PIXELS_DECODE）。
- B5：env 增 ADMIN_EMAILS；用户邮箱重登获权。

## 8. 风险与回滚

- B1/B3/B4/B5：回滚＝部署上一包（0010/0011 additive，留表无害）。
- **B2 回滚诚实条款**：B2 改变了待解析数据的存放（BYTEA）与状态机，
  **前滚修复优先**；若必须回滚到旧包，流程顺序写死（消除"脚本提交后
  在途请求再写出新状态"的并发窗口）：
  ① **先停服**：`systemctl stop career-rag`（用 stop 而非 kill，规避
     unit 的 Restart=always；停服后无任何写入方，Caddy 对 API 短暂 502
     属回滚场景可接受）；
  ② 执行状态迁移脚本：`sudo -u postgres psql -d career_rag
     -v ON_ERROR_STOP=1 -f /opt/career-rag/deploy/rollback_b2.sql`——
     脚本内容（单事务）：`BEGIN; UPDATE session_state SET
     status='awaiting_resume' WHERE status IN
     ('resume_uploaded','resume_queued'); DELETE FROM resume_uploads;
     COMMIT;`（**含 resume_queued**——停服完成后该状态无人认领；
     两方评审独立确认）；
  ③ 换回旧 app 包 + 旧前端（symlink 翻回旧 release）；
  ④ `systemctl start career-rag` 恢复流量。
  0009 表保留无害。脚本随 B2 批入库 `deploy/rollback_b2.sql`。
- OCR 成本闸：确认制 + 解析限额 + VL Semaphore + 页数/像素/解码防炸/
  base64 上限。
- 返还偏置只向用户（GREATEST + CHECK 双下限；reset 交错上界 1/任务）。
- 遥测 fail-open；ADMIN_EMAILS 空 → /admin 全 403，主线无影响。
- 进度孤儿行无害且有界：**每个已启动旧代 ≤ 其非终态事件数（≤99，常态
  个位数）**，新任务首事件事务按 `generation < $2` 清理旧代；跳页说明
  合并为**单条汇总事件**（§4），常态每代总行数 ≤10。

## 9. 流程

方案三方全 PASS 才动代码；每批四门 + 对侧抽查；全部批次完成后三方对全量
diff 查 bug（正确性/契约/并发/安全/回归），修复回审至三方干净。

## 10-11. 历史意见处置

五轮评审历史意见（v1 23 条、二轮 22 组、三轮 20 组、四轮 20 组）的处置
对照表见 v2.3（git 3368613）§12 及本文件修订史；全部已并入本版正文。

## 12. 第五轮意见处置（v2.4）

| 来源 | 意见 | 处置 |
|---|---|---|
| Codex B1 | "同 v2.2"引用不可恢复、git 历史缺失 | 本版全文自包含，无任何外部引用；修订史声明如实（v1-v2.2 为草稿未入库） |
| Codex M1 | §0 治理条款自相矛盾 | 裁决已落地（de88946），§0 改为裁决记录；顺序与门控矛盾随之消除 |
| Codex M2 | consult 保护接口不可实现 | §1.2 三件契约扩展写死（穿参 locked.status、mutator 覆写 status、flag-off 换 loader）（子 agent 五审 M 级同源） |
| Codex M3 | mark_resume_error 无既有事务；孤儿终态事件 | §1.2 改为单事务 UPDATE…RETURNING 命中后 INSERT；miss 全 no-op + 回滚测试 |
| Codex M4 | reset 会销毁合法待解析上传 | §5.3 三态语义：仅 queued 遗留才清理，uploaded 保留 |
| Codex M5 | progress API 无 DTO | §3.1 ResumeProgressResponse 完整契约（当前代/排序/空态/done/停轮询） |
| Codex M6 | Pillow MAX_IMAGE_PIXELS 40-80M 不拦 | §4 显式尺寸乘积检查 + 40_000_001 边界测试 |
| Codex M7 | B4 oracle 分支缺口 | §4 三分支断言（q70 过/ q50 过/双超跳页不调 VL） |
| 子 agent M | mutate 契约三件 | §1.2（与 Codex M2 合并） |
| 子 agent m1 | version 比对门控归属 | §1.2 match-brief 条款写死 |
| 子 agent m2 | ln -sfn 非原子 | §7 ln -sn + mv -Tf（rename 真原子） |
| 子 agent m3 | deploy_guide 全新安装矛盾/bootstrap | §1.3 文档同步扩围 + §7 bootstrap |
| 子 agent m4 | B2 返工敞口半句 | 裁决为"允许"，条款已闭（无需保留敞口） |

## 13. 第六轮意见处置（v2.5）

| 来源 | 意见 | 处置 |
|---|---|---|
| Codex B1 | 保留型约束未内联 | 头部「规范性引用原则」裁定：权威源＝代码+钉死测试（防双源漂移），锚点已给全；不复制字面值 |
| Codex M1 | mutator 协议/状态名简写 | §1.2 MutationOutcome{result, status_override: KEEP/None/str} + 全名 |
| Codex M2 | 解析中重传致进度永久轮询 | §3.1 done=status!='resume_queued' + 前端 generation 变化即停 + 交错测试 |
| Codex M3 | terminal_event 字段/seq/幂等 | §1.2 TerminalEvent 类型 + seq 1..99/终态=100 保留段 + 冲突不可达论证 |
| Codex M4 | parse/admin DTO 缺失 | §1.3 复用 ResumeAcceptedResponse；§5.3 四个 Admin DTO 逐字段 + 404/空态 |
| Codex M5 | 图片上传阶段边界 | §4 上传零 VL、尺寸检查、固定 preview、422 不适用图片 |
| Codex M6 | 回滚声明不成立 | §8 B2 前滚优先 + rollback_b2.sql 状态迁移脚本 |
| Codex M7 | B4/B5 env/文档同步缺口 | §4/§5.3 同步条款（含 product_guide :170 冲突处） |
| Codex m1 | current.tmp 相对路径/残留 | §7 绝对路径 + ln -sfn 幂等（子 agent nit 同源） |
| Codex m2 | 40M 接受边界/调用次数 | §4 双边界 + VL 调用次数与 payload 断言 |
| Codex m3 | 未上传 generation 语义 | §3.1 列值 0 → null |
| 子 agent m6-1 | 自包含声明字面矛盾 | 头部措辞改为"正文自包含 + 唯一非规范性指针" |
| 子 agent m6-2 | 终态 CAS 漏 session_id | §1.2 WHERE 补全 |
| 子 agent m6-3 | PUBLic_PATHS 笔误 | §1.5 改正 |
| 子 agent nit | reset 三态显式/RESUME_PARSE_LIMIT 入 env | §5.3 ③ 显式 + §7 B2 env |

## 14. 第七轮意见处置（v2.6）

| 来源 | 意见 | 处置 |
|---|---|---|
| Codex B1 | 四个锚点虚设（词表双源冲突/clarify 键行号偏/phase·120·80 无测试/G17 映射错） | 头部锚点表全面核正：裁定咨询词表与岗位聚类词表为两个集合（consult_engine.py:50 为咨询侧权威）；clarify 键改 :100-101；phase/120/80 给定义源 + B3 契约钉死快照测试补齐缺失权威（§3.1）；§6.4 G17 措辞修正 |
| Codex M1 / 子 m1 | 回滚漏 resume_queued（两方独立同发现） | §8 脚本 IN 双态 + 单事务 + ON_ERROR_STOP |
| Codex m1 / 子 nit1 | 孤儿行上界表述失真/跳页事件可击穿 ≤10 | §8 上界改"每旧代 ≤ 非终态数"；§4 跳页合并单条汇总事件 |
| Codex m2 | Admin DTO 字段名/空值类型 | §5.3 逐字段类型与 nullable 写死 |
| 子 nit2 | 引用原则 120/80 自张力 | 头部原则加"钉死测试短子串可内联"豁免 |
| 子 nit3 | owner_user_id 指代歧义 | §5.1 改"begin 步骤①" |

## 15. 第八轮意见处置（v2.7）

| 来源 | 意见 | 处置 |
|---|---|---|
| Codex M1 | 回滚存在并发写回窗口（脚本提交后在途请求再造新状态） | §8 流程写死：stop 服务 → 脚本 → 换包 → start（含 Restart=always 规避说明） |
| Codex m1 | §3.1 旧上界残留 | §3.1 两处对齐：孤儿上界=该代非终态数；协议硬上界 ≤100（含终态 seq=100） |
| Codex m2 / 子 nit | §3.3 旧行号 94-99/479 残留 | §3.3 锚点同步：JSON 键=112-121、clarify 键=100-101、词表全集=B3 快照 |
| Codex m3 | phase 第三处 DTO（schemas.py:241）未列 | 头部锚点表补 :241 + B3 快照覆盖三处 DTO 一致性 |
| Codex nit | psql 命令缺 -f 参数 | §8 ② 完整命令写死 |

> 工程事故记录（2026-08-08）：v2.7 首次提交（4b49e3d）因 PowerShell
> 未带 -Encoding utf8 读写本文件导致全文乱码，已从 git 恢复 v2.6 并以
> Edit 工具重放全部修订；此后本文件的任何修改禁止经由 shell 文本管道。
