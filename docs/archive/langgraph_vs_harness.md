# 两种编排范式对照：自研 Supervisor Harness vs LangGraph StateGraph（论文素材）

> 主线分支 `codex/v1-complete` 保留自研 Harness；`langgraph` 分支为等价的 LangGraph 实现。
> 两版共享全部 Agent 本体、检索层、状态契约与 `/api/v1` 接口；差异只在编排层。

## 1. 架构对照

| 维度 | 自研 Harness（主线） | LangGraph（本分支） |
|---|---|---|
| 编排载体 | `app/agents/orchestrator.py` 普通异步函数顺序调用 | `app/graph/` StateGraph：7 节点 + 1 条件边 |
| 有界恢复 | if 分支 + 状态标记（每类 ≤1 次） | 条件边 + GraphState.loops 计数 + recursion_limit=12 双保险 |
| 执行位置持久化 | 无（进程崩溃即丢 in-flight run，启动回收为 stale） | AsyncPostgresSaver 每节点 sync checkpoint；同 thread_id `ainvoke(None)` 手动续跑，已完成节点零重放 |
| 状态事实源 | PostgreSQL session/run 表（唯一） | 同左不变；checkpoint 仅为执行位置快照（终态即删，PII 卫生） |
| 依赖 | 零编排框架依赖 | langgraph 1.2.9 + checkpoint-postgres 3.1.0 + psycopg 3.3.4（独立小连接池） |
| 可解释性 | 每行可讲，答辩友好 | 图定义声明式可视化，行为由 6 项特征测试锚定 |

## 2. 行为等价性证明方法

1. **特征测试先行**（`tests/test_orchestration_characterization.py`）：先对旧实现锚定 7 检查点顺序、
   stage 先行推进、公开快照恰好五个时机、重检索计时归属、supervisor_log 字段、intent 复用、终态单次保存；
2. 同一套特征测试参数化跑两个实现，断言完全一致；
3. OpenAPI 快照零漂移；旧测试断言全程冻结（279 → 新增至 299，零删改）。

## 3. 恢复语义对比（真实 PostgreSQL 故障注入，`tests/test_langgraph_runner_recovery.py`）

- 在 strategy 节点 checkpoint 落盘后模拟进程崩溃；
- 新进程对同一 thread_id `ainvoke(None)`：intent/retrieve_match/strategy 计数保持 1（零重放），续跑至完成；
- 终态结果与不中断对照 run 完全一致，`save_run_result` 恰好一次；
- 终态后 checkpoint 三表清零（避免简历 PII 副本滞留）。
- 范围声明：本轮为**手动续跑能力**；自动恢复调度（扫描/worker/租约）属 Release-1（known_issues #10），
  对外能力声明保持 `execution_durability="process_local"` 不变。

## 4. 端到端证据（2026-07-30，`docs/validation/2026-07-30-langgraph-e2e-report.json`）

虚拟简历（`scripts/generate_demo_resume.py` 产出 DOCX）走完整流程，全部真实 LLM/Embedding/PG：
上传 → 归一化（1 学历/2 经历/19 技能）→ 确认 → 意图咨询（含一轮真实澄清问答）→ Match Brief →
图路径执行 `completed` → 群聊 8 条消息四角色齐全 → 结果 5 个岗位（now_fit 1 / stretch_fit 2 / bridge_role 2），
每个岗位均带可溯源 JD evidence span，零警告。

## 5. 工程结论（诚实版）

- LangGraph 没有减少业务代码：节点是旧函数的薄包装，审计/投影/错误处理原样保留；
- 它买到的是：执行位置持久化与续跑语义（自研需重写 mini-checkpointer）、声明式图结构、生态兼容；
- 它付出的是：第二套 PG 驱动与连接池、checkpoint PII 治理、Windows 事件循环适配
  （psycopg 不支持 Proactor，需 `app/serve.py` 显式 SelectorEventLoop 启动）、依赖升级面；
- 对一个月毕设：主线自研是正确决策；LangGraph 分支的价值在于给出可检验的对照实验与产品化路径。

## 6. 测试规模

| 节点 | 数量 |
|---|---|
| 主线基线（审计修复后） | 279 |
| + S1 spike + S2 特征测试 | 285 |
| + S3 图实现等价矩阵 | 291 |
| + S4 恢复/接线/清理 | **299** |
