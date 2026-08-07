# 前端产品化优化方案（v3.2 终稿 — 群聊化修正三方评审通过）

> **v3 轮评审记录**：子 agent 三审 APPROVE（评价：三轮以来第一版事实层零瑕疵）
> + Codex 六审 APPROVE。加上 v2.3 轮，本方案累计经受子 agent 三轮 + Codex 六轮
> 独立评审，60+ 条意见全部处置。

> **v2.3 → v3（用户定位反馈驱动）**：v2.3 已获三方通过，但用户指出两个方向性
> 问题——①七阶段 RunRail 是工程流水线隐喻，没有体现"群聊服务"这个产品本体；
> ②四个角色没有"演好自己"：执行 agent 应主动提问引导顾客，PM 应在**每个 agent
> 交接点**出场确认质量并站在顾客侧引导。v3 据此重构 P0-1 为「PM 群公告·服务
> 进度卡」、新增 P0-9「角色主动性」三段式设计，范围声明从"纯前端"修正为
> "零 OpenAPI 变更 + 一项后端群聊投影增强（纯新增消息行，不改任何 DTO）"。
> v2.3 的全部评审结论（诚实红线、契约映射、缺陷包）完整保留。
>
> **v2.3 评审记录**：子 agent 两轮（APPROVE）+ Codex 四轮（APPROVE），40+ 条
> 意见处置，含三个现网真 bug 与一个后端语义冲突设计的撤回。

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

**v3 群聊化实查依据（conversation_projector.py 全文核对）**：
- 播报骨架已存在：PM intro → 小意复核 Brief → 小检开工/完成（完成句含候选数）→
  小策开工/完成交接 → PM 核查 checkpoint + recovery + 结果/警告——**交接叙事
  是有的，但 PM 的运行期发言只有 intro、核查 checkpoint 与结果**——
  **intent 完成、retrieval 完成两个交接点没有 PM 确认消息**（这正是
  "没体现监督"体感的来源）；
- 所有播报是"汇报语态"（"检索正在执行：SQL 硬过滤→…"），不是"对顾客说话"
  的服务语态；执行 agent 全程零提问、零引导；
- `runs.py::run_conversation` **已经加载 state 快照**（supervisor_log 取自
  snapshot）——给投影传入检索摘要（真实候选数等）零 schema 改动即可做到。

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

## 三、P0（全量 3–3.5 个工作日；3 天硬上限用 §五 P0.5 削减版；**零 OpenAPI/DTO 变更**——P0-9B 为后端投影纯新增消息行，属唯一后端改动，schema 不变）

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

### P0-1 PM 群公告·服务进度卡（本轮标志性交互，群聊隐喻版）
**形态修正**：不做页面级"工程流水线轨"。进度卡是 **PM 在群里发出的一条
群公告式消息**（PM 头像 + 气泡内清单，随时间线滚动、运行期在时间线内
sticky 置顶一份，单一 DOM）——过程可视长在群聊里，而不是长在群聊上面。
- **展示按四个角色分段**（群聊叙事单位）：
  `小意 · 需求确认 → 小检 · 岗位筛选 → 小策 · 规划建议 → PM · 核查发布`；
- **底层仍消费七段精确契约串**（诚实映射表写死）：
  resume+intent → 小意段；retrieval → 小检段；strategy → 小策段；
  verification+finalization+result → PM 段——分组只发生在显示层；
- **责任段 ≠ 实时执行主体（诚实归属表，防止"小意正在工作"的虚构脉冲）**：
  `resume` = 系统归一化流程（小意段内标"资料已就绪·系统处理"，不给小意
  脉冲）；`intent` = 咨询已完成时是 Supervisor checkpoint 复用结果（进行中
  文案"PM 正在复核小意已确认的需求"）；`retrieval`/`strategy` = 小检/小策
  真实执行（脉冲归属正确）；`finalization` = 系统确定性整理（文案"系统正在
  整理发布材料"）；`result` = PM 发布（非 RunStage 枚举，仅进度节点）；
- 每段：完成勾 / 当前段脉冲按上表归属 / 未到灰；**不显示耗时**；
- `kind==="recovery"` 驱动 PM 段上「↻ 质量把关：受控重检」标记；
- 状态优先级映射五条（v2.3 版）原样保留。

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

### P0-9 角色主动性（群聊的灵魂，三段式）
用户核心诉求：执行 agent 要像真顾问一样主动提问引导，PM 要在每个交接点
确认质量并站在顾客侧。**能力边界如实声明**：运行是锁定 Brief 后的异步
流程、中途不可接收用户回复——因此 P0 能诚实交付的是：**小意的真双向提问
（咨询期）+ 小检/小策的主动说明与建议（单向）+ 结果后的行动引导**；
"小检/小策运行中提问并等待回答"需要 run-input/状态机 API，**列入 P1 并
向用户如实说明**。每句插话都必须由真实数据渲染（不做空话表演）：

**A. 咨询期（真双向，前端确定性，零后端改动）**
- 小意本就是提问引擎（每轮强制一个启发式问题）；
- 新增 **PM 里程碑插话**（前端按数据确定性渲染，不调 LLM）：
  ① 三槽位集齐（can_finalize 翻真）→ PM："小意已把必填信息收集齐：目标
  {current_goal}、地点 {locations/远程}、签证{文案}。你可以继续补充偏好，
  也可以让我安排匹配。"（数据全部来自 profile_draft）；
  ② 确认单生成 → PM："确认单由你们的对话记录自动生成，请你核对无误后开始。"
  （核对动作诚实地交还用户——前端并没有"核对"任何东西）；
  实施注：PM 插话刷新后无法恢复原插入位（transcript 不记录翻转历史），
  确定性追加在时间线末尾，文档如实声明。
- 槽位 chips（P0-3）本身即引导；chip 点击预填 = 顾客侧引导动作。

**B. 运行期（单向播报升级为服务语态 + PM 交接确认——后端投影增强）**
改动面如实声明：`conversation_projector.py` 新增消息行 + **`runs.py` 从快照
白名单提取 checkpoint 状态与候选计数、经内部 context dataclass 传给投影**
（当前只提取 supervisor_log）；区分"字段缺失"与真实 0；继续禁止投影简历
原文/user_id 等私有字段（隐私回归测试）。DTO/OpenAPI 零变化：
- **PM 交接确认 ×2**（补齐用户点名的缺口；统一 `kind="checkpoint"`）：
  文案**只锚定真实存在的 checkpoint 数据**（supervisor_harness 的
  matching_input / matching_output.metrics）——注意：不得写"N 项硬条件由
  数据库强制执行"（remote/work_mode 被接受为硬约束但不进 SQL、
  need_visa_sponsor=false 不生成过滤子句）、不得引用 filter_log 当硬条件
  执行日志（它只记 avoid-role 剔除）：
  intent 完成 → PM："我确认小检接收的约束与确认单一致（matching_input
  checkpoint 支撑），交给小检执行。"；
  retrieval 完成 → PM："小检返回了 {候选数} 个候选，我核对了候选集、排序与
  证据完整性（matching_output.metrics 支撑：{ranking 数}/{证据数}），
  交给小策。"（快照缺失或受控重检场景不带数字；**checkpoint 为 warning 时
  用带提示的交接句，不复用 passed 文案**）；
- **执行 agent 播报改服务语态并带引导句**（内容由 approved_plan 真实数据
  渲染）：小检开工句在 `locations` 非空时加"你要求的 {locations} 我已锁定为
  硬条件，绝不放宽"（`remote=true` 路径换中性文案"你选择了远程方向，我按此
  筛选"——remote 不进 SQL 子句，不得称硬条件）；
  小策完成句加"如果你之后想让我基于某个岗位细化简历，可在结果卡提交反馈
  或开启新咨询"；
- 后端测试（现有锚点明确列出）：`test_conversation_api.py` 的三组序列锚定
  断言须同步更新（:117 kind 全序列、:127 位置索引、:277 中间态 persona
  序列）+ 新增：checkpoint passed/warning 双轨文案、候选数缺失/0/正数三态、
  快照私有字段不泄漏回归、PM 消息顺序与 seq 连续性、前端 e2e mock 消息流
  同步；**诚实约束**：数字只在快照有值时渲染，取不到用架构事实句。

**C. 结果后（引导闭环，前端）**
PM 结果消息下方渲染**行动 chips**：`查看第 1 名的证据 / 更新申请进展 /
新建咨询细化方向`——把"接下来该干嘛"变成一次点击（全部映射到已有交互，
零新端点）。

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
chips 化；真流式（SSE）；**run-input/状态机 API（小检/小策运行中真提问的
前置条件，Codex 六审确认归属）**。

**工期口径（v3）**：全量 P0 约 3–3.5 天（P0-9 约 +0.5–1 天：projector 增强 +
单测 + mock 同步 + PM 插话组件）；若 3 天为硬上限，
延后「消息分组与 hover 元信息」「侧栏本地标题」「空态三步卡」三项为 P0.5，
保住 P0-0、服务进度卡、槽位 chips、滚动保护、结果区证据/反馈、移动导航六件套。

## 五、实施清单与测试（v3）

六个提交批次：
1. P0-0 缺陷包 + fixture 契约修正（先红后绿）；
2. PM 群公告·服务进度卡 + 状态指示 + 滚动保护（plan_ready 的 stage="plan"、queued 的
   stage=null 分别映射，映射表按 status 优先并处理可空）；
3. 槽位 chips + 消息质感；
4. 结果区重构 + 简历展开 + 额度/空态（侧栏标题走自定义事件或 query
   invalidate 触发重渲——同 tab 无 storage 事件）；
5. **P0-9 角色主动性**（B 段后端投影 + projector 单测先行 → A/C 段前端
   PM 插话与行动 chips → e2e 消息流断言更新）；
6. 移动抽屉导航（`role="dialog"` + `aria-modal`、打开即入焦、**focus trap 或
   背景 inert**、Escape 关闭、焦点回归触发钮、背景滚动锁，配 Vitest/移动
   Playwright 断言）+
   Playwright 移动冒烟（**专用 spec/testMatch 只跑一条**，不让 mobile project
   重跑全部 e2e）。

测试账目（预计）：
- Vitest：slot 判定纯函数（含 visa=false 用例）、滚动 hook、stage 映射表、
  标题/last_run 本地键读写、手风琴 a11y 契约重写 ×3（净增 ~8）；
- Playwright：现有 6 场景维护（查看证据/关闭证据 → 手风琴断言；反馈按钮组
  文案；确认单按钮保持 accessible name 不变以免动 :257-266）+ 新增 4 场景
  （服务进度卡四段推进（底层七串）、chips 随咨询翻绿含"不需担保"、failed/stale/cancelled →
  「新建咨询重试」且断言产生新 session_id、侧栏切换后 run 恢复）+ 375px 移动旅程冒烟（新增 mobile project）；
- 每批次跑 typecheck / vitest / build / e2e 四门；OpenAPI 与 generated.ts
  零变化为硬验收。

## 六、验收标准（v3）
1. 运行期 5 秒内可见"四个角色谁在干活、到了哪一段"，且进度以 PM 群公告
   消息形态存在于群聊内（不是页面顶部的工程轨）；
2. 咨询任意时刻能说出"还差哪个槽位"，且"不需要签证担保"正确显示为已完成；
3. 结果区不点按钮即见排名层次与可信能力胶囊（无一句不可证实的声明）；
4. 运行中切侧栏再回来，运行轨与结果完好；失败后一键「新建咨询重试」；
5. 反馈四个按钮均发送合法 outcome 并获 202（mock e2e 断言词表 + 真实服务
   彩排各验一次——「真实入库」以彩排为准）；
6. 全程 UI 至少出现 4 条 PM 消息（**intent 交接 / retrieval 交接 / 核查
   checkpoint / 结果**——intro 被 P0-0 #5 跳过故不计入），两条新交接消息
   统一 `kind="checkpoint"`（与 intro-skip、recovery 渲染逻辑互不干扰）；
   执行 agent 播报含由真实数据渲染的引导句；
7. Playwright 10+ 场景 + 移动冒烟全绿；OpenAPI/generated.ts 零字节变化
   （projector 只新增消息行）。
