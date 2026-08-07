# Day 3 React 答辩工作台设计（中文版）

**日期：** 2026-07-12

**状态：** 已批准实施

**范围：** P0 React 答辩工作台、可见 Intent Agent 交互、服务端控制轮询、总阶段进度板，以及只读运行监控所需的最小后端契约

> 本文档与英文版 `2026-07-12-day3-react-workbench-design.md` 内容对应。实现时以两份文档共同表达的技术契约为准。

## 1. 目标与范围

构建一个用途单一的答辩工作台，完整跑通 P0 职业匹配流程：

```text
创建会话并上传简历
-> 审阅并确认归一化简历
-> 与 Intent Agent 交互
-> 确认 Match Brief
-> 执行 run 并支持恢复
-> 通过总阶段进度板查看当前阶段与已完成阶段
-> 查看一份有证据支撑的统一结果
-> 可选查看仅面向考官的双空间追踪
-> 提交轻量反应反馈
```

该工作台不是营销站。不包含价格页、账户设置、模型设置、RAPTOR 控件、alpha/beta 控件或 provider 配置。

## 2. 产品原则

1. **Intent Agent 必须可见、可纠正。** 它必须在用户确认 Match Brief 之前，帮助用户形成或校验职业方向。
2. **服务端是权威状态源。** 刷新后依靠 URL 标识符和公开 API 恢复体验；业务结果不存入浏览器全局变量或 localStorage。
3. **证据优先于置信表达。** UI 展示 JD 证据、简历证据、能力缺口和来源，不展示录用概率或保证性结果。
4. **研究细节逐步披露。** 普通用户看到一份连贯结果；仅考官可见的追踪数据放在 capability-gated 路由中。
5. **P0 保持有界。** 只实现一个工作台、一条主流程、最多一次澄清和确定性测试。
6. **监控是只读安全投影。** 监控页只展示聚合运行量、耗时、证据覆盖和双空间使用情况，不提供用户管理、数据修改或私有状态浏览能力。

## 3. 视觉系统

采用已选定的“明亮、专业、适合答辩投影的研究工作台”方向。

- 背景：暖象牙白与白色表面。
- 主色：深藏蓝，用于导航和主操作。
- 证据色：青绿色，用于表示有根据的证据和成功完成状态。
- 警告/恢复色：琥珀色；破坏性操作和失败状态使用克制的红色。
- 字体：使用以 `Aptos`、`Segoe UI` 和 `Noto Sans SC` 为主的系统字体栈，不依赖网络字体。
- 布局：紧凑的应用外壳、清晰的步骤导航、宽松的阅读宽度和有限层次阴影。
- 动效：仅使用短暂状态过渡，并遵守 `prefers-reduced-motion`。
- 禁止模式：营销式巨幅首屏、装饰性渐变、虚假进度百分比、过多卡片网格和无标签纯图标控件。

## 4. 应用架构

使用 Vite、React、TypeScript strict mode、React Router、TanStack Query、Vitest、Testing Library 和 Playwright。

```text
frontend/src/
  app/          应用外壳、路由、providers
  api/          OpenAPI 生成类型、fetch client、query options
  features/     session、brief、run、results、evaluation、feedback、monitoring
  styles/       design tokens 和全局响应式规则
```

路由：

```text
/                            创建会话并上传
/sessions/:sessionId/resume  简历审阅
/sessions/:sessionId/brief   Intent 交互与 Match Brief
/runs/:runId                 Run 状态与恢复
/runs/:runId/results         产品结果与证据
/runs/:runId/evaluation      考官追踪视图
/monitoring                   只读运行监控看板
```

URL 是恢复定位器。TanStack Query 在页面加载时重新获取相应服务端资源。刷新 Run、Results 或 Evaluation 页面时，不得依赖内存导航状态。

## 5. 有意义的 Intent Agent 交互

### 5.1 入口问题

用户确认简历后，询问：

> 你目前是否已有目标职业或目标公司？

用户选择 `targeted`（已有目标）或 `explore`（尚无明确目标）。

### 5.2 已有目标分支

用户可提供目标岗位、目标公司和自由文本背景。

Intent Agent 负责：

- 将目标职位名称归一化为 role families；
- 分离 hard constraints 和 soft preferences；
- 默认将目标公司作为 soft preference；
- 仅当用户明确要求时才使用“仅限目标公司”匹配；
- 总结有简历证据支持的优势和重要缺口；
- 仅当地点、签证或是否接受 Bridge Role 信息必要时，最多追问一个澄清问题。

### 5.3 尚无目标分支

Intent Agent 仅使用已确认简历的结构化内容和证据，返回不超过三个职业方向。每个方向包含：

- role family 和展示标题；
- 有证据支撑的推荐理由；
- 简历 evidence span IDs；
- 主要缺口；
- 适合的入门岗位。

用户在前端本地选择一个方向。该选择不再触发另一次 LLM 调用。如果三个方向都不合适，用户可切换到“已有目标”分支。

### 5.4 有界澄清与执行

服务端记录是否已使用唯一一次澄清机会。公开响应仅返回安全的问题和结构化理解，不返回 prompt、raw state、provider error 或完整简历文本。

当 run snapshot 包含已完成的 Intent 交互时，执行阶段跳过当前隐藏在 execute 内的 Intent Agent 调用。未使用交互接口、直接创建 Match Brief 的旧客户端仍保留现有 Intent Agent fallback，以保持 Day 2 向后兼容。

## 6. 公开 API 增量

### 6.1 Intent 交互

新增：

```text
GET  /api/v1/sessions/{session_id}/intent-consult
POST /api/v1/sessions/{session_id}/intent-consult
```

`GET` 在刷新后恢复最新的安全交互投影；当尚无交互时返回 404。`POST` 启动或继续有界交互。

请求字段：

```text
mode: "targeted" | "explore"
goal_text?: string
target_roles: string[]
target_companies: string[]
company_exclusive: boolean
clarification_answer?: string
```

响应字段：

```text
session_id: string
mode: "targeted" | "explore"
assistant_message: string
current_goal: string[]
long_term_goal: string[]
hard_constraints: typed public object
soft_preferences: typed public object
avoid_roles: string[]
directions: CareerDirection[]
needs_clarification: boolean
clarification_question?: string
clarification_used: 0 | 1
```

`CareerDirection` 包含 role family、标题、理由、简历 evidence IDs、主要缺口和入门岗位。核心请求与响应模型禁止额外字段。

服务端将每个方向中的简历 evidence IDs 与已确认简历证据集合进行校验，并丢弃不受支持的 ID。

交互状态保存在现有 session `SharedState` JSON 中，因此无需数据库 migration。

扩展 Intent Agent allow-list：将 `companies` 作为 hard constraint，将 `preferred_companies` 作为 soft preference。“仅限目标公司”模式映射为对 `jobs.company` 的不区分大小写 SQL metadata filter；默认目标公司模式只映射为 `preferred_companies`。公司单字段匹配绝不用于匿名案例证据匹配。

### 6.2 Match Brief 快照正确性

在 `create_run` 捕获 state snapshot 之前，Match Brief 路由必须先将用户最终确认的职业目标、hard constraints、soft preferences 和 avoid roles 写入 session career state。不可变 Match Brief 仍是执行权威来源。

### 6.3 服务端指导的轮询

在 `RunStatusResponse` 中新增 `retry_after_ms: int | null`：

- `queued` 和 `running`：返回正数轮询间隔；
- 终态：返回 `null`。

TanStack Query 将该值用作 `refetchInterval`，不硬编码虚假进度时长。

### 6.4 考官案例证据

扩展 allow-list Explain DTO，增加类型化案例证据，包含 case ID、最高求职阶段和存在时的置信度。不返回匿名简历 payload、prompt、raw log 或 provider error。

同一变更中刷新 `tests/snapshots/openapi_v1.json`，再从该 snapshot 重新生成 `frontend/src/api/generated.ts`。

### 6.5 总阶段进度与只读监控 API

`RunStatusResponse` 除 `stage` 外增加确定性的 `completed_stages` 与 `total_stages`，前端据此渲染阶段完成状态，不根据时间猜测百分比。阶段顺序固定为 `resume`、`intent`、`retrieval`、`strategy`、`verification`、`finalization`、`result`；未创建 run 前的 Resume 与 Intent 状态从 session API 获取，创建 run 后由 run status 接管。

在 `/api/v1/capabilities` 中增加 `monitoring_enabled`。仅当环境变量 `MONITORING_ENABLED=true` 时提供以下只读接口：

```text
GET /api/v1/monitoring/overview?window_hours=24
GET /api/v1/monitoring/runs?window_hours=24&limit=20
```

`overview` 返回窗口内运行总量、各状态数量、完成率、警告率、失败率、P50/P95 总耗时、各阶段 P50/P95 耗时、平均推荐数、JD 证据覆盖率、使用隐式案例的 run 比例和发生双空间重排的数量。`runs` 只返回 run ID、状态、当前阶段、时间戳、耗时、推荐数、warning codes 和安全错误码。

完成 run 时，从最终 state 和 Product Result 生成独立的 allow-list `run_metrics` 只读记录。监控查询只读取 `match_runs`、`run_events` 和 `run_metrics`，不读取或返回完整 `state_snapshot`、简历、prompt、provider error 或用户身份。P0 使用 5 秒轮询，不引入 WebSocket、Prometheus、Grafana 或新的任务队列。

## 7. 页面与交互设计

### 7.1 新建会话

- 在紧凑的侧栏中说明三步工作台流程。
- 提供标准 file input 和拖放区。
- 接受 PDF、DOCX 和 TXT。
- 创建 session，上传文件，然后导航到简历审阅页。
- 使用 `crypto.randomUUID()` 为现有 session-create 请求生成一个仅对当前 session 有效的不透明 visitor ID；不采集姓名或邮箱，不在浏览器存储中持久化该标识。
- 使用清晰的校验和上传状态，不模拟解析百分比。

### 7.2 简历审阅

展示 Skills、Experience、Education、Projects、Quality Warnings 和 Evidence。页面只有一个主操作：**确认简历**。次要操作可返回上传页，但不得在视觉上与主操作竞争。

### 7.3 Intent 交互与 Match Brief

页面首先显示“已有目标/尚无目标”问题和相应 Intent Agent 交互。解读完成或方向选择后，仅展示：

- career goal；
- locations；
- visa sponsorship requirement；
- role families；
- avoid roles；
- 已填写时的目标公司和 company-exclusive 选项；
- result count。

执行前展示 canonical brief 和缩短的 plan-hash fingerprint。不展示模型名、latent-space 控件、RAPTOR 或融合参数。

### 7.4 Run 页

展示真实阶段：Intent 交互完成、Retrieval、Strategy、Verification 和 Finalization。Run 页根据 `retry_after_ms` 轮询，在终态停止，并在刷新后从服务端恢复。

- `completed` 和 `completed_with_warnings`：导航或提供 Results 链接。
- `failed` 和 `stale`：显示安全错误码，并提供返回 Brief 或创建新 run 的操作。
- 网络中断：保留当前路由并提供重试。
- 非终态 result 返回 409：遵循公开 recovery payload 回到 Run status。

### 7.5 总阶段进度板

应用外壳在主流程页面持续展示七阶段进度板：简历、目标沟通、检索、策略、核验、结果生成、结果查看。桌面端使用带文字标签的横向 stepper；375 px 下压缩为“第 N/7 阶段”、当前阶段名称和可展开的阶段列表，禁止横向溢出。

已完成阶段显示完成标记；当前阶段显示真实服务端状态；未开始阶段保持中性。失败或 stale 状态停留在实际失败阶段，并显示恢复动作。进度板不显示基于时间推算的百分比，也不在刷新后倒退到浏览器默认状态。

### 7.6 Results 与 Evidence Drawer

只展示一份 recommendation list。选择推荐项后更新详情区，不创建第二份竞争性列表。

详情区包含标题、公司、地点、tier、简明解释、skill gaps 和打开 Evidence Drawer 的按钮。Drawer 展示：

- JD evidence；
- 提供时的 resume evidence；
- 从 required-skill evidence 字段确定性推导的 must-have hits；
- 相关 skill gaps。

通过 Escape、遮罩或关闭按钮关闭后，焦点必须返回到原始触发按钮。界面不展示录用概率或保证性结果。

### 7.7 Examiner View

仅当 `/capabilities` 返回 `explain_enabled: true` 时才显示该导航入口。capability 关闭时直接访问该路由，显示“不可用”状态和返回 Results 的链接。

开启时，展示 explicit rank、implicit rank、final rank、匿名案例证据、实际 implicit weight、stage durations、warnings 和 bounded recovery events。该视图在视觉上标记为“仅考官可见”，并与普通推荐详情分离。

### 7.8 Reaction

每个推荐项提供轻量 usefulness reaction。明确说明该反应仅记录在当前 session，不会自动发布为公共匿名案例。

### 7.9 运行监控页

`/monitoring` 是答辩与开发使用的只读观测页。顶部显示时间窗口选择和最后更新时间；主体显示运行量/状态、性能、结果质量和双空间使用四组指标，并提供最近运行表格。页面按服务端建议每 5 秒刷新，网络错误时保留最后一次成功数据并提供手动重试。

该页面只在 `monitoring_enabled` 开启时显示入口。关闭时直接访问显示不可用状态。P0 不提供删除 run、重放 run、修改状态、查看完整简历或任意 SQL 查询能力。

## 8. 可访问性与响应式行为

- 主流程的所有控件都可通过键盘到达和操作。
- 优先使用原生 input、button、heading、list 和 dialog 语义，必要时才增加 ARIA。
- 每个输入项都有持久可见的 label 和错误关联。
- 可见 focus ring 满足对比度要求。
- 文本满足 WCAG AA 对比度；证据/警告含义不得只依赖颜色。
- Evidence Drawer 打开时限制焦点，关闭后恢复焦点。
- 375 px 和 768 px 下使用单列布局，不出现横向滚动。
- 1440 px 下使用有界的列表/详情分栏和可读行长。
- 自动化 viewport 测试在 375、768 和 1440 px 下断言 `scrollWidth <= clientWidth`。

## 9. 错误与隐私边界

fetch client 将公开 validation 和 recovery payload 解析为类型化 `ApiError`。可展示安全 `detail`、`error_code` 和 recovery actions，但绝不渲染 provider payload、SQL error、prompt 文本、完整 `SharedState`、`user_id` 或完整归一化简历文本。

前端不记录简历内容。开发诊断仅可记录路由名、HTTP status、session ID 和 run ID。

## 10. 测试策略

### 10.1 类型与契约 Gate

- 使用 `openapi-typescript` 从 `tests/snapshots/openapi_v1.json` 生成类型。
- `api:check` 生成到临时位置，存在漂移时失败。
- TypeScript strict build 通过。
- 核心 API 请求和响应代码不得显式使用 `any`。

### 10.2 组件与功能测试

在每个页面或功能旁使用 Vitest 和 Testing Library，覆盖：

- 上传校验和导航；
- 简历各分区和唯一主确认操作；
- targeted 与 explore Intent 分支；
- 最多一次澄清；
- Match Brief 字段可见性和禁止控件不存在；
- 轮询间隔和终态停止；
- 根据路由标识符进行刷新恢复；
- failed/stale 恢复操作；
- 统一结果选择；
- Evidence Drawer 焦点恢复；
- capability-gated Examiner 路由；
- 总阶段进度映射、移动端折叠与刷新恢复；
- monitoring capability gate、聚合指标和最近运行安全字段；
- reaction 成功与安全错误处理。

### 10.3 Playwright

CI 使用确定性 route fixtures 覆盖完整流程和 capability on/off。在 375、768 和 1440 px 宽度下测试横向溢出。确定性测试不依赖 live providers。

为答辩演示保留独立的可选 live-backend smoke 流程。provider 或网络不稳定不得使标准前端测试产生波动。

## 11. 验收标准

Day 3 在以下条件全部满足时完成：

1. 前端仅消费 `/api/v1` 和生成的公开类型。
2. 键盘用户可从上传完成到 Results。
3. Intent Agent 可见地处理 targeted 和 explore 两个分支。
4. 已完成 Intent 交互的 run 在 execute 阶段不重复调用 Intent Agent。
5. 刷新后可从服务端恢复 Resume Review、Run、Results 和 Examiner 页面。
6. 轮询遵守 `retry_after_ms` 并在终态停止。
7. Results 提供可追溯证据，绝不展示录用概率。
8. Examiner 内容受 capability 限制，不包含私有 state。
9. Drawer 焦点恢复和 375/768/1440 溢出测试通过。
10. 总阶段进度板仅由服务端状态驱动，并能在刷新后恢复。
11. 监控页能展示运行量、成功/警告/失败率、P50/P95 耗时、证据覆盖和双空间使用率，且响应中不存在私有状态或简历内容。
12. 后端回归测试、前端单元测试、类型检查、build 和 Playwright 全部通过。

## 12. 明确不在范围内的内容

- 营销页、身份认证 UI、计费、账户设置，以及具有修改能力的管理员控制台；只读运行监控页属于本次范围。
- 公网监控部署、Prometheus/Grafana、WebSocket 推送和跨实例实时指标总线。
- 用户可选的模型/provider 配置。
- 正常 UI 中的 RAPTOR、cross-encoder、alpha/beta 或 latent-space 控件。
- 公共部署、生产 worker lease 或队列基础设施。
- 将 reaction 自动发布到匿名案例库。
