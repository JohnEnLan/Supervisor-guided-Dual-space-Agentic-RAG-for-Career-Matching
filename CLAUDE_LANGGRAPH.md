# CLAUDE_LANGGRAPH.md — Career-RAG 项目规格（LangGraph 版 · 仅本分支生效）

> 本文件是 `langgraph` 分支的"宪法"，由 CLAUDE.md 复制而来并做 LangGraph 化修订。
> **原 CLAUDE.md 保持不动**（主线 codex/v1-complete 与 main 仍以原文件为准）。
> 在本分支上工作时，本文件的条款覆盖 CLAUDE.md 中与之冲突的条款；未提及的条款仍沿用 CLAUDE.md。

---

## 0. 本分支目标

把主线中"普通异步函数 + Supervisor Harness"的自研编排层，迁移为 **LangGraph StateGraph** 驱动的稳定框架版本，同时**保持对外行为完全一致**：
- 全部 `/api/v1` 契约不变（OpenAPI 快照 `tests/snapshots/openapi_v1.json` 不允许漂移）。
- 全部 240 个既有测试语义不变（编排层测试允许改写为 LangGraph 等价物，断言结论不变）。
- 论文叙事：主线讲"轻量自研 Harness"，本分支作为对照实验/工程化演进讲"迁移到 LangGraph 后获得 checkpoint、可视化与恢复语义"，两版可对比。

## 1. 对 CLAUDE.md 硬约束的修订

| 原条款 | 本分支修订 |
|---|---|
| §2.3 "不要引入 LangGraph / AutoGen / CrewAI 等重框架" | **仅解除 LangGraph 一项**。AutoGen / CrewAI / LangChain 全家桶仍然禁止；只允许 `langgraph` + 其必需的最小依赖，锁定版本写入 requirements.txt。 |
| §2.3 "三个业务 Agent = 三次带不同 system prompt 的 LLM 调用" | 不变。Agent 本体仍是普通异步函数（prompt + LLM 调用 + state 读写），LangGraph 只接管**编排**（节点顺序、条件边、恢复），不接管 Agent 内部逻辑。 |
| §2.4 "Supervisor = 核查 prompt + 有界循环" | 有界恢复改用 LangGraph 机制表达：clarification / re-retrieval / repair 三类循环用**条件边 + GraphState 中的 loop 计数器**实现，每类上限仍为 1；图编译时设置 `recursion_limit` 作为最后防线。禁止在节点内写开放式循环（不变）。 |
| §2.1 "状态绝不进进程全局变量" | 不变，且加强：GraphState 必须是 `app/state/schema.py` 的 SharedState 的**类型化包装**（单一事实来源不变），checkpointer 使用 **PostgresSaver**（复用现有 asyncpg 连接池所在的同一个库），禁止 MemorySaver 出现在任何非测试代码。 |
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

1. `requirements.txt` 锁定 `langgraph==<选定版本>`；新建 `app/graph/graph.py`（GraphState 定义 + build_graph()），不接管任何入口。
2. 用 LangGraph 重写 `run_persisted_agentic_match_run` 一条路径（run API 专用），旧 orchestrator 保留供其余入口使用；`tests/test_run_orchestration.py` 改写为图版等价断言，全量测试保持绿。
3. PostgresSaver checkpoint 接入 + 断点恢复测试（杀进程 → 重新 ainvoke 从 checkpoint 续跑）。
4. 其余三条编排入口迁移或显式废弃（写明决定），删除死代码。
5. 文档：本文件 + 论文对照章节素材（两版架构图、恢复语义对比、测试证据）。

每一步跑通 240 项全量测试后才进下一步（沿用 §2.8"一次一个模块"）。

## 4. 明确不做

- 不把 Intent 咨询（图外交互式对话）塞进图里。
- 不引入 LangSmith / LangServe / LangChain retriever 栈；检索仍是 `app/retrieval/` 的自研实现。
- 不改 `/api/v1` 契约、不改 SharedState 结构、不改 evidence 边界。
- 不在主线分支合并本分支任何提交，除非用户明确要求。
