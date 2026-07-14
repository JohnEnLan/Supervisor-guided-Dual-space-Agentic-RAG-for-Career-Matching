# Career RAG 电影化职业远征入场体验设计

**日期：** 2026-07-14

**状态：** 用户已批准方向、叙事、视觉、静音与性能边界，等待书面规格复核

**范围：** 仅重构 `/` 入场体验；`/workspace` 及现有 Session、Run、Result、Evaluation、Monitoring 流程保持不变

## 1. 设计命题

### 1.1 具体对象

- **主题：** 一次由证据导航的职业远征。
- **受众：** 求职者，以及需要理解论文机制的答辩评审者。
- **页面唯一任务：** 让用户在进入工作台前理解系统为何存在、如何协作、如何守住证据与隐私边界，并产生“正式启程”的情绪动机。

### 1.2 核心表达

页面不是产品营销轮播，也不是太空粒子背景上的普通功能卡片。它是一张随着滚动逐步完成的职业星图：简历证据成为坐标，目标成为方向，三个 Agent 成为协作舰队，双空间成为两条导航信号，Supervisor 成为不可绕过的安全门。

最终宣言固定为：

> 未来不由模型决定，但每一步都应有证据。

## 2. 目标与非目标

### 2.1 目标

1. 将当前三屏按钮轮播改为七段滚动式电影化长页面。
2. 使用连续镜头、匹配转场与逐步构建的职业星图形成完整叙事，而不是散落的装饰动画。
3. 明确展示 Intent Agent 的两条用户路径：已有目标与探索未知。
4. 保留 JD evidence、匿名案例只重排显式候选、硬约束不可绕过、公开结果隐私投影等论文核心语义。
5. 保持首页零业务 API、明显跳过入口、键盘可达、移动端可用和 reduced-motion 完整降级。
6. 不新增重型依赖，并避免滚动时每帧触发 React 渲染。

### 2.2 非目标

- 不修改工作台、Agent prompt、公开 API、数据库或检索算法。
- 不加入声音、视频、Canvas、WebGL 或第三方动画库。
- 不加入自动播放、强制滚动、滚动劫持或无法跳过的片头。
- 不为了效果增加 P2 RAPTOR、cross-encoder 或新的后台功能。

## 3. 七段远征叙事

### Scene 1 — 序章：远方

- **使命文案：** “职业不是一次匹配，而是一条需要证据导航的航线。”
- **镜头：** 黑场中出现少量星点，远方地平线缓慢亮起；标题以电影片名节奏进入。
- **星图变化：** 仅出现一个尚未命名的出发点。

### Scene 2 — 迷雾：相似度的边界

- **使命文案：** “相似，不等于适合；排序，也不能替你决定未来。”
- **镜头：** 多条模糊航线短暂出现，其中缺乏证据的路线逐步熄灭。
- **产品语义：** 说明传统简历—岗位相似度不能独立承担职业决策。

### Scene 3 — 定位：真实经历成为坐标

- **使命文案：** “从已经发生的经历出发，才有资格谈下一步。”
- **镜头：** 技能、项目、教育、经历与原文证据依次成为星点，并由细线组成个人星座。
- **产品语义：** 展示 `evidence_spans` 是后续推荐和简历建议的真实性依据。

### Scene 4 — 方向：目标或探索

- **使命文案：** “有方向，就校准目标；没有方向，就先探索可能。”
- **镜头：** 星图分成两条可理解的航线：目标岗位/目标公司，以及最多三个探索方向，随后汇回同一任务路径。
- **产品语义：** 解释 Intent Agent 与用户交互的必要性，而不是把它表现为后台自动步骤。

### Scene 5 — 舰队：Agent 协作

- **使命文案：** “理解、检索、规划，各由一位 Agent 负责。”
- **镜头：** Intent、Matching、Strategy 从不同方向沿轨道进入；Supervisor 最后在中央点亮并建立监督环。
- **产品语义：** 三个业务 Agent 是三次不同 system prompt 的 LLM 调用，共享结构化 state；Supervisor 使用有界核查循环。

### Scene 6 — 导航：双空间与安全门

- **使命文案：** “岗位证据给出道路，匿名案例帮助校准，但没有任何信号能穿过硬约束。”
- **镜头：** 显式岗位空间与匿名案例空间同时延伸，汇入 Supervisor gate；地点、签证、经验、学历和岗位状态形成门上的约束标记。
- **产品语义：** 案例证据只能重排显式候选，不能引入已被过滤的岗位。

### Scene 7 — 启程：证据誓言

- **使命文案：** “未来不由模型决定，但每一步都应有证据。”
- **镜头：** 所有星点和航线汇成一条通向远方的最终路径；主 CTA 在路径终点出现。
- **主操作：** “进入职业匹配工作台” → `/workspace`。
- **隐私承诺：** 不返回完整简历、内部提示词、供应商错误或 API Key。

## 4. 视觉系统

### 4.1 色彩令牌

| 名称 | 色值 | 用途 |
|---|---|---|
| Void | `#060B18` | 深空背景 |
| Expedition Navy | `#0B1936` | 舞台、轨道与结构层 |
| Starlight Blue | `#70B7FF` | 主航线和激活章节 |
| Navigator Teal | `#5EEAD4` | 证据与可信状态 |
| Oath Gold | `#D8B66A` | 使命宣言、Supervisor gate 与最终 CTA |
| Cold White | `#EDF4FF` | 主标题与星光 |

颜色不单独承担状态表达；激活节点同时使用形状、文本或线型变化。

### 4.2 字体角色

- **使命标题：** Bahnschrift Condensed，使用大字号、紧凑行高和克制字重。
- **中文正文：** Aptos / Segoe UI / Noto Sans SC，保证长文阅读。
- **坐标与证据标签：** Cascadia Mono，用于 stage 编号、证据 ID、轨道状态和章节导航。

### 4.3 标志性元素

唯一核心标志是“逐章完成的职业星图”。星点必须带有真实语义标签，例如 `SKILL`、`PROJECT`、`JD EVIDENCE`、`CASE SIGNAL`，避免成为可替换到任何科技网站的通用星空。

## 5. 电影化运动语言

### 5.1 镜头规则

- 每段场景至少占一个视口高度，星图舞台在桌面端保持 sticky。
- 滚动推进景别：背景层移动最少，航线层适中，前景文字移动最多，形成有限视差。
- 场景间使用匹配转场：证据线成为职业航线，职业航线成为 Agent 轨道，Agent 轨道汇入双空间安全门。
- 不使用随机弹跳、连续旋转卡片或每个元素各自循环的分散动效。

### 5.2 动画类型

- SVG 路径使用 `stroke-dashoffset` 完成航线绘制。
- 星点使用 `opacity` 与轻微 `scale` 苏醒。
- 场景文字使用小幅 `translateY` 与交错透明度进入。
- Agent 使用轨道方向一致的 `translate` 入场。
- Supervisor gate 只执行一次扫描；最终信标使用低频呼吸，不持续闪烁。
- 主要动画只使用 `transform`、`opacity` 与 SVG stroke 属性，避免布局抖动。

## 6. 组件与数据流

### 6.1 文件边界

- `frontend/src/features/onboarding/CinematicOnboardingPage.tsx`
  - 管理 active chapter、滚动进度和首页结构。
- `frontend/src/features/onboarding/CareerConstellation.tsx`
  - 渲染语义化 SVG 星图；只接收章节与进度，不访问 API。
- `frontend/src/features/onboarding/MissionScene.tsx`
  - 渲染七段场景的标题、正文和语义标签。
- `frontend/src/features/onboarding/ChapterNavigation.tsx`
  - 渲染章节进度、锚点导航和当前章节状态。
- `frontend/src/features/onboarding/onboardingContent.ts`
  - 保存静态中文文案和章节元数据。
- `frontend/src/styles/onboarding-cinematic.css`
  - 隔离电影化布局、SVG 状态、动画和响应式规则。

旧 `OnboardingPage.tsx` 在路由切换后删除，避免并存两套入场逻辑。

### 6.2 状态与事件

1. 首次渲染只读取静态内容，不访问后端、不读 storage。
2. `IntersectionObserver` 在章节越过舞台阈值时更新 `activeChapter`。
3. 被动 scroll listener 只收集滚动位置；单个 `requestAnimationFrame` 将归一化进度写入 CSS 自定义属性。
4. React state 仅在 active chapter 改变时更新，不在每帧滚动时更新。
5. Chapter navigation 使用普通锚点；浏览器原生滚动仍由用户控制。
6. “跳过远征”和最终 CTA 均使用 React Router `Link` 导航到 `/workspace`。

### 6.3 失败与降级

- `IntersectionObserver` 不可用时，所有章节仍按普通文档流显示，章节导航保持可点击。
- JavaScript 延迟加载时，核心标题、正文、跳过入口和工作台入口仍应存在于首次 React 渲染结果中。
- 动画状态不能决定内容是否存在；动画失败只影响表现，不阻断导航。

## 7. 性能预算

- 不新增运行时依赖，不加载声音、视频、位图背景、Canvas 或 WebGL。
- 动态 SVG 图元控制在 72 个以内；不为每颗背景星创建持续运行的独立 React 状态。
- 不在 scroll handler 中读写布局并循环修改多个元素。
- 非当前章节暂停循环动画；移动端减少背景层与持续星点数量。
- 相比当前构建，主 JavaScript gzip 增量目标不超过 15 kB。
- 保留首页零 `/api/v1/**` 请求的浏览器断言。
- 不使用严格 FPS 或单机毫秒数作为 CI 唯一门槛；通过无长任务式实现约束、事件触发次数和真实浏览器检查共同验证。

## 8. 无障碍与响应式

- 页面保留一个主 `h1`；后续场景使用顺序 `h2`。
- 章节导航使用可读链接和 `aria-current="step"`，不能只有圆点。
- 滚动时不自动移动键盘焦点，也不抢夺滚动位置。
- 所有控制至少 44 × 44 px，焦点环在深色背景上清晰可见。
- `prefers-reduced-motion: reduce` 下取消视差、路径绘制、扫描与延迟，直接显示每一场景的最终状态。
- 375px：星图成为非 sticky 的顶部罗盘，章节按普通文档流阅读。
- 768px：保留简化 sticky 舞台，减少前景层。
- 1440px：使用双栏电影舞台与完整职业星图。
- 三种宽度均不得出现横向溢出或 CTA 被固定元素遮挡。

## 9. 测试策略

### 9.1 单元/组件测试

- 恰好渲染七个具名章节。
- 章节内容覆盖目标/探索分支、三个 Agent、Supervisor、双空间、硬约束和隐私承诺。
- 跳过入口与最终 CTA 均指向 `/workspace`。
- Chapter navigation 正确反映 active chapter。
- reduced-motion hook/状态不会移除内容或导航。

### 9.2 Playwright 浏览器测试

- `/` 不请求任何 `/api/v1/**`。
- 滚动到各章节时 `aria-current` 与星图 `data-chapter` 更新。
- 航线动画使用允许的 transform/opacity/SVG stroke 属性，不依赖 width/height 动画。
- reduced-motion 下路径与场景立即到达最终状态。
- 键盘可访问跳过、章节导航和最终 CTA。
- 375、768、1440px 无横向溢出。
- 刷新 `/` 回到序章，不使用 localStorage/sessionStorage 跳过。

### 9.3 回归门

- OpenAPI 类型检查、Vitest、TypeScript、Vite build 和完整 Playwright 通过。
- `/workspace` 与现有完整业务 E2E 保持通过。
- 对比构建产物，确认没有新增第三方动画依赖且 gzip 增量在预算内。

## 10. 验收标准

1. 首页成为七段、滚动驱动、静音的电影化职业远征。
2. 动画形成一条持续构建的职业星图叙事，而不是零散装饰。
3. 用户能理解系统使命、Intent 交互、三 Agent、Supervisor、双空间、硬约束、证据和隐私边界。
4. 用户可随时跳过，滚动和焦点不被劫持。
5. 首页无业务 API、无持久化“已看过”状态、无声音/视频/Canvas/动画库。
6. reduced-motion、键盘和三档响应式验收通过。
7. 完整前端回归、业务流程和生产构建通过。
