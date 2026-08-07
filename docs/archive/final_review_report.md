# 双审通过报告 · 系统架构与代码分区说明

> 分支 `langgraph@cda65d1` · 2026-07-31
> 双审结论：**Claude code review PASS + Codex（gpt-5.6-sol · xhigh）code review PASS**，无未决 findings。

---

## 1. 审查过程（真实可核）

| 环节 | 内容 | 结果 |
|---|---|---|
| 真实性复核 | 提交链 / GitHub+GitLab 双远端指针 / E2E 报告 / 测试数逐项核实 | 全部属实 |
| Claude 审查+优化 | 修复 checkpoint 计时跨进程失真；pyflakes 清零；删无用导入 | 299→修复后全绿 |
| Codex 终审 R1 | 8 条 findings（2 high） | FAIL |
| 修复收敛 | F1–F4 Codex 实现，F5–F8 Claude 补齐（死机截断后接力） | 312 绿 |
| Codex 终审 R2 | 5/8 PASS，3 条残余 | FAIL |
| 残余修复 | 硬过滤权威收口 / 清理循环隔离 / 文档残留 | 314 绿 |
| Codex 终审 R3 | 逐条复核 + 新问题抽查 | **PASS** |

期间修复的代表性实质缺陷：LLM 透传字段可剔除 SQL 已放行的岗位（硬过滤权威被架空）、首个 checkpoint 落盘前崩溃不可恢复、checkpoint 持久化进程相对时钟导致恢复后耗时失真、单个中毒线程饿死 PII 清理。

**最终基线：314 项测试全绿**（后端）；前端 30 项 + typecheck + 生产构建绿；虚拟简历端到端真实跑通（5 岗位/三分层/证据可溯源/群聊四角色）。

## 2. 整体架构

```
React 工作台 (frontend/)
   │  轮询式 REST（服务端下发节奏）
   ▼
FastAPI /api/v1 (app/api/)  ←—— 公共 DTO 投影，原始状态永不出境
   │
   ▼
编排层（可切换，langgraph 分支默认图路径）
   ├─ LangGraph StateGraph (app/graph/)：7 节点 + 有界重检索条件边
   │    AsyncPostgresSaver 每节点 sync checkpoint → 崩溃后手动续跑零重放
   └─ 自研 Supervisor Harness (app/agents/orchestrator.py)：legacy 回退路径
   │
   ▼
三业务 Agent + Supervisor (app/agents/)
   Intent（需求）→ Matching（检索匹配）→ Strategy（策略）
   Supervisor Harness：7 个确定性检查点 + 有界恢复（每类 ≤1 次）+ 发布门禁
   │
   ▼
双空间检索 (app/retrieval/)
   显性空间：SQL 硬过滤 → BM25 ∥ Dense 并行 → job_id 级 RRF → 加权重排
   隐性空间：匿名案例受限重排（有界权重，不能引入新岗位/绕过硬过滤）
   │
   ▼
PostgreSQL + pgvector (app/db/)
   岗位/JD 块/向量(HNSW) · 会话状态(按 session_id) · run 生命周期 · checkpoint(终态即删)
```

核心设计不变量：硬约束只由 SQL 与确定性代码裁决（LLM 输出仅 advisory）；一切建议必须携带可验证的 evidence span（简历侧防编造、JD 侧可溯源）；状态全部入库、进程无用户全局变量；所有恢复循环有界（每类最多一次）。

## 3. 功能一览（用户旅程）

1. **上传简历**（PDF/DOCX/TXT）→ 归一化为结构化档案，每条事实绑定原文 span，无法验证的标记 unverified
2. **确认简历** → **意图咨询**（Targeted/Explore，最多一次受控澄清）→ 区分当前目标/长期方向/硬约束/软偏好
3. **Match Brief 确认单** → 哈希冻结目标、约束、Top-K，创建 run
4. **执行**（图路径 + checkpoint）→ 前端两种视角：进度板 或 **职业规划服务群**（需求顾问·小意 / 岗位顾问·小检 / 规划师·小策 / PM 四角色群聊直播，PM 播报监督检查点与受控恢复）
5. **结果**：岗位三分层（Now Fit / Stretch Fit / Bridge Role）+ 逐岗匹配解释与 JD 证据 + 技能缺口 + 简历修改建议（只引用真实经历）+ 短中长期路径
6. **反馈** → 私有记录持久化，供 P1 双空间闭环
7. **评估/监控**（能力开关控制）：Precision/Recall/MRR/NDCG、证据覆盖率、阶段耗时 P50/P95、恢复事件、双空间使用率

## 4. 代码分区摘要

| 分区 | 职责 |
|---|---|
| `app/api/` | FastAPI 入口与 lifespan（双连接池、checkpoint 周期清理）；`v1/` 全部公共路由（会话/简历/意图/Brief/运行/群聊/结果/反馈/监控）；`result_projector.py` 与 `conversation_projector.py` 把私有状态投影为公共 DTO——隐私边界所在 |
| `app/graph/` | LangGraph 编排：`state.py` GraphState 契约、`nodes.py` 七个薄包装节点、`build.py` 图组装、`runner.py` 生命周期外围（CAS/续跑探测/终态幂等/checkpoint 清理） |
| `app/agents/` | 三业务 Agent + `supervisor.py`（规划与终审，含确定性复核）+ `supervisor_harness.py`（7 检查点）+ `orchestrator.py`（legacy 编排与两图共享的公共编排契约）+ `trace.py`（答辩用白名单投影） |
| `app/retrieval/` | `hybrid_search.py` 混合检索主链、`rrf.py` 融合、`dual_space_search.py`+`implicit_search.py` 双空间、`raptor.py` RAPTOR-lite（默认关，消融用）、`query_builder.py` |
| `app/db/` | `schema.sql`+`migrations/` 全部表结构；`pool.py` asyncpg 池；`state_store.py` 按 session 的原子状态读写（行锁/CAS）；`run_store.py` run 生命周期与快照；监控/事件存储；`vector.py` 统一向量序列化 |
| `app/normalization/` | Stage 0 简历归一化：解析（含 DOCX 表格）→ 本地切 evidence span → LLM 结构化 → 逐事实 span 校验防编造 |
| `app/memory/` | 私有记忆、反馈记录、匿名案例库（PII 校验）、反馈闭环（P1） |
| `app/evaluation/` | 检索/忠实度/硬过滤指标（逐岗证据映射、unknown 单列）、压测统计 |
| `app/llm/` | DeepSeek 与 Qwen Embedding 异步客户端：Semaphore 限流 + 上下文预算截断 |
| `app/domain/` `app/state/` | 领域模型（MatchBrief 冻结单、公共结果 DTO、run 状态机、监控指标）与 SharedState 单一事实来源 |
| `app/serve.py` | 唯一启动入口（Windows 事件循环适配：psycopg 需 SelectorEventLoop） |
| `frontend/` | React 19+Vite+TanStack Query 工作台：会话/简历/Brief/进度/群聊/结果/评估/监控 8 页面，类型由 OpenAPI 快照生成并带漂移检测；Vitest+Playwright |
| `scripts/` | 岗位入库建向量、RAPTOR 建树、案例种子、演示简历生成、系统评估与消融 |
| `tests/` | 314 项：单元/契约/特征(保序)/等价矩阵/真实 PG 恢复注入/并发隔离/隐私断言/OpenAPI 快照 |
| `docs/` | 迁移计划书（双审定稿）、双架构对照、E2E 证据、已知问题清单、历史设计与计划 |
| `data/` | LinkedIn 岗位样本（50/1000）、评估标注集、演示简历产物 |

## 5. 已知边界（不影响本判定）

设计级暂缓项见 `docs/known_issues.md`（10 条，含案例库双模型统一、自动恢复 worker 等 Release-1 事项）；主线分支 `codex/v1-complete` 保持自研 Harness 叙事，本分支为对照实验与产品化路径。
