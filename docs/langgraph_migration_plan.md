# LangGraph 迁移计划书（v2 定稿 · 已经 Codex 对审修订）

> 状态：定稿。流程：Claude 起草 v1 → Codex 对审（判定：修订后执行）→ Claude 采纳修订 → 本 v2 为实施依据。
> 配套宪法：`CLAUDE_LANGGRAPH.md`（langgraph 分支，随本次修订同步更新）。
>
> **本轮范围决断（指挥方裁定）**：实现"手动 checkpoint 续跑能力"（用测试证明进程重启后可从 checkpoint 续跑），
> **不**实现自动恢复 worker/lease/启动重调度——那属于 Release-1 工程化（见 known_issues #10）。
> 因此现有 279 项测试语义（含 `execution_durability="process_local"` 能力声明与启动 stale 回收）**零例外保留**。

---

## 1. 为什么要迁移（必要性论证）

### 1.1 产品化视角（迁移的主因）

当前编排层是 ~600 行自研 orchestrator + ~260 行 supervisor_harness。它对毕设是优点（可讲解、零依赖、行为可控），但对**毕设之后的产品化与长期维护**存在结构性短板：

1. **持久化恢复是半成品。** 现在"提交后轮询 + 进程内 BackgroundTasks"，进程重启 in-flight run 直接丢失。LangGraph 的 checkpointer（PostgresSaver）把"每个节点执行完落一次可恢复快照"变成框架默认行为，崩溃恢复、断点续跑、time-travel 调试免费获得——这正是我们自研路线上最贵的一块（自己做等于重写一个 mini-checkpointer）。
2. **生态与人才兑换率。** 开源成熟框架意味着：社区文档、既有运维经验、招人时"会 LangGraph"是简历可筛选项、上下游工具（LangSmith 类观测、streaming、human-in-the-loop 中断）即插即用。自研 Harness 每个新维护者都要从零读代码。
3. **演进成本。** 后续产品方向（多用户队列、人工介入审核、可视化编排、A/B 编排策略）在 LangGraph 里是"加节点/加边/换 checkpointer"，在自研层里每一项都是新的架构工程。
4. **论文双叙事红利。** 主线保留自研 Harness，分支给出 LangGraph 等价实现 + 对照实验（行为一致性、恢复能力、代码量对比），毕设从"实现了一个系统"升级为"实现并对比了两种编排范式"——这是加分项而不是风险项。

### 1.2 诚实的反方论点（不回避）

- **依赖风险**：LangGraph API 迭代快，锁版本可控但升级有成本。
- **可解释性**：答辩时"自己写的每一行都能讲"优于"框架黑盒"。→ 缓解：主线不动，答辩以主线为准。
- **约束表达**：我们的"每类恢复最多 1 次"在 LangGraph 里要用条件边 + 计数器显式表达，写错反而更隐蔽。→ 缓解：240 项既有测试作为行为不变量，图版必须全绿。

### 1.3 结论（对审后降调）

诚实定位：**这是一次论文/工程化可行性对照实验，附带验证 checkpoint 恢复能力；不是当前 P0 的必要重构。**
"崩溃恢复/time travel 免费获得"是夸大——checkpoint 只给恢复原材料，自动续跑还需恢复扫描/worker/lease（本轮不做）；
代码量未必显著下降（orchestrator 大量代码是业务审计与投影，框架不消除）；"人才兑换率"是推测性收益不作工程论据。
对审补充的反方成本一并承认：第二套 PG 驱动与连接池、checkpoint 含 PII 副本（需保留期与删除联动）、
sync durability 延迟、节点重放的 LLM 成本、跨版本恢复兼容。在"主线不动、分支迁移、279 测试为锚"前提下仍**值得执行**。

## 2. 目标与不变量

| 类别 | 内容 |
|---|---|
| 目标 | `langgraph` 分支上，run 执行路径由 LangGraph `StateGraph` 驱动，接入 `PostgresSaver` checkpoint，行为与主线一致 |
| 不变量 1 | `/api/v1` 全部契约不变，OpenAPI 快照零漂移（`tests/snapshots/openapi_v1.json`） |
| 不变量 2 | 全部 **279** 项测试原样冻结（不许删改旧断言）；图等价性由新增特征测试与黑盒等价测试证明 |
| 不变量 3 | CLAUDE.md 其余硬约束全部保留：SharedState 单一事实来源、SQL 硬过滤、evidence 边界、Semaphore 限流、有界恢复各 ≤1 次 |
| 不变量 4 | Agent 本体（intent/matching/strategy 的 prompt + LLM 调用）零改动，LangGraph 只接管编排 |
| 明确不做 | 不引入 LangChain 全家桶/LangSmith/LangServe；意图咨询（Brief 确认前的图外交互）不进图 |

## 3. 现状 → 目标映射（对审修订版）

### 3.1 技术选型（对审确定）

- Checkpointer：官方 `AsyncPostgresSaver`（`langgraph.checkpoint.postgres.aio`），接受第二套驱动
  （psycopg3 + psycopg-pool，独立异步池，lifespan 管理，首次部署 `await checkpointer.setup()`）。
  "复用同一个 PostgreSQL" 指同库同 DSN，**不是**复用 asyncpg 池。禁同步 PostgresSaver 于异步路径。
- 调用形态：`await graph.ainvoke(state, config={"configurable": {"thread_id": run_id}, "recursion_limit": 12}, durability="sync")`
  （sync durability 兑现"节点完成即可恢复"）。
- 版本锁定：`langgraph==1.2.9`（1.2.10 发布仅一天，观察期不足）、`langgraph-checkpoint-postgres==3.1.0`、
  `psycopg[binary]==3.3.4`、`psycopg-pool==3.3.1`；生成完整 constraints，干净环境 `pip check` + 全量测试。
  如实承认传递依赖含 `langchain-core`（宪法"不引入 LangChain 全家桶"指不主动使用其应用层栈）。
- checkpoint 表含完整 SharedState（PII 副本）：登记表与清理策略，设 `LANGGRAPH_STRICT_MSGPACK=true`。

### 3.2 图结构（补全对审指出的遗漏）

```
lock_brief(plan gate：批准 Brief 回写 + approved_match_brief/planning 日志)
→ intent（含 intent_consulted=True 时跳过 LLM 但仍写 checkpoint 与 reused 日志的分支）
→ retrieve_match → strategy → verify
   verify 条件边：needs_reretrieval ∧ loops.reretrieval==0
     → prepare_reretrieval → retrieve_match(attempt=2) → strategy(attempt=2) → verify(attempt=2, allow_repair=第一次未用)
     → publish
   否则 → publish
publish：harness publication_gate + result_projector，只生成结果；
run 终态保存（save_run_result 幂等约束）放在图完成后的外围包装器，不进可重放节点。
```

保序契约（全部为群聊/Explain/监控的产品依赖，逐条 characterization test 锚定）：
7 个确定性 checkpoint 顺序；stage 在节点执行前推进；公开 `state_snapshot` 只在原有五个时机保存
（planning/首次 retrieval/首次 strategy/最终 verification/finalization），重检索中段不加新公开快照；
第二遍 matching/strategy 时长按现状计入 `verification`，`public_stage_duration` 只写一次；
`supervisor_log` 的 `reretrieval_loop/repair_loop/hard_filter_violations` 写入点不变。

### 3.3 事实边界（五层，checkpoint 不是业务状态源但确含状态副本）

`approved_plan`=不可变执行输入；LangGraph checkpoint=内部恢复状态（含 GraphState 副本）；
`match_runs.state_snapshot`=公开读模型；`result_snapshot/status`=终态产品事实；`session_state`=会话级事实。

GraphState = { shared: SharedState, brief: MatchBrief, retrieval_plan, verification, product_result,
attempt: int, loops: {reretrieval, repair}, run_id: str, stage_timing 累计 }

## 4. 分步实施（对审重排：spike 前移、特征测试先行、每步全量绿灯后才进下一步）

| 步骤 | 内容 | 验收 |
|---|---|---|
| S0 | langgraph 分支合并 codex/v1-complete（merge-tree 预检无冲突）；宪法与本文基线统一为 **279**；按 §3.1 锁定四个依赖 + 完整 constraints；干净 .venv `pip check` | 279 基线全绿 |
| S1 | **checkpointer spike（最大风险前移）**：真实 PostgreSQL 上 `asetup`、完整 SharedState round-trip、两个并发 thread_id 互不串、模拟进程重启后 `ainvoke(None, config)` 续跑 | spike 测试绿；PG 不可用则此步阻塞并上报 |
| S2 | **特征测试先行**：为现行 orchestrator 的 stage/snapshot/log/event 顺序新增 characterization tests（§3.2 保序契约逐条锚定），旧 279 项原样冻结不许删改 | 特征测试对旧实现全绿 |
| S3 | 实现 `app/graph/`（state/nodes/build）；图路径在 feature flag 下运行，与旧 orchestrator 跑同一特征测试集证明等价；不切 API | 双实现同测全绿 |
| S4 | **最大验收门**：run API 切换到图路径（durability=sync + 外围幂等包装器）；OpenAPI 快照零漂移；故障注入（节点前/后/checkpoint 前后 kill）证明手动续跑；不删除任何旧编排入口 | 全量绿 + 恢复测试绿 |
| S5 | E2E：虚拟简历完整流程（上传→确认→意图→Brief→执行→群聊/结果页），检索出岗位且证据可溯源；并发多 run 隔离 | E2E 通过 |
| S6 | 论文对照文档（两版架构图、恢复语义对比、代码量/测试对比）+ 收尾清理 | 文档完成 |

## 5. 风险与回滚

| 风险 | 缓解 |
|---|---|
| langgraph 版本 API 变动 | requirements.txt 锁精确版本；升级另立任务 |
| 条件边写错导致循环越界 | GraphState.loops 计数 + 图编译 recursion_limit 双保险；专项测试断言恢复各 ≤1 次 |
| checkpointer 与既有 state_store 双写不一致 | checkpoint 只做图恢复，业务事实仍以 state_store/run_store 为准（checkpoint 是执行位置的快照，不是业务数据源） |
| 迁移中断 | 每步独立 commit + push 双远端；任何一步红灯超 1 个工作日即回滚该步 commit |
| 回滚方案 | langgraph 为独立分支，主线始终可用；分支内 `git revert` 到上一绿灯步 |

## 6. 验收清单（第 3 大轮）

- [ ] Codex 对迁移 diff 做独立代码审查（正确性、约束、简化机会）
- [ ] Claude 复读全部图定义与条件边
- [ ] 全量测试绿（247 + 新增图测试 + 恢复测试）
- [ ] 虚拟简历端到端跑通，检索返回岗位、证据 span 可点开、群聊四角色发言完整
- [ ] 产品目标对齐核查：逐条核对本文 §2 不变量
