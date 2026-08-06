# 前端产品化优化方案（v2.3 终稿 — 三方评审通过）

> **评审记录**：Claude Code（起草与合议）+ 子 agent 独立评审两轮（二审 APPROVE）
> + Codex 独立评审四轮（四审 APPROVE）。合计处置 40+ 条意见，含三个现网真 bug
> （反馈 422、cancelled 终态缺失、切侧栏丢结果）与一个后端语义冲突设计的撤回。

> v1 → v2：子 agent 与 Codex 双路评审均 NEEDS_CHANGES，意见高度收敛。v2 修正：
> ①两条"数据源现成"断言不成立（结果 DTO 无 score → 强度条出 P0；消息无时间戳 →
> 删时间戳与伪耗时）；②检索胶囊诚实性矛盾（P0 只留恒真项，动态胶囊入 P1 走
> per-run 审计字段）；③阶段轨改为**七段精确契约**；④反馈词表对齐后端真实枚举
> （评审顺带挖出现网 3/4 选项会 422 的真 bug）；⑤工期重估（终口径 2.5–3 天，见 §五）、暗色与双栏
> 出本期；⑥新增 P0-0 现网缺陷修复包（run 持久化 / 终态死胡同 / cancelled 终态 /
> PM 重复自介 / e2e fixture 契约违例）。
> 设计主旨不变：**一个标志性交互（七阶段 RunRail）+ 全链路诚实的状态可视**。

## 一、现状审计（v2 修正版，全部实查代码）

**成立的核心诊断**：数据层把"过程可解释"做满了（`completed_stages/stage/
total_stages`、消息 `persona/stage/kind/seq`、`profile_draft/completeness`、
recovery 循环消息——后端全给了），表现层只消费了不到一半；检索能力（RAPTOR+
Cross）在 UI 上完全不可见。强制滚底（WorkbenchPage:342）、会话无名 ID、额度
撞墙才知道、完成度只在可定稿时闪现、证据模态割裂、反馈原生 select——均属实。

**v1 审计的三处修正**：
- persona **已有四色**（theme.css:82-85 青/蓝/紫/赭实心底），P0-4 是"色进 token +
  分组分节"的微调，不是从零建设；
- 移动端保障**比 v1 以为的更少**：Playwright 只有 Desktop Chrome 一个 project，
  **不存在任何 375px 断言**（v1 说"e2e 保证 375px 无溢出"不实）；
- 运行期已有常驻"团队正在处理下一阶段…"指示条（:485-489），真实缺口是
  **不具名、不分阶段**，不是"完全静止"。

**v1 漏掉、双审补上的现状问题**：
- **两套设计系统并存**：结果卡内嵌的 EvidenceDrawer/ReactionForm 走
  `styles/global.css + tokens.css`（navy/teal 旧皮肤），与 v2 米色系同屏混搭，
  两套合计 50+ 处 token 外硬编码色；评估/监控页整页旧系统；
- **现网 bug**：ReactionForm 的 helpful/not_relevant/applied 三个选项不在后端
  outcome 词表（passed_screen/oa/interview*/final_interview/offer/rejected），
  提交即 422——mock 无条件放行掩盖了它；`cancelled` 是后端终态但不在前端
  TERMINAL 集合（:21），取消后会永远显示"服务进行中"；
- **演示翻车点**：run_id 只活在 URL query，侧栏 NavLink 不带 query——运行中点一下
  侧栏，**结果永久丢失**且可继续瞎聊；failed/stale 后输入框禁用 + 无重开按钮 =
  死胡同；PM 自我介绍在静态欢迎与运行 intro 消息里出现两遍；
- 归一化中刷新页面，409 会被解读为"未上传"而重新显示上传入口（known_issues
  #6 的前端注释自认），有重复上传风险——修复属后端错误码细分（P1）；
- e2e mock 违反真实契约：`can_finalize=true` 却 `hard_constraints={}`（后端
  三槽规则下不可能）；completed_stages 漏 resume、终态只给四段（真实七段）。

## 二、设计原则（不变）+ 诚实性红线（新增）

四条参照原则（对话主轴/阶段台账/任务面板/轻快动效）保持。新增红线：
**UI 上的每个状态声明必须有真实数据源**——没有时间字段就不显示时间戳；
拿不到运行期开关状态就不亮能力胶囊；推断不出"谁在线"就只说"当前阶段"。

## 三、P0（全量 2.5–3 个工作日；2.5 天硬上限用 §五 P0.5 削减版；全部零 API 变更）

### P0-0 现网缺陷修复包（先于一切视觉工作）
1. **反馈词表修正**：按钮组 = `被拒 / 过筛 / 面试 / Offer`（映射 rejected /
   passed_screen / interview / offer，均为后端词表真枚举）+ 可展开备注；
   干掉必 422 的三个旧选项。**语义框架同步改**：这些是投递后的漏斗结果，
   模块标题从"这个推荐有帮助吗？"改为"投递后回来告诉我们进展"（异步语义），
   避免刚出结果就问投递结果的错位；即时相关性反馈（有帮助/不相关）需要
   后端词表扩独立字段，明确列入 P1；按钮**默认不预选**（防止刚看到结果就
   误提交"被拒"）；
2. **cancelled 入前端 TERMINAL 集**；
3. **run 持久化**：`localStorage["last_run:{user_id}:{session_id}"]` 在
   **createMatchBrief onSuccess（拿到 run_id 即写）**，进入会话且 URL 无
   `?run=` 时自动恢复——考官点侧栏不再丢结果；execute 成功或 409 时幂等覆盖；
   恢复后 status 若 404/403 → 删除陈旧键回咨询态；
   登出与 401 统一出口都清理本地键（隐私——当前 401 边界只清 query cache）；
4. **终态出口（后端语义对齐版）**：Match Brief 创建后后端即置
   `intent_consulted=True`，同会话再发 consult 一律 409——**"同会话继续咨询"
   前端零 API 做不到，撤回该设计**。P0 口径：
   - `completed`：保留结果视图为该会话的终点页（这就是它的产品形态）；
   - `failed / stale / cancelled`：渲染「新建咨询重试」按钮（走现有
     createSession，消耗会话额度，弹窗如实说明）；错误文案同步改写，
     不再误导"可重新生成确认单"；
   - 同会话重开咨询 / 多轮匹配 / run 历史列表 → **P1**（需后端解锁语义与
     session-run history API）；
   - 前端重置面（briefDraft/brief/executeAttempted/查询缓存）仅服务于
     「新建咨询」跳转前的本页清理，不宣称能恢复咨询；**实施顺序约束**：
     必须等 createSession 成功后才清理本页状态并跳转，402 时保留原终态页面；
5. **PM 自介去重**：运行消息渲染跳过 `kind==="intro"`（静态欢迎已承担该职责）；
6. **e2e fixture 契约修正**：mock 的 can_finalize 与三槽数据一致；status 用
   连续多次响应模拟七段推进（resume→…→result 全集）；反馈 mock 校验词表；
   **mock 全面对齐 DTO 并建 typed fixture builder**（`satisfies` 各响应类型，
   防再次静默漂移）——已知漂移全清单：resume-preview 的
   quality_issues→resume_quality_issues、evidence_spans/span_id/text→
   evidence/evidence_span_id/content、experience.company→organization、
   education.school→institution、缺 resume_version；RunStatus 缺
   execution_durability/updated_at；result 消息 stage 应为 result 非
   finalization；ReactionResponse 状态串是 reaction_recorded；
   session create 状态串是 awaiting_resume。

### P0-1 七阶段 RunRail（本轮标志性交互）
时间线内嵌任务卡（单一 DOM，**P0 全断点保持时间线内联**——右缘 sticky/侧板
与"双栏出本期"矛盾，彻底归 P1）：
- 七段**精确契约串**映射：`resume 简历 → intent 意图 → retrieval 检索 →
  strategy 策略 → verification 核查 → finalization 整理 → result 发布`
  （PUBLIC_STAGE_ORDER 逐字对应；不发明"锁定"伪阶段——Brief 锁定发生在 run 前，
  由确认单卡片自身表达）；
- 已完成实心勾 / 当前脉冲 / 未到灰点；**不显示耗时**（接口无历史翻转时间，
  本地观测值会撒谎，删）；
- `kind==="recovery"` 消息驱动轨上「↻ 质量把关：受控重检」标记——把有界循环
  变成可见的质量叙事。

### P0-2 状态指示（只说真话版）
- 咨询期：`turn.isPending` 驱动小意 typing 气泡（真实信号）；
- 运行期状态**优先级映射**（不机械读 stage——完成后 stage 仍可能停在
  finalization，`result` 是公开进度节点不是 RunStage 枚举值）：
  ① `completed/completed_with_warnings` → 「已发布」，七段全勾；
  ② `failed/stale/cancelled` → 停止脉冲，中断态标在所到阶段；
  ③ `draft/plan_ready`（此时 **stage="plan"**，不是 null）→「确认单已锁定，
     准备执行」；`queued`（stage=null）→「已进入执行队列」；plan 不进七段轨
     但也不是异常值；
  ④ running 且 stage ∈ intent–finalization → 直接映射白话文案；
     running 且 stage=null → 「正在启动」；
  ⑤ 未知值安全降级「处理中」；终态若 stage 停在 plan/null，显示卡片级
     「执行前中断」而非把中断标进阶段轨。
  **不模拟无法证明的"某 agent 正在输入"**。

### P0-3 咨询槽位 chips（严格同口径）
输入框上方三枚 chips + completeness 细条：
- 判定**逐字复刻**后端 `_required_slots_filled`：目标=current_goal 含非空串；
  地点=`locations` 为**至少一个元素、且所有元素均为 trim 后非空字符串的 list**
  （`["  "]` 不算填了）**或** `remote===true`（chip 显示"地点：远程"）；
  签证=`need_visa_sponsor` **是布尔即已答**（false 显示"签证：不需担保"——
  严禁 truthy 判断）；
- 纯函数 + 单测与后端 tests/test_consult_engine.py 用例对齐；
- **chip 可点**：点击未完成 chip → 输入框聚焦；**仅输入框为空时**预填引导句
  （已有草稿只聚焦不覆盖）。

### P0-4 消息质感（微调档）
同 persona 连续消息分组；运行播报按 stage 插入小节行；入场 fade+4px/200ms
（尊重 prefers-reduced-motion）；现有四色收进 token 并统一头像/名字排版；
hover/聚焦显示元信息**分体裁**：运行消息显示阶段（有 stage 无 round）、
咨询消息显示回合（有 round 无 stage）——不能两者同显（无该数据）。

### P0-5 结果区（诚实版）
- 排名序号：前三名 ①②③ 强调，第 4 名起用普通序号 4./5.…（result_count 可到
  10，规则必须覆盖全量）+ tier 徽章层次化；**无强度条**（DTO 无分数）；
- 证据改**卡内手风琴**：`aria-expanded` + 键盘可开合，Vitest 用手风琴语义
  重写原三条焦点陷阱测试（a11y 契约替换而非删除）；引用段落标"出自 JD 原文"；
- 能力胶囊只保留**恒真项**：`混合检索（BM25+语义双路）`；
  `dual_space_enabled===true` 时加"支持双空间增强"（capabilities 真源）——
  RAPTOR/Cross 动态胶囊移 P1（需 per-run applied 审计字段，见 P1）；
- `source_url` 非空且为 http/https 时给「查看原岗位 ↗」（DTO 里是普通字符串，
  必须校验协议 + `rel="noopener noreferrer"`）；
- 反馈按钮组见 P0-0；提交后原位"已记录 ✓"；demo 徽章收右上角，触屏可点出说明
  （hover 之外提供可聚焦触达）。

### P0-6 滚动保护
底部 120px 内才自动跟随；否则「↓ 有新消息」浮标。**结果发布同样服从该规则**：
用户不在底部时浮标变体为「结果已生成 ↓」，点击才滚至结果首卡并短暂高亮。

### P0-7 导航、额度与空态
- **修 769–900px 无导航洞**：移动抽屉断点与现有 900px 统一（不是 768）；
- 侧栏额度**诚实版**：显示「已创建 N 次咨询」（has_more=true 时写「至少 N 次」
  ——分页响应无 total）；402 弹窗只写「当前账户的咨询额度已用完」，
  **不写数字上限**（402 响应不含上限值，精确上限入 P1）；
- 空态页三步引导卡 + 主按钮；
- 会话标题：**Match Brief 创建成功时**（锁定后，非 finalize 时——草稿会作废）
  把 career_goal 前 12 字写 `localStorage["title:{user_id}:{session_id}"]`；
  **登出与 401 统一出口清理全部 user-scoped 本地键（title 与 last_run 两类）**；
  无标题显示"咨询 · MM-DD"。

### P0-8 简历确认增强
确认卡加「查看完整档案」内联展开：education / experience / **projects** /
skills / resume_quality_issues / **evidence** 六类全量渲染（preview DTO 全集，
不漏项才配叫"完整"）；确认前保留「重新上传」入口（发现解析错误有出路）。

## 四、P1（答辩后，明确出本期）
暗色模式全量（前置条件：两套设计系统 token 统一，50+ 硬编码色清理，评估/监控
页同步——工作量被 v1 严重低估）；宽屏双栏任务板（断点数学重做：268px 侧栏 +
720 对话 + 300 面板 ≥ 1360px 才成立，或容器查询）；匹配强度条与 RAPTOR/Cross
动态胶囊（依赖 explain / per-run `applied` 字段的 API 增量）；精确额度与标题
落库；landing 产品缩影；离开页面提醒 / 取消 run；ProfilePage 的 JSON 裸奔
chips 化；真流式（SSE）。

**工期口径（二轮复核后）**：全量 P0 约 2.5–3 天；若 2.5 天为硬上限，
延后「消息分组与 hover 元信息」「侧栏本地标题」「空态三步卡」三项为 P0.5，
保住 P0-0、RunRail、槽位 chips、滚动保护、结果区证据/反馈、移动导航六件套。

## 五、实施清单与测试（v2）

五个提交批次：
1. P0-0 缺陷包 + fixture 契约修正（先红后绿）；
2. RunRail + 状态指示 + 滚动保护（plan_ready 的 stage="plan"、queued 的
   stage=null 分别映射，映射表按 status 优先并处理可空）；
3. 槽位 chips + 消息质感；
4. 结果区重构 + 简历展开 + 额度/空态（侧栏标题走自定义事件或 query
   invalidate 触发重渲——同 tab 无 storage 事件）；
5. 移动抽屉导航（`role="dialog"` + `aria-modal`、打开即入焦、**focus trap 或
   背景 inert**、Escape 关闭、焦点回归触发钮、背景滚动锁，配 Vitest/移动
   Playwright 断言）+
   Playwright 移动冒烟（**专用 spec/testMatch 只跑一条**，不让 mobile project
   重跑全部 e2e）。

测试账目（预计）：
- Vitest：slot 判定纯函数（含 visa=false 用例）、滚动 hook、stage 映射表、
  标题/last_run 本地键读写、手风琴 a11y 契约重写 ×3（净增 ~8）；
- Playwright：现有 6 场景维护（查看证据/关闭证据 → 手风琴断言；反馈按钮组
  文案；确认单按钮保持 accessible name 不变以免动 :257-266）+ 新增 4 场景
  （RunRail 七段推进、chips 随咨询翻绿含"不需担保"、failed/stale/cancelled →
  「新建咨询重试」且断言产生新 session_id、侧栏切换后 run 恢复）+ 375px 移动旅程冒烟（新增 mobile project）；
- 每批次跑 typecheck / vitest / build / e2e 四门；OpenAPI 与 generated.ts
  零变化为硬验收。

## 六、验收标准（v2）
1. 运行期 5 秒内可见"到了七段中的哪一段、当前阶段叫什么"；
2. 咨询任意时刻能说出"还差哪个槽位"，且"不需要签证担保"正确显示为已完成；
3. 结果区不点按钮即见排名层次与可信能力胶囊（无一句不可证实的声明）；
4. 运行中切侧栏再回来，运行轨与结果完好；失败后一键「新建咨询重试」；
5. 反馈四个按钮均发送合法 outcome 并获 202（mock e2e 断言词表 + 真实服务
   彩排各验一次——「真实入库」以彩排为准）；
6. Playwright 10 场景 + 移动冒烟全绿；OpenAPI/generated.ts 零字节变化。
