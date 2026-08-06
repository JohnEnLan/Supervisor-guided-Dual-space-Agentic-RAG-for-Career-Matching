# 生产增强方案：简历澄清回路 + PM 常驻督导（v10 终稿 — 六轮三方评审收敛，双 APPROVE）

> v1 → v2：子 agent（6 项）与 Codex（8 项）双路评审均 NEEDS_CHANGES，意见深度
> 收敛。v2 核心修正：①PM 消息**不进转录顶层**——改为 turn 条目内嵌
> `supervisor_notes`（DTO extra=forbid 三重炸点、React key 冲突、最近四轮切片
> 挤占、avoid-role 误扫全部消解）；②澄清证据的**数据归属铁律**（原话逐字、
> 服务端定 ID、LLM 只出 summary）；③确认基线不可变 + 三个统一消费 helper；
> ④阶段机锁定"槽位先行"；⑤跳过机制确定性白名单先行；⑥PM 预算的并发安全与
> fail-open；⑦"逐字节一致"改"运行时行为等价"+ 四组合测试；⑧工期上修 8–10 天
> （附砍参压缩版）。宪法结论修正措辞：V2 §5 已授权图外咨询 8/15 轮，无需修宪。
>
> v3 → v4（Codex 二审 3 阻断 + 4 高危 + 3 次要全并入）：①回答归属改
> **pending question 锚点制**（只处理上一轮实际问过的 target，杜绝模板回答
> 误挂简历证据）；②教练预算改 **reservation 状态机**（coach_attempt_id +
> reserved/succeeded/unavailable，消解"从已持久化 notes 计数"与"调用前预留"
> 的自相矛盾）；③定稿 PM note 只抑制重复文案、**永不隐藏「生成确认单」CTA**；
> ④POST 返回时序与滚动锚点写死；⑤finalize 隐式 skip 的持久化落点 +
> /match-brief 兜底；⑥消费者列账精确到函数（含召回 query builder）；
> ⑦换简历竞态加 generation guard；⑧chips 口径 answered/skipped/remaining；
> ⑨P0 锁定三触发全版。工期 9–11 天。
>
> v4 → v5（子 agent 三审收口）：V1 **跨轮 stale-working 覆盖竞态**——
> persist_turn 对 transcript 整表覆盖 + CAS2 不推进 rounds_used，多 tab 下
> note/reservation 可被静默抹掉 → 定义按 coach_attempt_id 的并集合并 +
> reservation 状态单调不可逆退 + 竞态测试；V2 generation guard 需 state_store
> 锁内暴露 resume_version（内部 API 变更列账）；V3 跳过判定"混有实质内容"
> 写死确定性规则（剥白名单短语后残余 < N 字符判 skip）；V4 转换类触发改
> 状态判定防饿死、行号勘误。
>
> v5 → v6（Codex 三审 2 阻断 + 4 高危）：①generation guard 改**一致快照制**
> （load_consult_context 单查询取 state+版本；版本冲突改 409 resume_changed，
> 整轮不落库不推进 round——旧 target 生成的话术一并作废）；②finalize 与
> 在途回答竞态——发问/回答 CAS 追加 pending 身份核对，pending 被清/target
> 终态即 409 不得复活，前端 turn.isPending 时禁用 finalize CTA；③CAS2 并发
> 前提逐字写死（不等值 round、身份匹配即可、单调、幂等 no-op、原位更新）；
> ④轮内处理顺序锁定（skip→改 state→重算 phase→再生成）；停滞排除改按
> pending_at_round_start 判定；⑤持久化 schema 补全（targets 状态表 +
> questions_used 归 ResumeState；coach_reservations 归顶层；重传简历重置
> A 组字段但不重置教练预算）；⑥**隐式空间隐私边界**：raw_answer 不进
> build_implicit_query_text，隐式 query 只可消费去标识化摘要（新增隐私
> 测试）。
>
> v6 → v7（子 agent 四审单点收口）：V6-1 **隐式空间 P0 零消费澄清内容**
> ——"去标识化摘要"是断言不是机制（token 子集校验保忠实性，人名原词
> 恰好通过），删减而非增补：信号增强与"澄清进 user_profiles"同批移 P1，
> 隐私测试升格"澄清任何内容不进 implicit query"；V6-2 409/抽取失败边界
> 判据 + 409 范围限定（纯 template/deepen 轮不拦截）+ 隐式信号可空取舍
> 声明 + summary 抽取式指令；V6-3 pending 身份键 target_ref+asked_round、
> 409 detail 契约列账、工期措辞如实、行号勘误。
>
> v7 → v8（Codex 四审 2 阻断 + 1 高危）：①**上传 202 窗口**——上传受理即
> 原子写单调 resume_upload_generation（版本要到后台归一化成功才递增，只核
> version 会漏过窗口内旧回合）；②**撤回 v7 "纯轮免检"**——新简历重建
> targets 会改 determine_phase 与 finalizable 触发，澄清开关开启时所有咨询
> CAS 统一核 generation（409 恢复 UX 已定义，正确性优先）；③409 前端恢复
> 写死可实施规格（onError 分流/保输入/清 briefDraft/可见提示/双测试旅程）。
>
> v8 → v9（五审：子 agent **APPROVE** + 4 条编辑级落笔注全并入）：受理写 =
> 单条 UPDATE 不重写 state JSON（封"受理整写抹掉并发咨询轮"既有隐患）+
> 交错测试补条；§4 锁内暴露 +generation、新列迁移列账；工期如实 10–12d。
>
> v9 → v10（Codex 五审 1 阻断 + 1 高危：generation 生命周期收口）：
> ①**旧档案重确认洞**——resume_queued 期间 preview 仍返旧档案、confirm 仍
> 可把旧 v1 确认回去，重开刚封的 202 窗口 → preview 在 queued 期返回
> 409 resume_processing；confirm 锁内要求当前 generation 已完成且
> status=resume_ready；"要求已确认"契约限定**只约束咨询读取/CAS**（后台
> 提交只核 generation，否则受理清确认后后台永远无法成功——歧义消除）；
> ②过期后台任务规则：成功/失败写入都核 generation，过期任务安静 no-op
> 绝不覆盖新简历或错标 error；补两条测试。
>
> **六审（终轮）：子 agent APPROVE（5 条实施注）+ Codex APPROVE（4 条实施
> 注）——收敛达成。九条实施注全数收录 §10，不改变任何已裁决设计。**

## 0. 现状锚点（双审核验后修正版）

- 质量问题源头结构化（resume_intake.py:80-86）、`_validated_fact_items` 先丢
  无锚点条目（:303-304，**留存者必带 evidence_span_ids**——对触发器有利）、
  `_normalize_quality_issues` 压平（:253）；severity 是 LLM 自由文本，
  结构化入库时**必须枚举归一**（low/medium/high 白名单，异常归 medium）；
- 转录条目 = "整轮"（user_message+assistant_reply 必填、reply≤120/question≤80、
  DTO `extra="forbid"`，schemas.py:150-155）——**任何顶层新条目/新键都会让
  GET /consult 500**（v1 的最大盲点）；
- `_ConsultLLMResponse` 为 `extra="ignore"` + 两次尝试（非 v1 所称"严格 schema"，
  措辞修正）；`build_consult_user_prompt` 取**最后 4 条 entry** 做上下文；
- `save_normalized_resume` 版本+1 且清确认（state_store.py:142-145）；
  P0 回填走 `mutate_state_atomically` 不触碰版本列；
- **咨询 CAS 持久化白名单只复制 `_INTENT_CAREER_FIELDS`**（sessions.py:69）——
  working 副本上的 ResumeState 改动与 supervisor_log 追加**默认会丢**，
  本方案必须显式扩展 CAS mutator 的合并面（见 §1.3/§2.2）；
- Supervisor 咨询期空白属实；宪法裁决（双审一致）：CLAUDE_LANGGRAPH.md §5
  已授权图外咨询 8/15 轮且与图内计数不混算——**本方案合宪，无需修宪**；
- v3.2 前端已有 can_finalize 时的 PM 卡（WorkbenchPage.tsx:446-455）——
  定稿时刻存在三重发声风险，需抑制规则（§3）。

## 1. Feature A：简历澄清回路

### 1.1 触发（确定性）
归一化后计算 `clarification_targets`：
1. 结构化 quality_issues 保留入库（新字段 `resume_state.quality_issues_struct`，
   severity 枚举归一），取 `severity ∈ {medium, high}`，**high → medium 排序**；
2. 确定性补充检测：experience 缺职责/成果描述（字段空或 < N 字符）、
   项目无技能关联；**时间断档检测移入 P1**（dates 为自由文本，全仓无日期
   解析器，独立成本 0.5–1d——砍参项）；
3. 选取 **top `RESUME_CLARIFY_MAX`（默认 2，Field 1..5）** 个为本次 targets；
   `clarification_progress.total = 选中数`（非全部检测数）；同一段经历不连问
   两次（target 去重键 = 字段路径）。

### 1.2 阶段机（锁定"槽位先行"，消除 v1 自相矛盾）
```
三槽未齐                          → template
三槽已齐 且 存在未结 targets       → resume_clarify
targets 完成/跳过/达上限           → deepen / explore（原逻辑）
```
- `determine_phase` **签名变更列账**：需接收澄清上下文（改为接收 SharedState
  或新增 context 参数——现签名只见 CareerState，看不到 targets）；
- `can_finalize` 保持纯槽位制**不等待澄清**；**finalize = 隐式 skip 剩余
  targets**——用户永远可以直接开始匹配。**持久化落点（Codex 高危 5）**：
  现 `/consult/finalize` 只 load→build draft→return 零写入（sessions.py:244），
  改为在一次 `mutate_state_atomically` 内：校验完整度 → 剩余 targets 置
  skipped + 清 pending question → 构造 draft 返回。
  **在途回答竞态（Codex 三审阻断 2，"行锁天然串行化"不足）**：咨询 LLM 在
  取行锁前已基于旧 state 执行——finalize 先提交后，咨询 CAS 仍满足同一
  expected_round，可能把已 skipped 的 target 改写成 answered 甚至复活旧
  pending；且 UI 实际可触发（输入框只在 turn.isPending 禁用，「生成确认单」
  只受 finalize.isPending 控制，WorkbenchPage.tsx:345/:446）。规格：
  - 咨询轮 CAS 除 expected_round 外**追加核对 latest pending 身份与请求
    开始时一致**（身份键 = `target_ref + asked_round`，与 CAS2 前提同
    标准逐字锁死，四审 V6-3）；pending 已被 finalize 清除或 target 已
    终态 → 该轮 409，**不得恢复/改写终态**；
  - 前端 `turn.isPending` 时同步禁用 finalize CTA；
  - 补"咨询 LLM 等待期间 finalize"竞态测试；**`/match-brief` 兜底**：客户端可绕过 finalize
  直呼 match-brief（sessions.py:263），其锁内持久化路径同样执行隐式 skip，
  否则 run snapshot 携带未结 targets；
- `calculate_completeness` 公式**不动**（既有测试与 ge/le 约束不扰动），
  澄清进度独立字段展示；
- **轮内处理顺序锁定（Codex 三审高 4）**：①按 pending 判定确定性 skip →
  ②在 working state 上更新 target/pending →③**重新执行 determine_phase**
  →④再构造 prompt 与下一问——现代码在调 LLM 前先算 phase
  （consult_engine.py:224），若不重算，skip_remaining 清空 targets 后模型
  仍按 resume_clarify 生成下一问；
- **A/B 防互踩**：PM 停滞检测（§2.2 触发 2）排除澄清轮，判定键 =
  **pending_at_round_start || 本轮发出了澄清问题**（不按重算后的 phase 判，
  Codex 三审高 4 连锁）。

### 1.3 提问与回填（数据归属铁律）
- CONSULT_PROMPT 增加 clarify 分支：针对当前 target 问一个具体问题并引用
  原文片段；**实施注（N7）**：第 N+1 轮 prompt 需同时区分"待抽取回答的
  target T"与"待提问的 target T+1"，防重问（questions_used 兜底）；
- **回答归属 = pending question 锚点制（Codex 二审阻断 1，取代"存在未结
  target 的任意 phase 就抽取"）**：新增持久化字段
  `pending_clarification_question = {target_ref, asked_round, baseline_version}`，
  在小意实际发出澄清问题的那轮 CAS 写入；**只有存在 pending question 时才
  执行回答抽取，且只允许绑定其 target_ref**——targets 从归一化起就存在，
  但用户还在答职业目标/地点时（未问过任何澄清问题）模板回答**不得**产生
  C### span；成功回答/跳过后在同一 CAS 内原子清空 pending，再选择下一个
  target；phase 因 questions_used 达上限切走后 pending 仍在，回答照常归属；
- **LLM 只允许产出 `answer_summary` 与 `clarification_action`**
  （answered | skip_current | skip_remaining，optional 字段，抽取失败不炸轮、
  target 保留待下轮）——其余全部服务端确定性生成：
  - `raw_answer` = 截长后的用户消息**原话逐字**（≤ MAX_USER_MESSAGE_CHARS）；
  - `target_ref` = 服务端注入并校验的当前 target；
  - `span_id` = 代码生成（前缀 `C` + session 内序号，与 `R###` 命名空间隔离）；
  - **span.text = raw_answer**（证据本体永远是用户原话；summary 仅展示元数据，
    summary 校验用**实词 token 子集判定**（summary 的内容词全部出现在
    raw_answer 中即通过——归一化子串包含会拒掉一切正常转述，N3）；
    **校验失败即丢弃 summary，展示层回退 raw 截断**，target 仍算 answered）；
    CONSULT_PROMPT 明示 summary 必须**抽取式**（只复用用户原词，抬高
    token 子集通过率），P4 彩排观测通过率；**已知取舍声明（四审 V6-2）**：
    summary 全灭时澄清对隐式空间的增强为零（P0 隐式本就零消费澄清）、
    对显式链路无影响（effective_resume_text 含 raw）——fail-closed 是
    有意设计，实施不得为"信号非空"放宽校验或直拼 raw；
- **跳过机制（确定性先行）**：短语白名单（"跳过/不想说/先不补充/下一个/
  skip"等）在 **LLM 调用前**判定，**启用条件 = 存在 pending clarification
  question**（不再按本轮重新计算的 phase 判定——最后一问发出后 phase 可能
  已切走，按 phase 判会漏识别跳过，Codex 阻断 1 连锁修正）；
  **"混有实质内容"判定写死（三审 V3）**：剥除白名单短语后残余 < N 字符
  （如 8）才判 skip，否则不走白名单、交给 LLM 的 clarification_action
  次级信号裁决；`questions_used` 独立持久化（与 answered 数分离，
  防重问循环）；
- **存储（确认基线不可变——v1 的"追加进原字段"撤回）**：
  - `normalized_base_resume`、`original_evidence_spans` **一字不动**
    （数据库宣称"用户确认过的内容"保持为用户确认时的内容）；
  - 新增独立字段：`resume_state.clarifications[{target_ref, answer_summary,
    span_id, round, action}]` 与 `resume_state.clarification_evidence_spans[]`
    （EvidenceSpan 复用现有 `source` 字段 = `"user_clarification"`，
    **不造平行 origin 术语**）；
  - CAS mutator 显式扩展：在 persist_turn 的原子合并中加性写入上述两字段
    （加入持久化白名单，append-only 合并语义，**幂等身份键 = span_id /
    clarification 的 target_ref+round**——通用合并器无默认复合键，须显式给）；
  - **换简历竞态 generation guard（Codex 高危 7）**：save_normalized_resume
    整体替换 ResumeState 且 resume_version+1（state_store.py:127），而咨询轮
    先读旧 state 后 LLM 再 CAS——交错时旧简历问题的回答可能挂到新简历。
    pending question 携带 `baseline_version`（=发问时 resume_version）。
    **一致快照制（Codex 三审阻断 1，取代"只丢澄清变更照常持久化"）**：
    - 初始读改用新内部 API `load_consult_context`——**单查询**同时返回
      state + resume_version + confirmed_resume_version + generation（现
      load_state 与 get_resume_metadata 是两次独立查询、非同一快照，
      state_store.py:87/:110，可能拿到 v1 state 配 v2 版本号使旧问题错标
      新版本过检）；
    - **上传 202 窗口封堵（Codex 四审阻断 1）**：上传接口先返回 202、归一
      化在后台跑，resume_version 要到后台成功才递增（sessions.py:128/:139/
      :390）——只核 version 时，"读 v1 → 上传已受理 → LLM 完成 → CAS 见
      v1 通过 → 后台落 v2"会漏过旧回合。规格：**上传受理时即在原子事务内
      写单调 `resume_upload_generation` 并使旧确认失效**（不得走可能携带
      陈旧 state 的 load_state→save_state）。**受理写规格（五审注 1）**：
      现上传端点本身就是 load_state→save_state(status="resume_queued")
      整 state 重写（sessions.py:133-137），咨询轮 CAS 在该窗口提交会被
      整体回写抹掉——受理写改为**单条 UPDATE（status + generation +
      清确认），不重写 state JSON 列，替换现有 save_state 调用**；
      **各环节契约分层（Codex 五审消歧——"要求已确认"若同时约束后台
      提交，受理清确认后后台永远无法成功）**：
      - **咨询读取/CAS**：要求 `confirmed_resume_version == resume_version`
        且 `expected_generation == current_generation`；
      - **后台归一化提交**：只核 generation——成功则写新 ResumeState、
        递增版本、置 status=resume_ready、确认保持 NULL；
      - **过期后台任务（A/B 乱序）**：成功与失败写入都核 generation，
        过期任务**安静 no-op**——绝不覆盖新简历、绝不把当前任务错标
        resume_error（现失败路径无条件写 resume_error，sessions.py:390，
        是改造锚点）；上传事务返回 generation 并传给
        `_normalize_resume(expected_generation=...)`；
      - **resume-preview**：status=resume_queued 时返回明确的
        `409 resume_processing`，**不得返回旧档案供确认**（现只要
        version>0 即返回，sessions.py:152）；
      - **resume-confirm**：锁内要求当前 generation 已完成且
        status=resume_ready（现只要 version>0 即可确认，sessions.py:179/
        state_store.py:162——否则旧 v1 可被重新确认，**重开刚封死的
        202 窗口**）；最好同核客户端刚看过的 expected version/generation；
      - **resume_error 恢复路径**：确认已在受理时清除且 confirm 锁定
        resume_ready，归一化失败后用户须**重传简历**才能继续（UX 文案
        如实声明"上传即宣告旧档案作废"）；"恢复旧档案"显式动作列 P1；
      - 交错测试五条："202 已返回、归一化晚于咨询 CAS 完成"、"受理写与
        咨询 persist 并发 → 咨询轮不丢"、"两读之间重传"、"queued 期
        preview/confirm 均不得暴露/确认旧版本"、"A/B 乱序完成——A 的
        过期成功/失败均不影响 B"；
    - **发问 CAS 与回答 CAS 都在锁内核版本 + generation**；
    - 版本不一致时**整轮不落库**：不写该 LLM turn、不推进 round、返回受控
      `409 resume_changed`，前端重拉 resume-preview + consult——本轮
      assistant_reply/next_question 同样由旧 target/旧原文生成，落库会让
      用户看到已失效的问题且无 pending 接收回答（v5 "只丢澄清"不彻底）；
    - 竞态测试两条：state 与 metadata 两读之间重传、LLM 等待期间重传；
    - **边界判据写死（四审 V6-2）**：版本冲突 = 环境性失效（target 已
      作废，轮内一切话术不可救）→ 409 整轮作废；抽取失败 = 输出质量
      问题（target 仍有效）→ 不炸轮、target 保留重试——实施不得把抽取
      失败升级 409，也不得把版本冲突降级静默丢弃；
    - **409 适用范围（v8 修订，撤回 v7 "纯轮免检"）**：澄清开关开启时
      **所有咨询 CAS 统一核 generation**——纯 template/deepen 轮看似与
      简历无关，但新简历重建 clarification_targets 会改 determine_phase
      与 finalizable 触发（Codex 四审阻断 2：放行会在新版本上落旧 phase
      回合、按旧 targets 预留教练）；合法轮被 409 的体验成本由恢复 UX
      承接（输入保留、提示重试，见 §3），正确性优先；开关关闭时无
      targets/pending/教练，无需核（等价承诺不受影响）。

### 1.4 消费闭环（v1 "自动携带"断言不实，逐消费者列账）
新增三个统一 helper（单一事实来源）：
```
effective_resume_text(state)      # base_resume + 补充说明节（渲染层拼接）
all_resume_evidence_spans(state)  # original + clarification 两池合并
resume_evidence_ids(state)        # 白名单收集器（替换 base.py:25 现实现）
```
消费者**精确到函数**逐一切换（Codex 高危 6：粗粒度列账会漏掉真正决定
召回的入口，导致 C### 只进 strategy 白名单却不影响岗位召回）：
- `build_resume_retrieval_query`（query_builder.py:39，主召回 query 直读
  normalized_base_resume → 改 effective_resume_text）；
- `build_implicit_query_text` **P0 零消费澄清内容（四审 V6-1 收口，
  终版决策）**：该函数产出 anonymized_resume_text 供匿名案例检索
  （matching_agent.py:126），现测试断言完整简历/原始 evidence/姓名/
  联系方式不得进入（test_implicit_search.py:10-58）。v6 曾提"消费去标识
  化 summary"——但 token 子集校验是**忠实性**校验不是去标识化（抽取式
  summary 由构造必然复用原词，人名/客户名整句通过后直送隐式 query，
  现有正则对自由文本人名无效）。终版：**隐式空间 P0 不消费任何澄清内容**
  （显式检索与业务 Agent 用 effective_resume_text 不受影响）；隐式信号
  增强与"澄清进 user_profiles"同批移 P1（届时须自带 PII 清洗设计）；
  隐私测试升格为"**澄清任何内容不进 implicit query**"（更强更可测）；
- `MatchingAgent.build_user_prompt`（matching_agent.py:76）与
  `_explain_candidate_match`（:285）两个 LLM payload；
- Supervisor planning/final payload（supervisor.py:489）；
- strategy_agent 上下文选取（:47）与白名单派生（:98-157）、base.py:25
  收集器、result projector 的 resume_evidence 查找；**strategy/supervisor prompt 措辞同步改**（"original
resume evidence only" → "resume evidence and user-confirmed clarifications
(source-tagged) only"）。
**可见性口径**：source 标签 P0 仅内部状态与 supervisor_log 可见；结果
EvidenceItem 与 ResumePreview **不加字段**（验收措辞同步收窄——不再承诺
"结果页 origin 可见"，改为"证据链内部可溯源，答辩可展示 state"）。

## 2. Feature B：PM 常驻督导

### 2.1 职责模型（不变，措辞两处修正）
- "时刻存在" → **"进度可视常驻 + 关键时刻发声"**（v1 §2.2 本已如此，
  标题措辞对齐）；
- "真双向" → **"用户可回应的群聊引导"**（POST 无 reply_to/目标 persona，
  用户回答仍由小意处理——不夸大）。

### 2.2 PM 督导步（并发安全 + fail-open 版）
**L1 确定性评估**（每轮，零成本）：槽位缺口、completeness 变化、streak、
澄清进度、预算余量——事实并入 persist_turn 的 CAS 原子写。
**L2 有界 LLM 教练**（fast，strict-JSON 意图但按 extra=ignore 实情校验）：
- 触发三类（判据确定性）：
  1. **首次进入 deepen（不问来源相位）**——槽位先行下真实序列是
     template→resume_clarify→deepen，若锁死"template→deepen"则双开关
     场景恒假（子 agent 二审 N1）；**实现用状态判定**（phase==deepen 且
     该类未消费）而非严格边沿检测——防被优先级挤掉后永久饿死，也允许
     实现层对相邻两轮连发（R 轮定稿总结 + R+1 轮首入 deepen）做静默
     （三审 V4②）；
  2. 完成度停滞（连续 2 轮零增长且未 can_finalize，**排除澄清轮**）；
  3. 可定稿总结：条件 = `can_finalize && targets 为空或已耗尽/跳过`——
     防止画像刚齐、澄清还没问就先发"总结"导致叙事倒置 + 前端定稿卡
     被过早抑制（N2）；
- **预算与并发 = reservation 状态机（Codex 二审阻断 2，取代"从已持久化
  notes 计数"——那与"调用前预留"自相矛盾：预留时 note 尚不存在）**：
  - 持久化 `coach_reservations[{coach_attempt_id, round, trigger,
    status: reserved|succeeded|unavailable}]`；**预算计数依据 =
    reservations 总数**（不是 notes 数）；每类 ≤1 次、总 ≤3 次
    （`CONSULT_COACH_MAX`，Field 1..5）；
  - 执行顺序：**第一次 CAS 同时持久化 小意回合 + L1 事实 + reservation
    （status=reserved，每轮至多一个，优先级 定稿>停滞>转换）→ 事务外调
    L2（mutate_state_atomically 只在 mutator 内持锁，L2 必然在锁外）→
    第二次 CAS 按 round+trigger+coach_attempt_id 定位 reservation 置
    succeeded/unavailable，并向对应 turn 内嵌套追加一次 note**（该操作是
    修改既有条目而非顶层 append——合并语义按 coach_attempt_id 幂等，
    重复执行不产生第二条 note）；
  - **CAS2 并发前提逐字锁死（Codex 三审高 3，防实施者复用现有
    _ConsultRoundConflict 的 round 等值判断，sessions.py:360）**：CAS2
    **不检查** consult_rounds_used == reservation.round，允许
    latest.rounds_used ≥ reservation.round；只要求 reservation 存在且
    round+trigger+attempt_id 身份匹配；仅 reserved 允许转终态；已是相同
    终态则幂等 no-op；**对最新锁内 state 原位更新**（不复制 L2 调用前的
    state）；交错测试覆盖；
  - **crash/CancelledError 规则**：进程退出后遗留的 reserved 视为已消费
    （烧掉不释放，有界优先——N5 口径统一），同一 trigger 不再重试；
    下一轮其它 trigger 不受影响；并发同轮请求被第一次 CAS 的
    expected_round 409 挡住，物理调用数不可能超预算；
  - **跨轮 stale-working 覆盖防护（子 agent 三审 V1，必改）**：persist_turn
    对 consult_transcript 是整表 deepcopy 覆盖（sessions.py:366-371），冲突
    检查只看 rounds_used，而 CAS2 不推进 rounds_used——第 N+1 轮的 L2 窗口
    （1–8s）内另一 tab 发起第 N+2 轮、其 LLM 调用恰好横跨 CAS2 时，R2 的
    整表覆盖会**静默抹掉刚追加的 note 并回退 reservation 状态**。规格：
    persist_turn 合并 consult_transcript 时，对重叠 round 的条目按
    `coach_attempt_id` **并集保留 latest 中已有的 supervisor_notes**；
    coach_reservations 按 attempt_id 合并且状态**单调**（reserved →
    succeeded/unavailable 不可逆退）；补"CAS2 与下一轮 persist_turn 交错"
    竞态测试；
- **fail-open 铁律**：L2 超时（独立小超时预算，如 8s）/解析失败/服务错误
  只记 `status=unavailable` 日志，**绝不把已成功的小意回合变成 502**；
  CancelledError 穿透；
- **verdict 双落**：note 存 turn 条目内（见 2.3）；同时 supervisor_log
  append（stage="consult_coach"）——CAS mutator 白名单显式加入
  supervisor_log 的受控追加（现白名单会丢弃它，v1 未列账）。

### 2.3 转录与渲染（v1 顶层条目方案撤回）
- **PM 消息内嵌于当轮条目**：`ConsultTranscriptEntry` 加 optional
  `supervisor_notes: [{kind, trigger, text, verdict}]`（声明字段，
  extra=forbid 不炸；旧数据缺 key 默认空表；条目"整轮"语义保持）——
  最近四轮切片、avoid-role 扫描、React key、必填字段全部零破坏；
- note 嵌套模型**单列且 `extra="ignore"`**（不继承 PublicDTO 的 forbid——
  防同一 500 陷阱向下递归一层，N6）；**写侧仅在有 note 时写 key**
  （开关关时旧全字典断言不红）；
- 长期账（P1 点名）：note 绑定轮次，未来 run-input 时代的无锚点 PM 独立
  发言需再评估形态；
- **返回时序写死（Codex 高危 4）**：POST /consult **等待 note 追加成功或
  unavailable 落账后才返回**（L2 不放后台）；ConsultResponse 不重复携带
  note——前端本就忽略 POST payload、成功后 invalidate 重拉 GET consult
  （WorkbenchPage.tsx:267），note 随 refetch 到达；e2e 断言 refetch 后 PM
  气泡出现；
- **滚动锚点修正**：现自动滚动依赖 transcript.length（WorkbenchPage.tsx:338），
  旧 turn 内嵌 note 不增条数、不会触发滚动——改按**实际渲染气泡数**
  （含 note）作滚动依赖；
- **note 字段契约定稿**：`{kind: "coach", trigger: "deepen_entry"|
  "stagnation"|"finalizable", text: str(≤300), verdict: "pass"|"advise",
  coach_attempt_id: str}`——嵌套模型单列 extra="ignore"，幂等身份 =
  coach_attempt_id；
- 前端在该轮小意气泡后渲染 PM note 气泡（复用 v3.2 消息体系）；
- **小意上下文隔离**：`build_consult_user_prompt` 的最近四轮投影**剥掉
  supervisor_notes**（PM 引导不注入小意的 LLM 上下文——职责分离，N4）；
- text 长度上限独立（如 ≤300），不受 assistant_reply 120 限制约束。

### 2.4 成本与延迟
每会话新增 LLM ≤3（教练）+0（澄清抽取并入小意响应字段）；触发轮典型
+1~2s、最坏 +8s（独立超时上限，fail-open）；全过 Semaphore。

## 3. 与 v3.2 前端方案衔接（含三重发声抑制）

| v3.2 项 | 本方案后形态 |
|---|---|
| P0-9A① 槽位集齐插话（前端） | 保留（即时性） |
| P0-9A② 确认单生成插话（前端） | 保留 |
| can_finalize PM 卡（WorkbenchPage:446） | **只抑制重复说明文案，永不隐藏「生成确认单」CTA**（该按钮是页面唯一 consultFinalize 入口，v3.2 :285 还锁定了其 accessible name——Codex 二审阻断 3）：后端 finalizable note 存在时，前端卡收缩为仅含 CTA 的行动条挂在 PM note 气泡下；教练关闭/失败时回退完整卡 |
| 槽位 chips | +第四枚「简历补充」：展示 `answered/skipped/remaining` 三态（"归零"口径撤回——跳过不增 answered），完成态判定 = `answered+skipped==total`；targets 空不显示 |
| 群公告进度卡 / 运行期 PM 交接（P0-9B） | 不变 |
| 能力边界声明 | 咨询期升级为"用户可回应的群聊引导"（不称"真双向"） |
| **409 resume_changed 恢复旅程（Codex 四审高 3）** | `turn.onError` 分流 `status===409 && message==="resume_changed"`（client.ts:32 已把 detail 投影为 ApiError.message，可直接分流）：**保留用户输入、不自动重放、清除失效 briefDraft**，invalidate/refetch resume-preview + consult，提示两段式（Codex 五审）：preview 返回 409 resume_processing 期间显示"新简历处理中"，preview 成功后切换"简历已更新，本轮未提交；请确认新档案后重试"；`turn.isPending` 同时禁用 finalize CTA；Vitest + Playwright 恢复旅程各一条；resume-preview 后端同批改 state+版本单查询（现 sessions.py:152 两次独立读） |

## 4. API/Schema 增量（如实清单，全加性）
- `ResumeState`：+quality_issues_struct、+clarifications、
  +clarification_evidence_spans（EvidenceSpan.source 新增合法值）；
- 咨询内部状态归属定稿（Codex 三审高 5——targets/questions_used 此前
  缺持久化 schema，抽取失败轮无 clarification 记录却已耗 question，
  不能从现有数组推导）：
  - `ResumeState`：+clarification_targets[{target_ref, status:
    open|answered|skipped}]、+pending_clarification_question{target_ref,
    asked_round, baseline_version}、+questions_used、+clarifications、
    +clarification_evidence_spans；
  - SharedState 顶层（会话级）：+coach_reservations[]；
  - **重传简历重置 ResumeState 内 A 组全部字段，但不重置会话级教练预算**；
  - 均不出公开 DTO，隐私 trace 白名单回归覆盖；
- `ConsultTranscriptEntry`：+optional supervisor_notes；
- `ConsultStateResponse/ConsultResponse`：phase 枚举 +resume_clarify、
  +clarification_progress{answered, skipped, total, questions_used}；
- `determine_phase` 签名变更（内部 API）；`mutate_state_atomically`/
  `_load_locked_state` 锁内暴露 resume_version **+ resume_upload_generation**
  给 mutator（内部 API，三审 V2 / 五审注 2）；
- `resume_upload_generation`：session_state **新列**
  `BIGINT NOT NULL DEFAULT 0`——schema.sql + 新迁移脚本；上传事务返回
  generation 传给 `_normalize_resume(expected_generation=...)`（五审注 3
  + Codex 五审高危补全）；
- `resume-preview` 新增 `409 resume_processing` 响应（detail 契约同
  resume_changed 列账）；`resume-confirm` 前置条件收紧（resume_ready +
  当前 generation）；CAS 持久化白名单扩展（clarifications/spans/supervisor_log
  受控追加；consult_transcript 重叠 round 条目按 coach_attempt_id 并集
  保留 supervisor_notes；coach_reservations 状态单调合并）；
- `409 resume_changed`：复用既有 409 状态码，**detail 字符串是事实契约**
  （前端按它分流重拉 resume-preview + consult），detail 值与前端分流逻辑
  列入契约测试；
- OpenAPI 快照 + generated.ts 有意再生；ResumePreview / 结果 EvidenceItem
  不变。

## 5. 开关与"等价"承诺（可测版）
`RESUME_CLARIFY_ENABLED` / `CONSULT_COACH_ENABLED`（默认 false）。
**验收表述改为运行时行为等价**：开关关闭时——业务分支不进新路径
（determine_phase 永不返回 resume_clarify、L2 零调用）、CONSULT_PROMPT
与基线一致、LLM 调用次数一致、持久化副作用一致（新字段恒为空缺省）、
既有测试语义全绿；OpenAPI 仅发生本方案评审过的加性变化（静态产物本就
不随运行时开关变，不承诺响应字节一致）。**测试覆盖四组合 00/10/01/11**。

## 6. 可行性评估（上修）
**工期**：全量 **10–12 个工作日**（v4 增 reservation 状态机、pending
锚点制、generation guard、finalize 持久化 + match-brief 兜底、query builder
消费切换约 +1d；v5–v7 增 load_consult_context、竞态测试组、隐私测试、
CAS2 前提约 +0.5–1d；v8 增 generation 新列迁移、受理原子写、202 交错
测试、前端恢复旅程双测试约 +0.5–1d——五审注 4 如实累计）。**压缩版 ≈ 7–8 天**：断档检测器→P1
（已砍）、澄清缺省 2（已定）、L2 效果 A/B 基础设施→P1、教练触发只保
"定稿总结+停滞"两类（转换类→P1）——压缩版需用户明确选择。
**风险**：同 v1 五条 + 新增：CAS 合并面扩展与 reservation 状态机是本方案
最深的改动（回归靠四组合测试 + 特征测试列账 + 竞态测试）；PM 话术质量靠
真机彩排验收。
**回滚**：双开关 + 全加性字段，关掉即运行时行为等价回退。

## 7. 分期
P0 = A（P0 层回填）+ B（L1+L2 **三触发全版为默认批准版**；压缩版两触发仅在用户明确选择压缩工期时生效，不由实施者自行取舍）+ §3 衔接件 + 双开关；
P1 = 真重归一化（re-confirm 流）、时间断档检测、澄清进 user_profiles、
教练效果 A/B、结果证据 DTO 来源标签、run-input API。

## 8. 测试计划（增补版）
单元：触发器（severity 归一/缺描述/去重键）、阶段机（槽位先行矩阵）、
跳过白名单（pending 存在性判定）、**pending 锚点制**（有 targets 但未问过
→ 模板回答不得产生 C###；最后一问后 phase 切走仍可跳过/归属）、跨轮抽取
错位与失败兜底、span 归属铁律（text=原话/ID 服务端/summary token 子集）、
**generation guard 竞态**（两读之间重传 + LLM 等待期间重传 → 409
resume_changed 整轮不落库）、**finalize 在途竞态**（LLM 等待期间 finalize
→ 咨询轮 409、终态不被改写）、**隐私**（澄清任何内容不进 implicit query——升格版）、
helper 三件套 + **query builder 消费**（effective_resume_text 进召回 query）、
L1 事实、**reservation 状态机**（预算按 reservations 计数/crash 遗留
reserved 烧掉/coach_attempt_id 幂等追加/每轮一个/fail-open/超时/CAS2
前提：rounds_used 不等值、单调、幂等 no-op、原位更新）、**轮内顺序**
（skip_remaining 后重算 phase 不再生成澄清问）、
finalize 隐式 skip 持久化 + /match-brief 兜底、**跨轮覆盖竞态**
（CAS2 与下一轮 persist_turn 交错 → note 不丢、reservation 不逆退）；契约：DTO 加性快照、旧 state/转录反序列化兼容、
`test_consult_api.py:119` 等精确断言更新列账；隐私：clarifications 不出
公开 trace（白名单回归）；四组合开关测试；真机：P4"简历含糊者"彩排
（澄清→引导→回填→匹配→strategy 引用 C### 证据）+ PM 触发逐类演示；
e2e：refetch 后 PM note 气泡出现 + 滚动触发 + finalizable 行动条 CTA 可用
+ resume_changed 恢复旅程（Playwright）+ turn.onError 分流（Vitest）
+ 202 窗口交错（后端）。

## 9. 验收标准（可测版）
1. 含糊简历 → 小意引用原文主动问（≤RESUME_CLARIFY_MAX 个），白名单短语
   即时跳过，finalize 隐式跳过；
2. 澄清进入证据链：strategy 建议可引用 `C###` span（source=
   user_clarification，内部状态可溯源），原档案确认状态不变；
3. PM 教练按触发矩阵出场（notes 内嵌当轮、verdict 落 supervisor_log），
   fail-open 验证（人为断 LLM 不影响咨询轮成功）；
4. 双开关关闭 → 运行时行为等价（四组合测试绿）；
5. 轮次预算 8/15 不变、教练 ≤3、澄清 ≤RESUME_CLARIFY_MAX；
6. 全量 pytest 绿 + 快照/类型有意再生一次 + P4 真机彩排通过。

## 10. 实施期注意事项（六审终审注——非阻断，随实施 PR 并入）

1. **契约分层的开关作用域**：":咨询读取/CAS 要求 confirmed==version" 是新的
   后端要求（现 `_execute_consult_round` 全程不查简历、仅前端 canConsult 拦）
   ——必须与 generation 核查同样**限定"澄清开关开启时"**，否则 00/01 组合
   下未确认即咨询的既有 API 测试红、等价承诺破；实现 PR 把该限定写进代码
   注释（§5 四组合测试是机械安全网）。
2. resume_error 态的 preview 展示旧档案（可见但不可确认、不可咨询）——
   两段式提示补第三态文案："旧档案已作废，请重传"。
3. queued/未确认期直接打 API 的咨询请求，409 detail 建议复用
   `resume_processing` 语义与 preview 一致（前端被 canConsult 挡住，仅
   API 直呼可触发）。
4. `save_normalized_resume` 签名加 generation 核查参数——与
   `_normalize_resume(expected_generation=...)` 配对，列内部 API 账。
5. 工期：v10 增量（preview/confirm 收紧 + 两条测试 + 两段式 UX）约 +0.5d，
   在 §6 的 12d 上限内吸收。
6. （Codex 终审）confirm 的 expected version/generation 核对**按必做实现**
   ——防多标签页确认用户未看过的新版本；文中"最好"不得理解为可省略。
7. （Codex 终审）`resume_error` 选定稳定 detail 字符串 + 前端重传 CTA
   契约测试。
8. （Codex 终审）§5 "新字段恒为空缺省"仅指 SharedState 功能字段；
   基础设施列 `resume_upload_generation` 始终启用、上传后必然非零。
9. （Codex 终审）queued / A-B 乱序两项测试现写在 §1.3——实施账目与 §8
   统一收录，内容无遗漏。
