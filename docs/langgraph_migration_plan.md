# LangGraph 迁移计划书（v1 草案 · 待 Codex 对审）

> 状态：草案。流程：Claude 起草 → Codex 对审 → 修订定稿 → 在 `langgraph` 分支实施。
> 配套宪法：`CLAUDE_LANGGRAPH.md`（langgraph 分支）。本文是"为什么与怎么做"，宪法是"红线"。

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

### 1.3 结论

在"主线不动、分支迁移、测试为锚"的前提下，迁移的期望收益（产品化路径、恢复语义、生态）显著大于风险。**建议执行。**

## 2. 目标与不变量

| 类别 | 内容 |
|---|---|
| 目标 | `langgraph` 分支上，run 执行路径由 LangGraph `StateGraph` 驱动，接入 `PostgresSaver` checkpoint，行为与主线一致 |
| 不变量 1 | `/api/v1` 全部契约不变，OpenAPI 快照零漂移（`tests/snapshots/openapi_v1.json`） |
| 不变量 2 | 全部 247 项测试语义不变（编排测试允许改写为图版等价断言，断言结论不变） |
| 不变量 3 | CLAUDE.md 其余硬约束全部保留：SharedState 单一事实来源、SQL 硬过滤、evidence 边界、Semaphore 限流、有界恢复各 ≤1 次 |
| 不变量 4 | Agent 本体（intent/matching/strategy 的 prompt + LLM 调用）零改动，LangGraph 只接管编排 |
| 明确不做 | 不引入 LangChain 全家桶/LangSmith/LangServe；意图咨询（Brief 确认前的图外交互）不进图 |

## 3. 现状 → 目标映射

```
run_persisted_agentic_match_run (orchestrator.py)   →  graph.ainvoke(GraphState, config={thread_id: run_id})
  Stage intent      → 节点 intent          （包 run_intent_agent，前后确定性检查做进节点包装器）
  Stage retrieval   → 节点 retrieve_match  （包 matching_agent + hybrid_search）
  Stage strategy    → 节点 strategy        （包 strategy_agent）
  Stage verification→ 节点 verify          （final_verification，allow_repair 语义不变）
  re-retrieval ≤1   → verify 条件边：needs_reretrieval ∧ loops.reretrieval==0 → retrieve_match；否则 → publish
  publication gate  → 节点 publish         （harness publication_gate + result_projector）
  run_store 阶段推进 → 各节点内沿用 update_run_stage / save_state_snapshot（群聊投影与监控不受影响）
  checkpoint        → PostgresSaver，复用同一 PostgreSQL；禁 MemorySaver 出现在生产代码
GraphState = TypedDict{ shared: SharedState, brief: MatchBrief, loops: {reretrieval:int, repair:int}, run_id: str }
```

## 4. 分步实施（每步全量测试绿灯后才进下一步）

| 步骤 | 内容 | 验收 |
|---|---|---|
| S0 | `git merge codex/v1-complete` 进 langgraph 分支；`pip install langgraph==<锁定版>` 写入 requirements.txt | 247 基线全绿 |
| S1 | 新建 `app/graph/`（state.py + nodes.py + build.py），纯定义不接管任何入口；节点单测 | 新增测试绿，基线不动 |
| S2 | run API 路径切换到 `graph.ainvoke`；`test_run_orchestration.py` 改写为图版等价断言 | 全量绿 + OpenAPI 快照零漂移 |
| S3 | 接入 PostgresSaver；新增断点恢复测试（模拟节点间崩溃 → 重新 invoke 续跑不重复执行已完成节点） | 恢复测试绿 |
| S4 | 其余三个编排入口：仍被旧 API 使用的保留并标注 legacy；只剩测试引用的删除（结合第 1 轮冗余清单） | 全量绿 |
| S5 | 对照文档：两版架构图、恢复语义对比、代码量/测试对比表（论文素材） | 文档完成 |
| S6 | 端到端验收：生成虚拟简历 → 完整流程（上传→确认→意图→Brief→执行→群聊/结果页）→ 检索出岗位且证据可溯源 | E2E 通过 |

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
