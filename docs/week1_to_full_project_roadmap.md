# Week1 优化与完整项目路线图

本文档用于把当前 Week1 已完成内容，对齐到 `毕业设计介绍_v6.pdf` 中描述的完整系统：

> Supervisor-guided Dual-space Agentic RAG for Career Matching
> 核心能力：Resume Normalization、Hybrid Search、Shared Structured State、RAPTOR、Dual-space Memory、Supervisor Agent、Career Trajectory Reasoning。

核心判断：Week1 的“简历进 -> Top-K 岗位出”已经跑通，但距离 PDF 中完整的 Agentic RAG 系统还有几个明确台阶。接下来要避免两种极端：

- 只停留在普通 RAG，支撑不起论文里的 Agentic / Supervisor / Dual-space 叙事。
- 过早做完整 RAPTOR、Cross-encoder、复杂多 Agent 框架，拖垮一个月项目节奏。

推荐策略是：

```text
先把 Week1 检索地基打硬 -> 做 RAPTOR-lite 可演示版 -> 再接三 Agent + Supervisor -> 最后补双空间记忆和评估。
```

## 1. 当前 Week1 状态

目前已经完成的基础链路：

- PostgreSQL + pgvector schema 可用。
- DeepSeek 文本生成可用。
- Qwen embedding 可用，维度与 `vector(1024)` 对齐。
- 50 条 LinkedIn JD 已字段化写入 `jobs`。
- 280 个 field-aware chunks 已写入 `job_chunks`，包含 embedding 和 tsv。
- PDF/docx/text 简历解析、DeepSeek 归一化、`original_evidence_spans`、`normalized_base_resume` 已实现。
- `hybrid_search.py` 已支持：
  - SQL hard filter
  - BM25
  - dense retrieval
  - RRF
  - dense-score bi-encoder-style rerank
- BM25 长简历 query 问题已修：不再直接用整段 resume 做 `plainto_tsquery`，而是提取关键词构造 OR 型 `to_tsquery`。
- `scripts/run_week1_pipeline.py` 已实现一条命令：

```text
简历文件 -> 归一化 -> 检索 -> Top-K -> retrieval_state 落库
```

这说明 Week1 里程碑已经成立：真实简历可以通过命令行产出 Top-K 岗位。

## 2. 和 PDF 完整愿景的差距

PDF 里的完整系统是六阶段：

- Stage 0：Resume Intake & Normalization
- Stage 1：Intent & Career Profile Agent
- Stage 2：Supervisor Planning
- Stage 3：Retrieval & Matching Agent
- Stage 4：Resume & Career Strategy Agent
- Stage 5：Supervisor Final Verification

当前 Week1 覆盖的是：

```text
Stage 0 + Stage 3 的检索底座
```

还没有完成：

- Agent 1：用户意图和长期职业画像
- Supervisor：检索计划、质量核查、bounded loop
- Agent 2：岗位分层 Now Fit / Stretch Fit / Bridge Role
- Agent 3：能力缺口、简历优化、职业路径
- FastAPI 多人服务
- Dual-space Memory
- 反馈闭环
- 评估指标
- RAPTOR-lite 或 RAPTOR ablation

所以现在不能说完整项目已完成，但 Week1 基础是对的。

## 3. 关于 RAPTOR 的范围决策

这里有一个关键冲突：

- `毕业设计介绍_v6.pdf` 把 RAPTOR 放在 MVP 1，并把它作为核心检索增强。
- 当前 `PLAN.md` / `AGENTS.md` 把 RAPTOR 放在 P2 / buffer，避免拖慢 P0。

建议采用折中方案：

```text
做 RAPTOR-lite，不做完整重型 RAPTOR。
```

这样既能支撑论文叙事，也不会把工程复杂度拉爆。

## 4. RAPTOR-lite 设计

### 4.1 离线层级

基于现有 `job_chunks` 构建三层即可：

```text
JD chunk leaf
  -> job_summary
  -> role_cluster_summary
  -> career_direction_summary
```

最低可行版本：

1. `job_chunks` 已经是 leaf nodes。
2. 每个 `job_id` 生成一个 job-level summary。
3. 每个 `role_cluster` 生成一个 role-level summary。
4. 可选地，把 role clusters 再合并成 career direction：
   - data_ai
   - software_engineering
   - product_management
   - marketing_sales
   - operations
   - healthcare
5. 每个 summary node 用 Qwen embedding。
6. summary node 写入 PostgreSQL。

建议新增表：

```sql
CREATE TABLE raptor_nodes (
    node_id TEXT PRIMARY KEY,
    node_type TEXT,
    parent_id TEXT,
    job_id TEXT,
    role_cluster TEXT,
    content TEXT,
    embedding vector(1024),
    child_ids TEXT[]
);
```

### 4.2 在线检索

在线流程：

```text
resume query
  -> retrieve raptor summary nodes
  -> expand child job_ids
  -> union with BM25 candidates
  -> union with dense candidates
  -> RRF
  -> final rerank
```

也就是说 RAPTOR 不替代 BM25/dense，而是增加一个“层级召回源”。

### 4.3 为什么这样够用

完整 RAPTOR 可能需要递归聚类、反复总结、复杂树维护。对一个月项目来说太重。

RAPTOR-lite 的优势：

- 能讲清楚层级检索思想。
- 能做 before/after 对比实验。
- 能复用现有 `jobs.role_cluster`。
- 不破坏当前 hybrid retrieval。
- 失败时可以降级：RAPTOR 没效果也不影响 BM25+dense 主线。

## 5. Week1 还可以优化什么

### 5.1 扩大数据规模

当前只有 50 个 jobs / 280 chunks，适合 smoke test，但不够支撑演示质量。

建议：

- 最低：1,000 jobs
- 较好：3,000-5,000 jobs
- 保留 `--limit 50` 用于快速测试

验收 SQL：

```sql
SELECT count(*) FROM jobs;
SELECT count(*) FROM job_chunks;
SELECT count(DISTINCT job_id) FROM job_chunks;
```

### 5.2 加 retrieval diagnostics

每个 Top-K 结果应该能看出它为什么上榜：

- BM25 rank / score
- dense rank / score
- RAPTOR rank / score
- RRF score
- final score
- evidence chunk ids

建议 `retrieval_state.ranking_scores` 扩成：

```json
{
  "job_id": "123",
  "final_score": 0.82,
  "rrf_score": 0.04,
  "bm25_score": 0.31,
  "dense_score": 0.76,
  "raptor_score": 0.55,
  "sources": ["bm25", "dense", "raptor"]
}
```

这对调试、论文截图、答辩解释都很有用。

### 5.3 改善 query-side resume representation

现在主要用 `normalized_base_resume` 作为 query。更好的方式是把简历拆成多个 query view：

- `resume_summary_query`
- `skills_query`
- `experience_query`
- `project_query`
- `goal_query`

Week1 可以先用规则构建；Week2 之后由 Agent 1 提供 `goal_query`。

### 5.4 field-aware retrieval 权重

JD chunk 来源不同，权重应不同：

- `required_skills`：技能匹配更重要
- `responsibilities`：岗位职责匹配更重要
- `metadata`：标题、地点、role cluster 更重要
- `raw_jd`：兜底召回

可以在 rerank 时加简单 field bonus：

```text
required_skills +0.05
responsibilities +0.04
metadata +0.03
raw_jd +0.00
```

这是便宜、可解释、适合论文的优化。

### 5.5 保存更多 evidence

目前已经保存了 candidate IDs、scores、evidence chunk IDs。下一步建议：

- 保存 hard filter log
- 保存每个 evidence chunk 的字段来源
- 输出时能根据 chunk_id 查回 JD 原文片段
- Supervisor final verification 使用这些 evidence 检查忠实度

## 6. 从现在到完整项目的实现顺序

### Phase A：加固 Week1 检索地基

目标：让 CLI baseline 成为后续 Agent 的稳定工具。

任务：

1. commit 当前 Week1 + 架构修复 + BM25 修复。
2. 扩到 1,000+ jobs。
3. 加 retrieval diagnostics。
4. 加 query-side resume representation。
5. 加 field-aware reranking。
6. 建一个 10-20 条的小评估集。

完成标准：

```text
一条命令返回 Top-K + 来源分数 + evidence + 简单指标。
```

### Phase B：RAPTOR-lite

目标：满足 PDF 里的 RAPTOR 叙事，并能做 ablation。

文件建议：

```text
app/retrieval/raptor.py
scripts/build_raptor_index.py
```

最小功能：

- 从 `job_chunks` 生成 job summaries。
- 从 `role_cluster` 生成 role summaries。
- summary embedding 写入 `raptor_nodes`。
- `hybrid_search` 增加 RAPTOR 召回源。
- 对比 no-RAPTOR vs with-RAPTOR 的 Top-K 指标。

### Phase C：Three Agents + Supervisor

目标：从固定 RAG pipeline 升级为 Agentic RAG。

严格保持轻量：

- 不引入 LangGraph
- 不引入 CrewAI
- 不引入 AutoGen
- 只用普通 async 函数 + SharedState + DeepSeek prompt

顺序：

1. `intent_agent.py`
   - 输入：resume_state + 用户目标文本
   - 输出：career_state
   - 区分 hard constraints 与 soft preferences

2. `supervisor.py` planning
   - 检查目标是否模糊
   - 生成 retrieval plan
   - clarification loop 最多 1 次

3. `matching_agent.py`
   - 包装 `hybrid_search`
   - 输出 Now Fit / Stretch Fit / Bridge Role
   - 写 `retrieval_state` + `strategy_state.recommended_roles`

4. `strategy_agent.py`
   - 输出能力缺口
   - 输出简历优化建议
   - 输出短中长期职业路径
   - 必须基于 `original_evidence_spans`

5. `supervisor.py` final verification
   - 检查硬过滤是否被违反
   - 检查解释是否有 evidence
   - 检查简历建议是否编造
   - re-retrieval / repair loop 最多 1 次

完成标准：

```text
一次 orchestrator 调用，从简历到推荐岗位、分层、缺口、简历建议、职业路径。
```

### Phase D：FastAPI 多人服务

目标：满足“多人同时使用、服务无状态”的 P0 要求。

路由：

```text
POST /resume
POST /match
GET /status/{session_id}
GET /result/{session_id}
POST /feedback
```

原则：

- 每个请求都有 `session_id`
- state 全部进 PostgreSQL
- 进程内不存业务状态
- 长任务提交后立刻返回，前端轮询

### Phase E：Dual-space Memory

目标：实现 PDF 中的显性岗位空间 + 隐性职业空间。

最低可行版本：

- `private_memory.py`：用户私有简历记忆
- `feedback.py`：投递反馈
- `case_base.py`：匿名案例检索
- `seed_cases.py`：塞 10-20 条匿名案例

隐私原则：

```text
原始简历 -> private memory only
匿名职业模式 -> case base
```

### Phase F：Evaluation

目标：论文里能量化证明系统有效。

指标：

- Recall@K
- Precision@K
- MRR
- NDCG@K
- hard filter accuracy
- explanation faithfulness
- before/after RAPTOR comparison
- before/after Latent Career Space qualitative comparison

建议数据：

```text
data/eval/resume_queries.jsonl
data/eval/relevance_labels.jsonl
```

## 7. 不建议现在做的事情

这些东西可以写成“接口预留”或“可选增强”，但不要现在塞进主线：

- 完整递归 RAPTOR
- Cross-encoder 线上服务
- 多 Agent 辩论
- 自动长期学习排序权重
- 复杂前端
- 把用户原始简历放进公共案例库

## 8. 最近 5 个最值得做的任务

建议接下来按这个顺序：

1. commit 当前 Week1 修复。
2. 扩大数据到 1,000 jobs。
3. 加 retrieval diagnostics + field-aware rerank。
4. 做 RAPTOR-lite schema + offline builder。
5. 开始 Day 8 `intent_agent.py`。

这个顺序能最大程度对齐 PDF，又不会偏离 P0。

## 9. 最终论文叙事

最终可以这样讲：

1. 起点是普通“简历-岗位”RAG 匹配。
2. 先通过 Resume Normalization 提升 query 质量。
3. 用 Hybrid Search + RRF + pgvector 建立可解释检索底座。
4. 用 RAPTOR-lite 增强层级召回。
5. 用 Shared Structured State 避免多 Agent 自然语言传递造成信息丢失。
6. 用三个业务 Agent 分别处理意图、匹配、策略。
7. 用 Supervisor 负责规划、核查、受控重试和最终验证。
8. 用 Dual-space Memory 将当前岗位匹配扩展为职业路径经验沉淀。
9. 用评估指标证明检索质量、解释忠实度和路径建议合理性。

一句话总结：

```text
Week1 是 RAG 检索地基；RAPTOR-lite 是检索增强亮点；三 Agent + Supervisor 是 Agentic 核心；Dual-space Memory 是从 Job Matching 升级到 Career Trajectory Reasoning 的关键。
```
