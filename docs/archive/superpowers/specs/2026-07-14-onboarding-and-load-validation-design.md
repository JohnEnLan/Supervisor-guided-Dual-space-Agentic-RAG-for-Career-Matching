# Career RAG 入场引导与负载验证设计

**日期：** 2026-07-14

**状态：** 用户已批准

**范围：** P0 前端入场体验，以及现有主流程的复杂业务、性能、并发和并行性验证

## 1. 目标

在不改变现有职业匹配业务契约的前提下，为 Career RAG 增加一个每次访问首页都会展示的三屏介绍体验。用户可以逐屏了解系统，也可以随时跳过并进入现有工作台。

同时建立可重复执行的验证套件，证明以下性质：

- 有目标与无目标两条 Intent Agent 路径均可完成。
- 多个 session 和 run 并发时状态、结果与反馈不会串联。
- SQL metadata 硬过滤先生成 allow-list；其后的 BM25 与 dense 分支真实并行，显式与隐式空间也并行读取，外部调用仍受 Semaphore 限流。
- 公开结果继续满足 JD evidence、隐私投影和解释能力边界。
- 性能测试不调用真实 LLM 或 embedding 服务，不消耗 API 额度。

## 2. 用户体验

### 2.1 路由

- `GET /`：始终显示三屏入场介绍，不读取本地“已看过”标记。
- `GET /workspace`：显示当前的简历上传工作台。
- 现有 `/sessions/*`、`/runs/*` 与 `/monitoring` 路由保持不变。
- 工作台导航中的“开始匹配”指向 `/workspace`。
- 品牌标识指向 `/`，用户主动返回首页时会再次看到介绍。

入场页不挂载工作台 `App` 布局，因此不会提前显示 7 阶段进度板，也不会为了渲染介绍页调用 `/api/v1/capabilities`。

### 2.2 三屏内容

#### 第一屏：系统用途

核心信息：Career RAG 将“简历与岗位相似度”升级为“有证据、可核查的职业决策”。视觉上展示简历证据、岗位证据和推荐结果之间的连接。

主操作为“了解它如何工作”，次操作为右上角始终可见的“跳过介绍”。

#### 第二屏：Agent 协作流程

展示三位业务 Agent 与 Supervisor：

1. Intent Agent 询问用户是否已有目标岗位或目标公司。
2. Matching Agent 执行硬过滤、混合检索与双空间融合。
3. Strategy Agent 生成简历策略、能力缺口和职业路径。
4. Supervisor 在有界循环内核查约束、证据和解释。

此屏提供“上一页”“继续了解”和“跳过介绍”。

#### 第三屏：可信与可解释

展示三项承诺：

- 每条岗位推荐必须包含 JD evidence。
- 匿名案例空间只影响已有显式候选的排序，不引入隐藏岗位。
- 公开结果不返回完整简历、内部提示词、供应商错误或 API Key。

主操作为“进入职业匹配工作台”，并保留“上一页”和“跳过介绍”。两个进入操作都导航到 `/workspace`。

### 2.3 动画与视觉

- 复用现有象牙白、海军蓝、青绿色与琥珀色设计令牌。
- 不使用渐变、背景视频、Canvas 或第三方动画库。
- 页面切换使用轻量 `opacity` 与 `transform`；流程节点使用延迟出现和连接线扩展。
- 每次切屏后将焦点移动到新屏标题，并用 `aria-live="polite"` 宣布当前页码。
- 在 `prefers-reduced-motion: reduce` 下关闭位移、连接线和延迟动画，仅保留即时状态变化。
- 所有交互控件高度至少 44px，375、768、1440px 宽度下无横向滚动。

## 3. 组件边界

### 3.1 新组件

`frontend/src/features/onboarding/OnboardingPage.tsx`

- 只管理当前屏幕索引，不持久化状态。
- 持有三屏静态内容、前进、后退和进入工作台行为。
- 不访问后端 API，不读取 `.env`，不接触用户数据。

`frontend/src/features/onboarding/OnboardingPage.test.tsx`

- 覆盖第一页、逐页前进、返回、跳过、最终进入、焦点管理和可访问标签。

### 3.2 现有文件调整

- `frontend/src/app/router.tsx`：将 `/` 与工作台布局拆开，新增 `/workspace`。
- `frontend/src/app/App.tsx`：品牌链接指向 `/`，“开始匹配”指向 `/workspace`。
- `frontend/src/styles/global.css`：增加入场页布局、三屏动画、响应式和 reduced-motion 规则。
- `frontend/e2e/full-flow.spec.ts`：业务主流程从 `/workspace` 开始。
- `frontend/e2e/onboarding.spec.ts`：真实浏览器覆盖介绍流程。

不修改后端公开 DTO，不修改 Agent prompt，不引入 P2 检索机制。

## 4. 测试与测量设计

### 4.1 前端单元与浏览器测试

- `/` 每次刷新都回到介绍第一页。
- 任意介绍屏点击“跳过介绍”进入 `/workspace`。
- 完成三屏后进入现有上传页，7 阶段进度板正常出现。
- 介绍页不请求 capabilities 或其他业务 API。
- 键盘可以完成前进、后退、跳过与进入操作。
- reduced-motion 模式下内容仍完整且没有依赖动画才能出现的元素。
- 375、768、1440px 均无横向溢出。

### 4.2 复杂业务测试

使用确定性的 LLM、embedding 与数据库替身覆盖：

- 有目标岗位/公司：Targeted consultation → Brief → Execute → Result → Explain → Reaction。
- 无目标：Explore 最多返回三个方向，选择方向不触发第二次 Agent 调用。
- 一次澄清后锁定约束；第二次澄清入口不存在。
- 旧 `plan_hash` 返回 409，并提供结构化恢复动作。
- 同一 run 竞争执行时只允许一次实际执行。
- 隐式证据异常、为空或置信度不足时保持显式排序。
- `job-hidden`、硬约束失败或无 JD evidence 的岗位不会进入公开推荐。
- `completed_with_warnings` 仍可读取结果，但公开 warnings 使用 allow-list。

### 4.3 并发测试

- 同时驱动至少 20 个 session、每个 session 1–3 个 run。
- 混合 targeted 与 explore 路径，并随机穿插 status/result/explain 请求。
- 断言 session_id、run_id、plan_hash、结果快照和反馈严格对应。
- 同一 run 发送并发 execute，断言只有一次成功启动，其余得到可恢复的 409。
- 测试只使用异步客户端与 `asyncio.gather`，不引入线程或多进程。

### 4.4 并行性测试

- metadata 硬过滤必须先完成并产生 allow-list，不与依赖 allow-list 的查询并行。
- 为 BM25、dense 两路以及显式、隐式两路分别设置可观测的受控延迟。
- 记录每个可并行分支的开始和结束时间，断言执行区间发生重叠。
- 每组并行总耗时必须显著小于组内延迟顺序相加，避免只检查函数是否调用。
- 为 LLM 和 embedding 替身记录同时活跃调用数，断言峰值不超过配置的 Semaphore，同时在负载允许时大于 1。
- 验证 `CancelledError` 继续传播，隐式分支普通异常才降级为显式排序。

### 4.5 性能测试

性能报告至少包含：请求总量、成功率、吞吐量、P50、P95、最大耗时、运行阶段耗时和峰值并发。

稳定自动化门槛：

- 受控依赖下 20 个并发完整业务 run 必须全部结束且无状态串联。
- 200 个只读 status/monitoring 请求必须无 5xx。
- 并行检索测试的墙钟时间不得退化为明显的顺序执行。
- 不把与机器性能高度相关的严格毫秒数作为 CI 唯一成功条件；实际 P50/P95 写入测试报告用于论文和后续比较。

## 5. 安全边界

- `.env` 继续由 `.gitignore` 排除，测试不得读取或打印真实密钥。
- 压力测试通过依赖替换拦截所有 LLM、embedding 和外部 HTTP 调用。
- 测试日志只记录合成 session/run ID、状态、时长和 allow-list 错误码。
- 前端构建只允许公开 `VITE_*` 配置；任何服务端 API Key 都不得使用 `VITE_` 前缀。
- 提交前扫描当前树与 Git 历史中的 API Key、私钥和意外 `.env` 跟踪。

## 6. 验收标准

1. 每次访问 `/` 都从介绍第一页开始。
2. 三屏逐页操作和任意位置跳过都能进入 `/workspace`。
3. 介绍页加载期间不调用业务 API。
4. 原有完整职业匹配流程和 7 阶段进度板不回归。
5. 新增单元、E2E、复杂业务、并发与并行性测试全部通过。
6. 生成一份不含敏感数据的性能测试摘要。
7. 完整后端测试、前端测试、类型检查、生产构建和 OpenAPI 检查通过。
8. 最终提交再次推送到 GitHub 与 GitLab 的同名分支。
