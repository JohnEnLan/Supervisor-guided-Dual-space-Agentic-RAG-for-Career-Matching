# 全局逐段审核合并发现清单（2026-08-07，基线 092461f→54f089f）

三方审核：子 agent 18 项（BLOCKED）+ Codex 21 项（不 PASS）+ Claude 线抽查（4 项亲验）。
合并去重后 29 项，按修复批次分组。修复人=Claude（v5.2），修后 Codex 复审 + 子 agent
重审受影响模块。状态标记：[ ] 待修 [x] 已修。

## FIX-1 后端行为（必修）

- [ ] **B1 (G1, 高)** field_path 打破等价：resume_intake.py:514 排除集加 "field_path"
      （+"target_ref" 防御）；:85 prompt 行挂 RESUME_CLARIFY_ENABLED 门；等价回归测试
      （真实 payload 含 field_path，开关关闭 verification_status 不变）。
- [ ] **B2 (G3/C1, 高)** T/T+1 锚点错位：抽取失败（answer_target 有、无 skip、action None）→
      确定性处理：预算余（questions_used<MAX）→ 服务端覆写 next_question 为 T 的重问模板、
      pending={T, asked_round=next_round}、questions_used+=1；预算尽 → 按 skip_current 处理 T，
      沿用现 :441 块锚 T+1。两轮错位回归测试 + 归属半边测试（tests-F2）。
- [ ] **B3 (G4, 中)** CAS2 持久化包 fail-open：sessions.py:648 mutate 包 try/except
      （CancelledError 穿透；CoachReservationConflict/其它异常 → 日志+返回 turn，预留烧掉）。
- [ ] **B4 (G6/C2, 中)** confirm 收紧：RESUME_CLARIFY_ENABLED 开启时 expected_resume_version
      缺失 → 422（DTO 保持 optional 兼容）；补 queued/error 真实分支测试（tests-F1）。
- [ ] **B5 (C3, 中)** 纯空白消息：请求层 strip 后非空验证；answered 且 raw 为空 → 视同抽取失败。
- [ ] **B6 (C4, 低)** summary 语义：校验失败持久化 None（不写 raw 截断）；raw 回退移投影层。
- [ ] **B7 (C5, 中)** 01 模式旧 targets：A 关闭时教练触发把澄清 targets 视为已耗尽；
      11→01 回滚旧状态测试。
- [ ] **B8 (C6, 中)** A 关闭时 phase_suggestion=resume_clarify 拒绝（基线重试语义）+ 调用次数测试。
- [ ] **B9 (C7, 中, 存量)** case_base.py:193 LIMIT 在 JOIN 后：CTE 先 Top-K case 再 JOIN outcomes。
- [ ] **B10 (C8, 中, 存量)** 会话额度竞态：事务内 advisory lock 原子 COUNT+INSERT + 并发测试。
- [ ] **B11 (C9, 中, 存量)** 同步解析阻塞事件循环：resume_intake 解析走 asyncio.to_thread
      （注释说明与宪法 asyncio 条款的关系：offload 阻塞调用是 asyncio 惯用法，非并发模型替换）。
- [ ] **B12 (G16, 低)** 投影文案"只引用简历已有证据"措辞涵盖澄清证据。

## FIX-2 前端（必修）

- [ ] **F1 (G2, 高)** 跨会话泄漏：useEffect([sessionId]) 清 briefDraft/brief/retryModal/
      executeAttempted（或 key={sessionId}）+ 测试。
- [ ] **F2 (G5/C10, 高)** preview 409 三态生命周期：按 detail 分流 resume_processing/resume_error；
      error 停轮询 + "旧档案已作废，请重传" + 重传 CTA；processing 刷新不显示上传入口。
- [ ] **F3 (C11, 中)** 统一 lifecycle 409 handler：confirm/finalize/match-brief 共用分流 +
      错误 UI + refetch；confirm 成功清 resumeRecovery。
- [ ] **F4 (C12/G13, 中)** AppShell 402 弹窗复用 FocusModal + 键盘测试。
- [ ] **F5 (C13, 中)** 硬条件显示诚实：SQL 锁定字段（locations/need_visa_sponsor=true/学历/经验）
      与方向类字段（remote/work_mode 等）分开标注，不统一称"锁定"。
- [ ] **F6 (C14, 中)** preview 非 409 错误与 consult GET 失败：显式 error 态 + 重试，
      数据未就绪禁发送。
- [ ] **F7 (C15, 中)** ProfilePage 查询失败 ≠ 空画像：错误态 + 重试。
- [ ] **F8 (C16, 中)** ReactionForm 幂等 key：payload 变更时轮换 key（同 payload 重试沿用）。
- [ ] **F9 (G12, 低)** LandingPage "数据库判定"句改为范围准确表述。
- [ ] **F10 (G14, 低)** 证据 chip 点击前查 aria-expanded。
- [ ] **F11 (G15, 低)** execute 效应 deps 换 execute.mutate。

## FIX-3 测试/验收安全网（必修）

- [ ] **T1 (C17, 高)** 四组合表驱动等价契约测试（prompt/外呼次数/响应/state delta 四维对比）。
- [ ] **T2 (G7)** 隐私 trace 回归：种入 clarifications/pending/coach_reservations 断言不出公开面。
- [ ] **T3 (G8/C19)** Playwright：PM note 气泡 refetch 场景 + finalizable 行动条 CTA。
- [ ] **T4 (G9)** 教练优先级 停滞>转换 测试。
- [ ] **T5 (G10/tests-F4)** 替换空转断言（202 窗口测试末段）。
- [ ] **T6 (G11/tests-F6)** summary 校验失败 × answered 组合路径测试（穿 run_consult_round）。
- [ ] **T7 (C18)** mobile spec 真发送咨询消息并断言回复。
- [ ] **T8 (C20)** e2e fixture 话术与 projector 现实同步。
- [ ] **T9 (C21)** PG 依赖测试加环境守卫/标记（无 PG 环境跳过而非报错）。

## 归档（用户口径确认项，默认照案通过）

- **A1 (G17)** preview 在 resume_error 返回 409（更安全路线，配 F2 后语义完整）。
- **A2 (G18)** 停滞 streak 在澄清轮重置而非暂停（更安静解读）。

## 双审已核对通过面（不重审除非被修复触及）

generation 生命周期主路径、reservation/CAS2 全套、finalize/match-brief 兜底、
三 helper 消费闭环、隐式零消费、公开 DTO 无泄漏、旧数据兼容、宪法合规
（asyncio/Semaphore/有界循环/证据防编造/无全局态）、FocusModal 与移动抽屉本体、
OpenAPI 纯加性。
