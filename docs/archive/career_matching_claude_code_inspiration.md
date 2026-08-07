# Claude Code 架构思想对 Career Matching 项目的启发与补充建议

项目：Supervisor-guided Dual-space Agentic RAG for Career Matching  
日期：2026-07-08

## 1. 总体判断

当前项目已经具备较完整的 Agentic RAG 主线：

- Resume intake and normalization
- Hybrid retrieval: BM25, dense retrieval, RRF, RAPTOR-lite, field-aware scoring
- Three business agents: Intent Agent, Matching Agent, Strategy Agent
- Supervisor planning and final verification
- Shared structured state
- FastAPI multi-user submit-and-poll workflow
- Evidence-gated recommendation and resume advice
- Dual-space memory and feedback-loop direction

因此，下一步不建议继续简单堆叠更多 Agent，而是把系统提升为一个更可控、更可解释、更可靠的 Career Agent Runtime。

Claude Code 的最大启发不在于“多 Agent 数量很多”，而在于它把 Agent 外围工程做得很扎实：上下文管理、工具执行、权限控制、失败恢复、审计轨迹、用户确认、可观测性。把这些思想映射到职业匹配项目，可以显著增强论文的系统性和答辩说服力。

推荐补充方向：

```text
Traceability + Context Engineering + Bounded Recovery + Human Approval + Privacy Guardrails + Dual-space Cache
```

## 2. 最值得补充的 6 个 Idea

### Idea 1: Career Agent Trace / EXPLAIN 轨迹层

#### 核心想法

为每次 career matching 生成一条完整的可审计轨迹，记录系统如何从用户目标和简历证据一步步得到最终推荐。

当前项目已经有 `supervisor_log` 和 retrieval diagnostics，可以将其正式升级为论文中的 Agentic Traceability 机制。

#### 可以记录的内容

- 用户目标如何被 Intent Agent 解析为 hard constraints 和 soft preferences
- hard constraints 如何进入 SQL filter
- BM25、dense retrieval、RAPTOR-lite 各自召回了哪些候选岗位
- RRF 和 rerank 如何合成最终分数
- Matching Agent 如何把岗位分为 now fit、stretch fit、bridge role
- Strategy Agent 的简历建议引用了哪些原始 evidence spans
- Supervisor 做过哪些规划、修复、重检索和最终校验

#### 论文价值

这一点可以支撑一个很强的论述：

> The system is not only an Agentic RAG recommender, but also an inspectable decision pipeline where each recommendation can be traced back to retrieval evidence, resume evidence, and bounded supervisory interventions.

#### 实现建议

新增或整理一个统一 trace schema：

```json
{
  "session_id": "s1",
  "stages": [
    {
      "stage": "intent",
      "input_summary": "...",
      "output": {
        "hard_constraints": {},
        "soft_preferences": {}
      }
    },
    {
      "stage": "retrieval",
      "sources": ["bm25", "dense", "raptor"],
      "ranking_scores": []
    },
    {
      "stage": "supervisor_final_verification",
      "repair_loop_used": 0,
      "reretrieval_loop_used": 1
    }
  ]
}
```

可以不新建数据库表，先用 `supervisor_log` + `retrieval_state.ranking_scores` 组合生成 `/explain/{session_id}` 或在 `GET /result/{session_id}` 中附带 explain block。

## 3. Idea 2: Bounded Recovery Sites 有界失败恢复机制

#### 核心想法

Claude Code 的 Agent Loop 有多个 continue sites，用不同策略处理不同错误。你的项目可以借鉴这个思想，把 Supervisor 的修复能力正式抽象成 Career Matching Recovery Sites。

当前项目已经有：

- too few results -> re-retrieval
- fabrication risk -> repair/drop unsupported resume advice
- missing evidence -> Supervisor verification

可以将这些系统化。

#### 建议定义 5 类 Recovery Sites

| Recovery Site | 触发条件 | 恢复策略 | 最大次数 |
|---|---|---|---|
| `goal_too_vague` | 用户目标过短或缺少方向 | 生成 clarification question | 1 |
| `too_few_results` | Top-K 不足 | 放宽 soft preferences 后 re-retrieval | 1 |
| `missing_evidence` | 推荐岗位缺少 job evidence | 用检索证据回填或删除 unsupported item | 1 |
| `fabrication_risk` | 简历建议未引用原始 evidence span | 删除或重写建议 | 1 |
| `json_parse_failure` | Agent 输出不是合法 JSON | 带错误信息重试一次 | 1 |

#### 论文价值

这可以把 Supervisor 从“普通 LLM 评审器”升级为“有界控制层”：

> The Supervisor does not run open-ended autonomous loops. Instead, it provides bounded recovery sites with explicit triggers, maximum retry counts, and auditable intervention logs.

#### 实现建议

把每次恢复写入 `supervisor_log`：

```json
{
  "stage": "recovery",
  "site": "too_few_results",
  "trigger": "actual_count < planned_top_k",
  "action": "relax_soft_preferences",
  "max_loops": 1,
  "loop_used": 1
}
```

这样既能防止无限循环，也方便答辩展示。

## 4. Idea 3: Career Context Builder 上下文工程模块

#### 核心想法

不要让每个 Agent 自己随意拼 prompt，而是新增一个轻量 `context_builder.py`，负责为不同 Agent 选择最小必要上下文。

Claude Code 的一个核心思想是：模型质量不只取决于模型本身，还取决于它看到了什么上下文。你的项目也一样。

#### 当前问题

现在的 Agent 基本从 `SharedState` 读取数据后自行构造 prompt。随着 state 变大，容易出现：

- prompt 越来越长
- 不同 Agent 看到不该看的信息
- evidence 混乱
- token 成本升高
- LLM 更容易被无关上下文干扰

#### 建议做法

新增阶段化上下文构建：

```text
Intent Agent Context
  -> normalized resume summary
  -> user goal text
  -> selected resume fields

Matching Agent Context
  -> career_state
  -> retrieval candidates
  -> job evidence spans only

Strategy Agent Context
  -> recommended roles
  -> job evidence
  -> original resume evidence spans

Supervisor Context
  -> compact state summary
  -> diagnostics
  -> evidence ids
  -> recovery logs
```

#### 可命名为论文机制

```text
Evidence-preserving Context Selection
```

#### 论文价值

可以说明系统通过上下文选择减少幻觉：

> Each agent receives a task-specific context view rather than the full shared state. This reduces irrelevant information, preserves evidence references, and makes the state transition easier to audit.

## 5. Idea 4: Plan Mode 用户确认职业匹配计划

#### 核心想法

借鉴 Claude Code 的 Plan Mode。职业推荐系统中，用户约束很关键，因此可以在正式检索前让用户确认 Supervisor 生成的 retrieval plan。

#### 适用场景

用户输入：

```text
Find data analyst jobs in Birmingham.
```

Supervisor 输出：

```json
{
  "hard_constraints": {
    "location": "Birmingham"
  },
  "soft_preferences": {
    "role_cluster": "data_analytics"
  },
  "top_k": 5,
  "include_raptor": true,
  "needs_clarification": false
}
```

系统先展示计划，再执行匹配。

#### 为什么适合你的项目

career matching 中很多错误来自用户意图误解，例如：

- location 是硬约束还是偏好
- visa sponsorship 是否必须
- salary 是底线还是期望
- career change 是短期目标还是长期方向
- bridge role 是否可接受

Plan Mode 能把这些歧义提前暴露出来。

#### MVP 实现

不一定要做复杂交互。可以先做 API 级两步：

```text
POST /match/plan
POST /match/execute
```

或者在现有 `/match` 中加参数：

```json
{
  "dry_run_plan": true
}
```

#### 论文价值

这是 human-in-the-loop 的明确体现：

> The user retains decision authority over career constraints before the autonomous matching workflow is executed.

## 6. Idea 5: Dual-space Latent Template Cache

#### 核心想法

你的项目核心创新是 dual-space：显式岗位空间 + 隐式职业轨迹空间。可以进一步借鉴 Claude Code 的缓存思想，把匿名 career cases 和 jobs 的关系离线预计算。

也就是：

```text
career case -> precomputed related job links -> online lookup
```

#### 推荐机制

离线阶段：

```text
career_cases
  -> dense retrieval over job_chunks
  -> top related jobs
  -> write case_job_links
```

在线阶段：

```text
resume embedding
  -> retrieve similar career cases
  -> lookup case_job_links
  -> apply user's hard constraints
  -> merge with explicit retrieval results
```

#### 关键约束

- 隐式路径不能绕过用户硬约束
- 原始简历不能进入公共 case base
- case_job_links 是加速器，不是唯一决策依据
- 隐式路径最好不新增 LLM 调用，保持低延迟

#### 论文价值

这可以成为非常漂亮的创新点：

> The latent career space is implemented as an anonymized template-based retrieval path. Historical career cases are pre-linked to job opportunities offline, allowing online matching to combine explicit job evidence with latent career trajectory patterns.

可以把它写成：

```text
Explicit Job Space: 当前岗位证据匹配
Latent Career Space: 相似职业轨迹模板匹配
```

## 7. Idea 6: Safety and Privacy Guardrails

#### 核心想法

Claude Code 重视权限和安全；你的项目则应该重视 career data privacy、evidence faithfulness 和 fairness boundaries。

建议把它写成独立章节，而不是埋在实现细节里。

#### 建议 Guardrails

1. 原始简历只进入 private memory，不进入公共 case base。
2. 匿名 career case 必须经过 PII 检查。
3. 简历修改建议必须引用 `original_evidence_spans`。
4. 岗位推荐解释必须引用 job evidence spans。
5. 用户 hard constraints 必须通过 SQL filter 执行，而不是只交给 LLM 判断。
6. 隐式 case path 也必须再次应用 hard constraints。
7. 用户可以删除个人 session、feedback、private memory。
8. 不基于敏感属性做推荐解释或排序。

#### 论文价值

答辩时很可能被问：

- 简历隐私如何保护？
- LLM 会不会编造经历？
- 反馈案例库会不会泄露个人信息？
- 推荐结果是否可解释？

这组 guardrails 正好回答这些问题。

## 8. 建议优先级

### P0: 最高收益，建议优先做

1. Career Agent Trace / EXPLAIN
2. Bounded Recovery Sites
3. Career Context Builder

这三个工程量相对小，但论文收益很高。它们能让系统从“能跑”变成“能解释、能审计、能答辩”。

### P1: 明显增强创新性

4. Plan Mode
5. Dual-space Latent Template Cache

这两个是产品和论文亮点。Plan Mode 强化 human-in-the-loop，Latent Template Cache 强化 dual-space 创新。

### P2: 论文安全边界和上线说服力

6. Safety and Privacy Guardrails

如果时间紧，可以先写设计和部分实现；如果时间够，应至少实现 PII 检查、私有记忆隔离、用户数据删除和 evidence gating。

## 9. 不建议现在做的事情

暂时不建议做：

- 重型 Swarm 多 Agent
- Agent 之间自由辩论
- 复杂前端
- 在线 cross-encoder 服务
- 完整 OAuth / JWT 权限系统
- LangGraph / AutoGen / CrewAI 重构
- 复杂自动学习排序权重

原因是当前项目主线已经足够丰富，再加入这些会分散论文叙事，也容易拖慢实现。

## 10. 可以写进论文的贡献点

最终论文可以把贡献点整理为 5 条：

1. 提出一个 Supervisor-guided Agentic RAG 架构，用于从简历到岗位推荐再到职业策略建议的端到端流程。
2. 设计 Shared Structured State，使多个 Agent 通过结构化状态协作，而不是依赖不可靠的自然语言中间摘要。
3. 引入 Evidence-preserving Context Selection，使岗位解释和简历建议都能追溯到原始证据。
4. 设计 Bounded Supervisor Recovery Sites，在目标模糊、检索不足、证据缺失和幻觉风险下进行有界修复。
5. 构建 Dual-space Matching，将显式岗位空间与匿名职业轨迹空间结合，从 job matching 扩展到 career trajectory reasoning。

## 11. 一句话总结

你的项目现在已经不缺“Agent 数量”，最值得补的是 Agent Runtime 的可靠性设计。

如果把 Claude Code 的启发翻译成你的论文语言，核心就是：

```text
用上下文工程保证 Agent 看对信息；
用证据约束保证 Agent 不编造；
用 Supervisor recovery 保证 Agent 出错能有限恢复；
用 trace 保证推荐过程可审计；
用 dual-space cache 保证职业轨迹经验能进入匹配；
用 privacy guardrails 保证简历数据不会失控。
```

