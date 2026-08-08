# v3 产品迭代方案（修订稿 v2.3 · 2026-08-08 · 自包含终审稿）

> 修订记录：v1→v2→v2.1→v2.2 四轮三方评审逐轮收敛（历史意见 60+ 条全部处置；
> 四轮子 agent 已 PASS，Codex 第四轮残留 2B/12M/4m 于本版全部处置，见 §12）。
> 本版**自包含**：所有表结构/契约/回滚不再引用历史版本。本文件随本版起纳入
> git 跟踪。
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

顺序 **B2 → B1 → B3 → B4 → B5**；迁移 B2=0009、B3=0010、B5=0011。

**R4 口径**：限额按解析次数（`RESUME_PARSE_LIMIT=3`）；重传不耗额度；外部
调用发起前失败不耗额度。**R1 裁减**：纯扫描 DOCX 引导转 PDF/图片重传。

**待用户裁决（仅门控 B4）**：`asyncio.to_thread` 用于卸载阻塞的光栅化/文件
提取，是否属于"禁 threading"硬约束的例外。事实：仓库现行代码已用
（resume_intake.py:689-691）且特征测试强制要求（test_resume_intake.py:232）；
Codex 评审认为历史实现不构成规则豁免，须宪法所有者（用户）一句话裁决并
写入 AGENTS.md/CLAUDE_LANGGRAPH.md。**裁决前 B4 不开工；B2/B1/B3/B5 不受
影响**（B2 上传提取沿用现行 intake 的既有 to_thread 边界，属存量行为）。

## 1. B2 上传确认流 + 解析限额

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

同步 schema.sql。上传不落磁盘；10MB 上限以流式读入内存缓冲、超限 413 在新
持久化函数内重写（persist_upload/unlink 移除，test_uploads.py 整文件重写）。
**上传时提取契约**：POST 内经现行 intake 同款 to_thread 边界执行本地提取
（存量行为）；文件损坏/不可解析 → **422 `unreadable_file`**（新 detail，
不入库不扣额度）。**intake 输入契约**：intake_resume/extract_resume_text 增
`bytes + suffix` 重载；CLI 保留 Path 适配。

### 1.2 状态机与原子操作

```
awaiting_resume → resume_uploaded → resume_queued → resume_ready / resume_error
```

- `accept_resume_upload`（单事务）：
  ① `UPDATE session_state SET resume_upload_generation =
     resume_upload_generation + 1, status='resume_uploaded',
     confirmed_resume_version=NULL, resume_confirmed_at=NULL
     WHERE session_id=$1 RETURNING resume_upload_generation`；
  ② `DELETE FROM resume_uploads WHERE session_id=$1`；③ INSERT。
- `begin_resume_parse(session_id, generation, max)`（单事务）：
  ① `SELECT status, resume_upload_generation, resume_parse_count,
     owner_user_id FROM session_state WHERE session_id=$1 FOR UPDATE`
     （owner_user_id 于此步取得，供 usage 归因；无行→404）；
  ② 锁内分类，优先级 `parse_limit ＞ resume_changed ＞ resume_processing
     ＞ resume_unparsed`；
  ③ `UPDATE session_state SET status='resume_queued',
     resume_parse_count = resume_parse_count + 1 WHERE session_id=$1`；
  ④ 同事务 `SELECT ... FROM resume_uploads WHERE session_id=$1 AND
     generation=$2`，字节入内存传 BackgroundTask（行缺失→回滚
     resume_changed）。四轮已证锁序安全、双击单扣。
- `save_normalized_resume`/`mark_resume_error`：前置
  `resume_upload_generation=$n AND status='resume_queued'`；**两函数各增
  可选 `terminal_event` 参数，在其自身既有事务内先 INSERT 进度终态事件、
  再 UPDATE 状态**（跨层同事务的唯一可行机制；进度回调不落终态事件，
  仅承载信息，见 §3.1）。
- **返还**：`_normalize_resume` 单 try/finally 结构内维护 `external_started`
  标记（进度阶段 normalizing/ocr 置位=首个外呼即将发起）；失败且未置位 →
  `UPDATE session_state SET resume_parse_count =
  GREATEST(resume_parse_count - 1, 0) WHERE session_id=$1`（无 generation
  谓词；扣费先于任务启动已提交，归纳可证正常运行不触 GREATEST 下限；
  每任务≤1 次返还是单 finally 的结构保证）。admin 重置与在途任务交错可多
  还 1 次（上界 1/任务，偏向用户，已接受）。restart 丢任务烧 1 次，救济
  见 §5.3 重置端点（会一并解锁状态）。
- 清理：任务 finally `UPDATE resume_uploads SET content=NULL,
  extracted_text=NULL WHERE session_id=$1 AND generation=$2`
  （**清理范围＝上传原件与临时提取副本**；resume_state 的
  original_evidence_spans/normalized_base_resume 属产品功能数据，保留）。
- `_RESUME_LIFECYCLE_DETAILS` 增 `resume_unparsed`、`resume_parse_limit`。
- **生命周期无条件保护（与 clarify flag 解耦）**：
  - consult/finalize 端点前置：`resume_uploaded`→409 unparsed、
    `resume_queued`→409 processing（无条件）；`resume_error` 留 flag 门控。
  - **consult 落库保护以 generation 为准**：consult 读取 state 时记录
    generation；落库在 `mutate_state_atomically` **行锁内**比对
    `locked.generation != loaded_generation` **或** `locked.status ∈
    {uploaded, queued}` → `status=None` 只追加 transcript 不写状态
    （status=None 写路径已存在，coach CAS2 在用）。双 flag 配置各测一遍。
  - **match-brief 同保护**：其状态写入同样带无条件 generation CAS
    （flag-off 也生效），失配 → 409 resume_changed，杜绝
    `match_brief_approved` 覆盖新生命周期。

### 1.3 API 契约

- `POST /sessions/{id}/resume`（202→200，require_owned_session）→
  `ResumeUploadedResponse{generation, filename, pages, chars,
  text_preview(≤600字·脱敏), parses_used, parses_limit, ocr_suggested}`；
  415 `unsupported_file_type`；422 `unreadable_file`。
- `GET /sessions/{id}/resume-upload`（require_owned_session）：仅
  `status='resume_uploaded'` 返回元数据，否则 404。
- `POST /sessions/{id}/resume/parse`（require_owned_session，202）：
  **请求 DTO `ResumeParseRequest{generation: int}`**——必须回传预览时拿到
  的 generation（旧标签页解析未预览的新代 → 409 resume_changed）。
- `resume-preview`/`resume-confirm` 在 uploaded 态 → 409 `resume_unparsed`。
- OpenAPI 快照 + generated.ts + apiFixtures 同批再生。**文档同步（B2 批）**：
  project_functionality_and_code_guide.md、code_guide.md、product_guide.md、
  deploy_guide.md 的上传/解析章节。

### 1.4 前端

同 v2.2：composer 回形针 → 用户气泡确认上传 → 小意预览气泡（parses 计数 +
ocr 提示）→ 确认解析 → 轮询；GET resume-upload 刷新恢复；reset effect 覆盖
两 mutation；旧 input 收敛；PM 欢迎语/占位符同批改；limit 态禁用 +
「新建会话继续」CTA + "会话额度也满时联系管理员重置"。

### 1.5 测试

v2.2 清单全部保留（lifecycle L233/263/425/819、PUBLIC_PATHS、test_uploads
整文件、phase_e:583、auth_ownership +2 端点、config RESUME_PARSE_LIMIT、
WorkbenchPage 六用例、apiFixtures、e2e/full-flow；三时序交错、重传竞态返还、
重复返还不可能、外呼后不返还、415/422、刷新恢复、双清、flag=false 下
uploaded/queued 409、consult 等待期 upload 不覆盖状态、限额后新会话），另增：
**parse DTO 回传旧 generation → 409**；**match-brief flag-off 并发上传 →
409 resume_changed**；confirm uploaded→resume_unparsed；GET resume-upload
非 uploaded→404。原样回归：四开关矩阵、clarification api/engine、
intent_consultation、api_concurrency、e2e/mobile。

## 2. B1 前端体验包（同 v2.2 全文保留）

R7 首访流（回读兜底 + 内存旗标 + 失败直达 /login）；R5 stagger（新增消息
i*450ms，PM→600ms→小意，reduced-motion 即时）；R3 折叠 details；R8 三档
宽度检查项 + 截图验收。

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

- 首事件事务：`DELETE ... WHERE session_id=$1 AND generation < $2` + 守卫
  INSERT；每条 INSERT 带 `WHERE EXISTS(... generation=$2 AND
  status='resume_queued')`；孤儿行无害有界（如实表述）。
- **终态事件归属（歧义消除）**：done/error 事件**由
  save_normalized_resume/mark_resume_error 经 terminal_event 参数在自身
  事务内写入**（§1.2）；intake 回调只发非终态事件（received/extracted/
  normalizing/ocr/validated），并为 §1.2 阶段标记提供信息。
- `GET /sessions/{id}/resume-progress`（require_owned_session）。
- 测试：回调序列；DELETE 代数谓词交错；终态事件与翻转同 tx；所有权；
  **前端 1200ms 轮询渲染、逐行动画 + reduced-motion、§3.3 存活子串快照**
  （B3 测试清单补齐）。

### 3.2 档案逐行（前端动画，同 v2.2）。

### 3.3 小意人设（同 v2.2：语气段扩写 + 存活子串清单逐字保留 + 120/80/
phase/retry 不动 + 欢迎语热情化）。

## 4. B4 视觉 OCR 兜底（**开工前置：§0 to_thread 裁决**）

- `qwen_vl.py`（DashScope OpenAI 兼容，QWEN_VL_MODEL=qwen-vl-ocr 首日冒烟，
  Semaphore(VL_MAX_CONCURRENCY=2)）。
- 提取契约页级重构 `[(page_no, text)]`。
- PDF：页文本 < RESUME_OCR_PAGE_MIN_CHARS(50) → 读 mediabox，
  `scale = min(RESUME_OCR_RENDER_SCALE(2.0),
  sqrt(RESUME_OCR_MAX_PIXELS(4_000_000)/(w*h)))` 光栅化 → JPEG → base64
  ≤10MB（超限降质重试一次 q70→q50，仍超 → 跳过该页 + 进度事件说明，
  不硬失败）→ OCR。**合并＝按页替换**，页序不变；`RESUME_OCR_MAX_PAGES(6)`
  只限 OCR 页数，之后的页保留原生文本。
- 图片：**解码级防炸**——`Image.MAX_IMAGE_PIXELS =
  RESUME_OCR_MAX_IMAGE_PIXELS_DECODE(40_000_000)`（超限 422/resume_error
  硬拒绝）+ JPEG draft 解码降采样 → 归一化到 MAX_PIXELS → 同管线。
- DOCX：无文本 → resume_error + 转 PDF/图片引导。
- 终止：无可用 evidence span → resume_error（G17）。
- 依赖入 requirements.txt；**前端**：accept 放开图片 + ocr 提示（前后端批）。
- 测试：混合 PDF 按页替换；**MAX_PAGES 截断后原生文本页保留**（oracle 与
  正文对齐）；base64 降质重试→跳页链路；解码防炸硬拒绝；scale 收敛内存
  有界；VL Semaphore；docx 引导；开关关闭逐字节等价；无 span→error；
  前端图片全流程。

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

### 5.1 计量

- 两表均 **await 写入 + fail-open**。`usage_scope` 任务体内设置：
  `_normalize_resume`（owner_user_id 来自 §1.2 步骤①；normalize/嵌套 ocr）、
  consult（consult）、coach（coach）、**run 统一包装器
  `_run_with_usage_scope(executor_call)`——透传 executor 既有全部参数与
  注入（含 LangGraph checkpointer，runs.py:68-74 的注入原样保留），仅额外
  包 scope，覆盖经典与 LangGraph 两支**、case_base（case_embed）。
- 记录在客户端内部：deepseek.chat、qwen_embed（**embed_one 直接复用
  embed_texts 时只在最内层 provider 请求处写一行，杜绝重复计量**；LRU
  命中零行）、reranker（仅 total）、qwen_vl。签名不变。
- 测试：双 executor 归因带 session_id/user_id 且 **checkpointer 仍生效
  （checkpoint 写入断言）**；嵌套 scope；fail-open；缓存零行；单请求单行。

### 5.2 管理员鉴权（同 v2.2：require_admin 无条件 fail-closed + 每请求实时
白名单 + 登录同步列 + trim/casefold/去重 + phone 恒非 admin；monitoring
先 flag 404 后 require_admin，匿名用例重写）。

### 5.3 管理端

- overview / users?page（最新简历定序 `resume_confirmed_at DESC NULLS LAST,
  resume_version DESC, session_id`，全空显示"未上传"）/ users/{id}/resume
  （不脱敏）/ `GET /admin/runs/{run_id}/explain`（require_admin 跨用户，
  复用 explain DTO）。
- `POST /admin/sessions/{id}/reset-parse-count`（require_admin）：**语义
  扩展**——重置计数 + 若 status='resume_queued'（restart 遗留）则置
  resume_error + 清该会话 resume_uploads 的 content/extracted_text
  （限额死局与 restart 遗留的统一救济，兼隐私清理）。
- 前端 /admin shell + 用户表 + 简历抽屉 + 重置按钮；评估/监控入口迁移 +
  旧路径重定向；用户侧移除（R9）。

### 5.4 联系人结构化（同 v2.2：contact 字段 + 逐字段 extractive 验证 +
落点全列 + 用户侧脱敏/admin 原样）。

### 5.5 测试（同 v2.2 清单，另加：即时撤权矩阵、reset 端点三重语义、
admin explain 跨用户、R9 双端断言、confirm/GET/定序/空态精确用例）。

## 6. 锁定契约兼容清单

1. Feature A 自 resume_ready 起不变；四开关矩阵预期不改。
2. 409 Literal 只加值（unparsed/parse_limit）+ 415/422 新 detail；
   `_RESUME_LIFECYCLE_DETAILS` 同步。
3. consult 契约与存活子串不动。4. G17/G18 不变。
5. `-m app.serve`、Semaphore、无状态沿用；in-flight 字节与任务同实例。
6. 每批快照/类型/fixtures 再生。7. to_thread 事项按 §0 裁决条款执行。
8. consult/match-brief 落库保护是新增防御，基线状态转移不变。

## 7. 部署与迁移

- 常规批：四门 → commit → 打包 → scp → 解包 → 迁移 → restart → 健康检查。
- **B2 部署顺序**：① 后端先行（解包 app → migrate → restart → curl 健康；
  旧前端×新后端已验证无害：upload 200 被忽略，preview 收到未知 409 回落
  上传入口，零 LLM）；② **前端版本目录 + 符号链接原子切换**：解包到
  `/opt/career-rag/releases/frontend-<版本>` → `ln -sfn` 切
  `/opt/career-rag/frontend-current`（Caddyfile root 改指 frontend-current，
  B2 批一并改；rename 原子、无空窗、可回切、无 .old 残留问题）；
  ③ `caddy validate` → `systemctl reload caddy`（index.html no-store 生效）；
  ④ 旧标签页刷新恢复（已接受残留）。
- B4：pip install -r + env（VL/OCR 全套）；B5：env ADMIN_EMAILS。

## 8. 风险与回滚

- 每批独立 commit/包；0009-0011 additive，回滚=上一包 + 表保留。
- OCR 闸：确认制+限额+Semaphore+页数/像素/解码防炸/base64 上限。
- 返还偏置只向用户（GREATEST+CHECK 双下限；reset 交错上界 1/任务）。
- 遥测 fail-open；ADMIN_EMAILS 空→全 403。

## 9. 流程

方案三方全 PASS 才动代码；每批四门+对侧抽查；全部批次后三方全量 diff
查 bug 至干净。

## 10-11. 历史处置

v1 23 条、二轮 22 组、三轮 20 组意见的处置对照表见本文件 git 历史
（v2/v2.1/v2.2 版）；本文件自 v2.3 起入库跟踪。

## 12. 第四轮意见处置（v2.3）

| 来源 | 意见 | 处置 |
|---|---|---|
| Codex B1 | to_thread 违宪 | §0 用户裁决条款（仅门控 B4；B2 提取属存量行为） |
| Codex B2 | 文档不自包含/未入库 | 本版 DDL 全部内联 + 文件入 git |
| Codex M1 | CHECK 简写无效 SQL | §1.1 全表达式 |
| Codex M2 | parse 无 DTO | §1.3 ResumeParseRequest{generation} + 旧标签页 409 测试 |
| Codex M3 | consult 保护应以 generation 为准 | §1.2 行锁内 generation 比对 ∨ 状态判定 |
| Codex M4 | match-brief 同类竞态 | §1.2 无条件 generation CAS + 测试 |
| Codex M5 | 终态事件事务归属矛盾 | §1.2/§3.1 terminal_event 参数、回调不落终态（子 agent 建议 1 同源） |
| Codex M6 | restart 遗留无救济/PII | §5.3 reset 端点三重语义（计数+解锁+清理） |
| Codex M7 | 包装器丢 checkpointer | §5.1 透传全部注入 + checkpoint 断言 |
| Codex M8 | mv 两步有空窗/.old 残留 | §7 releases 目录 + symlink 原子切换 + Caddy root 改 |
| Codex M9 | 上传提取执行契约缺失 | §1.1 to_thread 存量边界 + 422 unreadable_file |
| Codex M10 | 图片解码炸弹 | §4 MAX_IMAGE_PIXELS_DECODE 硬拒 + draft 降采样 |
| Codex M11 | B3 测试缺前端项 | §3.1 补齐 |
| Codex M12 | B4 oracle 与正文不闭合 | §4 测试与正文逐条对齐（降质重试→跳页） |
| Codex m1 | 精确测试未列 | §1.5/§5.5 |
| Codex m2 | 文档同步范围 | §1.3 四份文档点名 |
| Codex m3 | embed 重复计量 | §5.1 最内层单行 |
| Codex m4 | 隐私表述过宽 | §1.2 限定清理范围 |
| 子 agent 建议 2 | 保护条件评估位置 | §1.2 行锁内 + 双 flag 测试 |
| 子 agent 建议 3 | owner_user_id 来源 | §1.2 步骤①（§5.1 同步改） |
| 子 agent 建议 4/5 | reset 交错偏置/单 finally | §1.2/§8 |
