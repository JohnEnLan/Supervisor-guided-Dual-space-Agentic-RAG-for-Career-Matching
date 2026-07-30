# CLAUDE_LANGGRAPH.md — Career-RAG 项目规格（LangGraph 版 · 仅本分支生效）

> 本文件是 `langgraph` 分支的"宪法"，由 CLAUDE.md 复制而来并做 LangGraph 化修订。
> **原 CLAUDE.md 保持不动**（主线 codex/v1-complete 与 main 仍以原文件为准）。
> 在本分支上工作时，本文件的条款覆盖 CLAUDE.md 中与之冲突的条款；未提及的条款仍沿用 CLAUDE.md。

---

## 0. 本分支目标

把主线中"普通异步函数 + Supervisor Harness"的自研编排层，迁移为 **LangGraph StateGraph** 驱动的稳定框架版本，同时**保持对外行为完全一致**：
- 全部 `/api/v1` 契约不变（OpenAPI 快照 `tests/snapshots/openapi_v1.json` 不允许漂移）。
- 全部 **279** 个既有测试**原样冻结**（不许删改旧断言）；图等价性由新增特征测试/黑盒等价测试证明。
- 本轮只实现"手动 checkpoint 续跑能力"；自动恢复 worker/lease 属 Release-1（docs/known_issues.md #10）。
- 论文叙事：主线讲"轻量自研 Harness"，本分支作为对照实验/工程化演进讲"迁移到 LangGraph 后获得 checkpoint、可视化与恢复语义"，两版可对比。

## 1. 对 CLAUDE.md 硬约束的修订

| 原条款 | 本分支修订 |
|---|---|
| §2.3 "不要引入 LangGraph / AutoGen / CrewAI 等重框架" | **仅解除 LangGraph 一项**。AutoGen / CrewAI / LangChain 全家桶仍然禁止；只允许 `langgraph` + 其必需的最小依赖，锁定版本写入 requirements.txt。 |
| §2.3 "三个业务 Agent = 三次带不同 system prompt 的 LLM 调用" | 不变。Agent 本体仍是普通异步函数（prompt + LLM 调用 + state 读写），LangGraph 只接管**编排**（节点顺序、条件边、恢复），不接管 Agent 内部逻辑。 |
| §2.4 "Supervisor = 核查 prompt + 有界循环" | 有界恢复改用 LangGraph 机制表达：clarification / re-retrieval / repair 三类循环用**条件边 + GraphState 中的 loop 计数器**实现，每类上限仍为 1；图编译时设置 `recursion_limit` 作为最后防线。禁止在节点内写开放式循环（不变）。 |
| §2.1 "状态绝不进进程全局变量" | 不变，且加强：GraphState 必须是 `app/state/schema.py` 的 SharedState 的**类型化包装**（单一事实来源不变）。checkpointer 使用官方 **AsyncPostgresSaver**（psycopg3 + psycopg-pool 独立异步池，同一个数据库/DSN，**不是**复用 asyncpg 池；lifespan 管理生命周期；`durability="sync"`）。禁止 MemorySaver 出现在任何非测试代码。checkpoint 表含 SharedState 副本（PII），须登记清理策略；反序列化安全由 `app/api/main.py` 的显式类型 allowlist 控制。 |
| §2.2 "并发用 asyncio，不用 threading" | 修订为：**业务代码**不得创建线程；允许锁定版本的依赖内部受控线程（如 AsyncPostgresSaver 的 `asyncio.to_thread` 序列化）。 |
| 其余硬约束（asyncio、SQL 硬过滤、evidence_spans、Semaphore 限流、一次一个模块） | 全部不变。 |

## 2. 迁移映射（自研 Harness → LangGraph）

```
现有主流程                                LangGraph 节点/机制
──────────────────────────────────────────────────────────────
orchestrator.run_persisted_..._run     → StateGraph(GraphState) 编译产物 graph.ainvoke
Stage 0  resume intake                 → 节点 resume_intake（保持在图外的既有异步任务亦可，二选一后固定）
Stage 1  intent agent                  → 节点 intent
Stage 2  supervisor planning/brief     → 节点 plan_gate（确定性检查 + 已批准 Match Brief 注入）
Stage 3  matching agent + 检索          → 节点 retrieve_and_match
Stage 4  strategy agent                → 节点 strategy
Stage 5  supervisor final verification → 节点 verify
harness 检查点（7 个确定性 checkpoint）   → 各节点前后的确定性函数：入边前置校验 + 出边条件函数，不调 LLM
re-retrieval（≤1 次）                   → verify 的条件边：needs_reretrieval 且 loop 计数 0 → 回 retrieve_and_match；否则 → publish
repair（≤1 次）                         → verify 节点内确定性修复（沿用 allow_repair 语义），计数进 GraphState
clarification（≤1 次）                  → 意图咨询阶段既有实现保持在图外（Brief 确认前），不进图
publication gate + 投影                 → 节点 publish（复用 result_projector，产出 ProductResult）
run_store 阶段推进 / 快照               → checkpointer（PostgresSaver）+ 节点内沿用 update_run_stage / save_state_snapshot
supervisor_log / trace 白名单           → 不变，节点内继续写同一 SharedState 字段（保证 explain / 群聊投影兼容）
```

## 3. 实施顺序（本分支）

以 `docs/langgraph_migration_plan.md` v2 的 S0–S6 为准（对审后重排：spike 前移、特征测试先行、
run API 切换为最大验收门、本轮不删除任何旧编排入口）。版本锁定：`langgraph==1.2.9`、
`langgraph-checkpoint-postgres==3.1.0`、`psycopg[binary]==3.3.4`、`psycopg-pool==3.3.1`。
传递依赖含 `langchain-core` 属事实陈述；"不引入 LangChain 全家桶"指不主动使用其应用层栈。

每一步跑通 279 项全量测试后才进下一步（沿用 §2.8"一次一个模块"）。

## 4. 明确不做

- 不把 Intent 咨询（图外交互式对话）塞进图里。
- 不引入 LangSmith / LangServe / LangChain retriever 栈；检索仍是 `app/retrieval/` 的自研实现。
- 不改 `/api/v1` 契约、不改 SharedState 结构、不改 evidence 边界。
- 不在主线分支合并本分支任何提交，除非用户明确要求。
