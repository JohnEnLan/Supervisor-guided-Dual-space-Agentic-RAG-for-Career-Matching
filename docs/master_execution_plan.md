# 总执行方案（Master Execution Plan v5 终稿 — 三方评审收敛，双 APPROVE）——W-A + W-B + W-C 融合执行

> 用户决策（2026-08-06）：**W-B 全量（10–12d 版）、W-C 纳入、论文 docx 本轮动**。
> 本文档是三个工作流的**唯一执行入口**：批次顺序、交叉件裁决、验收门、
> W-C 规格、终局审核流程都以本文为准。
>
> v1 → v2（子 agent 首轮 4 必改）：A 批次 9 保位 + 终局审核后强制"文档
> 数字复核 pass"；B 审核基线 = CLAUDE.md **经 CLAUDE_LANGGRAPH.md §5
> 修订后口径**（未修订口径会把 LangGraph/8 轮预算成批误判违宪）；
> C 模块清单补 app/state、app/domain、app/config + tests/e2e 抽查口径；
> D 工期如实：批次 5–7 上调 9–11d（v10 全量 10–12d 减批次 10 吸收份额）、
> 批次 10 加宽 1–1.5d、总账 **17–21d**；另修批次 8 幻影节号、OpenAPI
> 再生归属、论文 docx 输出路径与"待测"口径。
>
> v2 → v3（Codex 首轮 6 阻断 + 5 高危）：①OpenAPI 冲突正式裁决（W-A 零
> diff / W-B 批次限量加性 diff / 后续 W-A 验收口径"除已批 W-B diff 外零
> 额外"）；②批次 7 拆 7A 后端 P0-9B + 7B 前端（并补漏 P0-9C 行动 chips）；
> ③批次 5 拆 5A/5B/5C 各自独立四门+提交（"一次一个模块"硬约束）；
> ④**W-C 移到最后**（代码→总验收→全局审核修复→冻结→文档→DOCX 终验，
> 取代 v2 的"0.5h 复核 pass"——审核会改代码，文档必须是最后写阶段，
> 两评审同题收敛取更彻底修法）；⑤新增批次 0 提交三规范文档锁定基线
> SHA；⑥PASS 语义修正（3 轮=升级门，阻断/高危未解决只能 BLOCKED 待
> 用户裁决，修复后受影响模块旧 PASS 失效须重审）；⑦四门+补 pyflakes/
> export_openapi/api:check/迁移双验证；⑧W-C 指标来源勘误 + 功能详解
> 先改 .md 源稿再渲染 + 渲染脚本须编写入库；⑨审计清单改 git ls-files
> 生成；⑩工期标"最佳情形 17–21d + 审计修复缓冲 2–3d"。
>
> v3 → v4（子 agent 二审收口，约六行）：冻结语义限定 = 产品行为代码 +
> 实测工件（W-C 允许新增文档与文档工具脚本）；§3 指标来源统一勘误口径；
> Feature A 全部 DTO 变更落 5A、5B 纯内部逻辑（§0 获准集同步去 5B）；
> §2 交叉件更新新编号；批次 0 幽灵文件名给路径；"10 批"→13 提交单元；
> W-A 批次门加零 diff 廉价检查；W-C 放宽 2–2.5d。
>
> v4 → v5（Codex 二审 2 阻断 + 收口项）：①**执行序重排**——审核修复
> 前移，批次 9 总验收改为在最终 commit SHA 上完整执行并产出版本化验收
> 报告后才冻结（消灭"实测证据绑旧提交"）；②W-C 渲染脚本走三方 PASS；
> ③门禁命令写死（契约批加 api:generate；零 diff 门限定两个产物路径）；
> ④5A/5B/5C 边界精修（契约批=5A/6，5C 零 diff；跨轮覆盖竞态与
> supervisor_log/notes/coach_reservations 合并归批次 6；5A 澄清 SQL 新列
> 仅 generation 一个）；⑤批次 0 细节（integrated 标历史、SHA 走 git tag）；
> ⑥W-C 输出文件名写死；⑦工期消歧（含评审 18–22d，对外含缓冲 20–25d）。

## 0. 规范性引用（设计规格不在本文重抄）

| 工作流 | 规范文档 | 评审状态 |
|---|---|---|
| W-A 前端产品化 P0 | `docs/frontend_ux_redesign_plan.md` **v3.2** | 三方通过（子 agent 3 轮 + Codex 6 轮） |
| W-B 生产增强 P0 | `docs/production_enhancement_plan.md` **v10 终稿** | 三方通过（双线各 6 轮，9 条实施注见其 §10） |
| W-C 文档对齐 | 本文 §3（此前无独立规范文档） | 随本文评审 |

**融合原则**：两份已批规格逐字有效，本文不改其任何已裁决设计；若执行中
发现本文与规范文档冲突，以规范文档为准并回报。重抄会引入漂移——这是
六轮评审文化的直接延伸。

**唯一跨规格冲突的正式裁决（OpenAPI）**：v3.2 要求零 API diff
（:292/:307），v10 §4 要求有意加性再生——裁决为：
- W-A 独立批次（1–4、7B、8）与 P0-9B 投影本身：**零 API diff**；
- W-B 契约批次（**仅 5A/6**）：获准产生且**只能**产生 v10 §4 列明的
  加性 diff（各自契约门再生）；**Feature A 的全部 DTO 变更（phase 枚举
  +resume_clarify、clarification_progress、409 契约）落 5A**，5B/5C 纯
  内部逻辑**零 API diff**（否则 5B 开启开关的测试会因枚举缺失 500）；
- 后续所有 W-A 验收口径 = "除已批准的 W-B diff 外零额外变化"。

## 1. 批次计划（批次 0–9，共 **13 个提交单元**（5 拆三、7 拆二），串行推进，每单元一提交）

每批完成条件（"四门+"）：`pytest` 全绿 + `pyflakes` + 前端
`typecheck/vitest/build` + 涉及 e2e 的批次跑 Playwright +
**契约批次（5A/6）**：`scripts/export_openapi.py` →
`npm --prefix frontend run api:generate` → `npm --prefix frontend run
api:check` → 审查限定文件 diff（api:check 只校验不生成，缺 generate
则命令序列不可执行——Codex 二审精修）+
schema 批次（5A）做**新库建库 + 既有库 0007→新迁移升级**双验证 +
**零 API 批次（1–4、5B、5C、7A、7B、8）**：export 后仅检查
`tests/snapshots/openapi_v1.json` 与 `frontend/src/api/generated.ts`
两个路径零 diff（无路径限制的 git diff 会被本批正常代码改动触红）+
对侧审查通过 + Claude 终验，才提交并进下批。
执行分工（**用户 2026-08-06 修正案**）：**所有批次（前端与后端）统一为
Codex 执行 → Codex 自查（对照规格逐条核对 + 完整重跑本批门禁并出自查
报告）→ Claude Code 独立审查终验**。执行者与终审者分离由"Codex 自查 +
Claude 独立审查"两级保障；Claude 审查发现问题→打回 Codex 修复→重新
自查→再审，循环至通过。

| 批次 | 内容 | 规格来源 |
|---|---|---|
| 0 | **基线锁定**：提交三规范文档（v3.2 / v10 / 本文）+ `docs/integrated_execution_plan.md`（**顶部标注「历史盘点，已被 master v5 取代，非执行依据」**——其批次号与 13.5–16d 口径已过时）；SHA 用**提交后打不可变 git tag**（`plan-baseline-v1`）记录（同一提交无法自嵌自身 SHA） | Codex 首轮⑤ + 二审⑤ |
| 1 | W-A P0-0 现网缺陷包 + typed fixture builder（先红后绿） | v3.2 P0-0 |
| 2 | W-A 群公告进度卡 + 状态指示 + 滚动保护 | v3.2 P0-1/2/6 |
| 3 | W-A 槽位 chips + 消息质感 | v3.2 P0-3/4 |
| 4 | W-A 结果区重构 + 简历档案展开 + 额度/空态 | v3.2 P0-5/7/8 |
| 5A | W-B Feature A ①数据契约/generation 生命周期：**quality_issues_struct/targets/pending/clarifications/spans 均为 app/state/schema.py 的 JSON/Pydantic 状态字段；SQL 新迁移列只有 `resume_upload_generation` 一个**（防误建多列）+ Feature A 全部 DTO（phase 枚举/progress/409 契约）+ 受理单条 UPDATE + preview/confirm 收紧 + 后台 no-op + 迁移双验证 | v10 §1.3/§4 + §10 注 |
| 5B | W-B Feature A ②澄清阶段机与竞态：触发器 → 槽位先行 + 轮内顺序 → pending 锚点 + 跳过 + summary 校验 → CAS 白名单扩展（**仅 Feature A 澄清字段**：clarifications/spans/targets/pending/questions_used）→ Feature A 竞态测试（202 窗口/finalize 在途/两读重传）——**跨轮覆盖竞态（CAS2×persist_turn）与 supervisor_log/supervisor_notes 并集合并、coach_reservations 单调合并归批次 6** | v10 §1.1–1.3 |
| 5C | W-B Feature A ③消费闭环：三 helper + 消费者逐函数切换 + 隐私测试（澄清任何内容不进 implicit query）——**零 API diff**（Feature A 契约已全部在 5A 落地） | v10 §1.4 |
| 6 | W-B Feature B：L1 事实 + L2 教练（reservation 状态机、CAS2 前提、fail-open）→ supervisor_notes 内嵌 + POST 时序 → verdict 双落 + OpenAPI 加性再生（Feature B 份额） | v10 §2 + §10 注 |
| 7A | 角色主动性合并件（后端）：P0-9B——conversation_projector.py 运行期 PM 交接确认 + runs.py 快照白名单 context 提取 + 隐私与消息序列测试（零 API diff） | v3.2 P0-9B |
| 7B | 角色主动性合并件（前端）：P0-9A 即时插话保留 + **P0-9C 结果后行动 chips** + PM note 气泡渲染 + 滚动锚点 + 第四枚澄清 chip（answered/skipped/remaining）+ finalizable 行动条（CTA 永不隐藏）+ 409 双旅程恢复 UX（两段式提示）+ turn.isPending 禁 finalize | v10 §3 + v3.2 P0-9A/C |
| 8 | W-A 移动抽屉导航 + 移动冒烟 | v3.2 §五批次 6 + P0-7 断点件 |
| 9 | 总验收（**在全局审核修复之后、于最终 commit SHA 上执行**）：全量 pytest + 前端四门 + e2e 全场景 + **四组合开关测试（00/10/01/11）** + 真机彩排 P1–P4（P4 = 简历含糊者走完整澄清→引导→回填→匹配→C### 证据引用 + PM 三类触发逐一演示）+ 32 项全局冒烟复跑 + **终局切换**：`.env` 开启 RESUME_CLARIFY_ENABLED + CONSULT_COACH_ENABLED 后重跑彩排 + **版本化验收报告** | v10 §8/§9 + 既有套件 |

**执行序（v5 重排，消灭"实测证据绑旧提交"）**：批次 0–8 实现 →
**全局逐段审核 + 修复**（§4）→ **批次 9 总验收在最终 commit SHA 上
完整执行**（四组合 + P1–P4 彩排 + 32 项冒烟 + 终局切换全在最终代码上
跑，产出**版本化验收报告**：SHA、四组合结果、测试计数、P1–P4 run id、
32 项结果、无秘密配置快照）→ **冻结** → **W-C 文档阶段**（§3，文档是
最后一个写阶段）→ DOCX 全页视觉与目录终验。
**批次 9 失败回路（终审注 1）**：彩排/冒烟暴露 bug → 修复 → 受影响模块
旧 PASS 失效重审 → **在新 SHA 上重跑完整批次 9 并重出验收报告**（SHA
变则旧报告作废，无捷径）。
**竞态测试批次归属（终审注 4）**：受理写并发、queued 期 preview/confirm、
A/B 乱序 → 5A 门；202 窗口、两读重传 → 5B 门（全集见 v10 §8）。

5A/5B/5C 各自独立红测、四门+、审查与提交（"一次一个模块"硬约束）。
**OpenAPI 再生归属**：**5A/6** 按各自契约门再生，合并记作 v10 §4 所称
"有意再生"的本工作流总变更；W-A 批次验收口径见 §0 裁决。

## 2. 交叉件裁决（已在两规格中定稿，此处只列执行提醒）

1. can_finalize PM 卡：批次 1–4 期间维持 v3.2 形态；批次 **7B** 改造为
   "后端 finalizable note 存在时收缩为仅含 CTA 的行动条"（v10 §3）；
2. 第四枚 chip 与 last_run 持久化互不依赖，可并行；
3. 409 resume_changed 恢复旅程依赖批次 **5A** 的后端契约——批次 7B 排在
   5A–6 后的原因；
4. e2e fixture：批次 1 的 typed builder 是后续所有前端批次的地基，
   批次 **5A/6** 的 DTO 加性变化须同步 fixture（5C 零 API diff）（v3.2 已列漂移清单
   机制）。

## 3. W-C 文档对齐规格（本轮新增规范）

**时序（v5 定稿）**：W-C 在 全局审核修复 → 总验收（最终 SHA）→
代码/实测工件冻结 **之后**执行——文档是最后一个写阶段，对齐对象 =
通过总验收的冻结态，验收报告即文档引用数字的可核来源。对齐基准 = 冻结时的实际代码与实测数据；
铁律沿用：不虚构能力、不虚构数字，指标引用可核来源
**`data/eval/demo_corpus_cross_v1/` + `docs/validation/2026-08-06-cross-encoder-ablation.md`**
（Codex 勘误：非 outputs/），新特性数字若无实测则如实写"待测"。

1. **README.md** 重写：删除 Examiner View / 旧 e2e 叙述；以"当前真实
   能力 + 快速启动 + 架构图 + 测试与评估入口"为骨架；
2. **docs/code_guide.md** 重写：以《功能与代码详解》为蓝本收敛（删除
   onboarding 电影页、"314 项测试"等过时事实，测试数以当时实际计数为准）；
3. **docs/product_guide.md** 重写：页面清单对齐群聊工作台现状 + 新增
   澄清回路与 PM 督导的用户可见行为说明；
4. **《功能与代码详解_V2.docx》回写**：**先改 Markdown 源稿**
   `docs/project_functionality_and_code_guide.md`（自称 Word 源稿），
   新增章节——澄清回路、PM 督导、generation 生命周期、双开关语义；
   再渲染 DOCX——**渲染脚本须编写并入库**（`scripts/render_guide_docx.py`，
   python-docx；此前渲染脚本未入库，Codex 实查仓库无现成脚本）+
   Word COM 逐页渲染检查门；
5. **毕业设计介绍 docx**：升级到 V2 现实——补群聊工作台、认证与配额、
   咨询引擎、检索双增强（RAPTOR + cross-encoder 及消融数字，**数字只引
   本节头部勘误的两个可核来源，无实测一律写"待测"，不得现编**）、
   本轮两特性（澄清回路 = 归一化质量信号驱动的主动澄清；PM 督导 =
   咨询期 supervisor 空白的填补，呼应"Supervisor-guided"标题）。
   **用户已确认四点（2026-08-06，取代此前默认值）**：
   ①基稿 = **对比 `毕业设计介绍_v7.1_核对修正版.docx` 与
   `毕业设计介绍_v7_架构优化版.docx` 两版**，先做逐章差异盘点、判定哪版
   更贴合当前系统实况，以其为主基稿、另一版的优质段落择优并入（盘点
   结论一并交付用户）；②**独立的 `毕业论文.docx` 本轮也动**——先读全文
   定位其与毕业设计介绍的分工与重叠，按同一 V2 现实口径同步更新（同产
   新版本文件不覆盖原稿）；③篇幅 = 扩节优先、新增章节仅限两个新特性、
   页数不设硬上限；④**行文口径 = 简单易懂**：面向非本方向读者，少用
   复杂术语，术语首次出现给一句白话解释，长句拆短句，机制先讲"为什么/
   干什么"再讲"怎么实现"。
   **输出文件名写死（Codex 二审⑥）**：`毕业设计介绍_v8_V2完整版.docx`
   与 `毕业论文_v2_更新版.docx`，均放父目录不覆盖旧版；仓库副本
   `backups/毕业设计介绍_v8_V2完整版.docx`、`backups/毕业论文_v2_更新版.docx`
   纳入版本控制（论文在 git 之外，双远端推送保护不到它）；渲染后
   Word COM 校验页数与目录。

## 4. 全局逐段代码审核（批次 8 之后、批次 9 总验收**之前**——v5 重排）

1. **逐段审核**：审计清单**由 `git ls-files` 生成**（生产源码全集，
   不手写目录白名单——手写清单已两次漏项：app/state/app/domain/
   app/config、app/graph/app/serve.py/frontend/src/app/features/styles）；
   tests/ 与 frontend/e2e 按"新增/改动文件全查 + 存量抽查 20%"口径。
   每模块产出：bug 清单（置信分级）+ 产品逻辑偏移判定；
2. **审核基线（必改 B）**：CLAUDE.md 硬约束**经 CLAUDE_LANGGRAPH.md §5
   V2 修订案修订后的口径**（未修订口径会把 LangGraph、咨询 8/15 轮预算
   成批误判违宪）+ 三规范文档 + CLAUDE_LANGGRAPH.md 本身；
3. **修复**：确认的 bug 即修（红测试先行），偏移项回报用户裁决（不
   擅自改设计）；
4. **收敛判据（v3 修正 PASS 语义）**：Claude 全模块过 + 子 agent 复核
   过 + Codex 复核过，三方各自明确输出 PASS 才结束；**全局 3 轮是升级门
   而非豁免门**——任何未解决的阻断/高危问题都不得 PASS，只能进入
   `BLOCKED/待用户裁决`；仅低风险项可在用户明确接受后列遗留清单；
   **修复后受影响模块旧 PASS 自动失效，须重审**；最后一轮修复后强制
   重跑回归：全量 pytest + 前端四门 + e2e 冒烟子集；
5. 审核收敛 → **批次 9 总验收在最终 SHA 上完整执行 + 版本化验收报告**
   → **冻结**（冻结面 = 产品行为代码 app/ + frontend/src + 实测工件；
   W-C 阶段**允许**新增文档与文档工具脚本如 scripts/render_guide_docx.py，
   但该脚本**同样走 Claude/子 agent/Codex 三方 PASS**（修后重审——
   "所有代码三方 PASS"无例外，Codex 二审阻断 2），**禁止**触碰行为面）
   → 进入 W-C 文档阶段（§3）→ DOCX 全页视觉与目录终验。

## 5. 工期与里程碑

| 阶段 | 估计 |
|---|---|
| 本文评审收敛（≤3 轮） | 0.5d |
| 批次 0（基线锁定） | 0.1d |
| 批次 1–4（W-A 主体） | 3–3.5d |
| 批次 5A/5B/5C + 6 + 7A/7B（W-B + 合并件） | **9–11d**（= v10 全量 10–12d 减去批次 9 吸收的四组合测试与 P4 彩排约 1d——用户选全量，不按压缩版排期） |
| 批次 8 | 0.5d |
| 全局逐段审核 + 修复 | 1.5–2d |
| 批次 9 总验收 + 终局切换（审核后、最终 SHA 上） | **1–1.5d**（全量 e2e + 四组合 + P1–P4 彩排 + 32 项冒烟 + 切换后重跑 + 验收报告） |
| W-C 文档阶段（审核后冻结执行；README + 两 guide + 功能详解源稿/DOCX + 渲染脚本编写入库 + 毕业设计介绍双版对比升级 + **毕业论文.docx 同步更新（用户 2026-08-06 追加）** + 终验） | 2.5–3d |
| **合计** | **最佳情形 18–22d（含本文评审 0.5d；不含则 17.5–21.5d）**；另留**审计修复缓冲 2–3d**，对外计划口径 **20–25d**（W-C 三 Word + 四 Markdown 与三方全仓审核按零严重缺陷估算是最佳情形——如实标注） |

## 6. 风险与回滚

- 每批一提交、双远端推送；批次内失败不跨批污染；
- W-B 双开关默认关进主干，终局切换只改 .env（运行时行为等价已由四组合
  测试锁定，回滚 = 关开关）；
- 论文 docx 产新文件不覆盖旧版；
- 会话中断恢复：本文 + 两规范文档 + git log 即完整现场。
