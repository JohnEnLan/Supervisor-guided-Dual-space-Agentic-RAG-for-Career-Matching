# AGENTS.md — Career-RAG 项目规格（写给 AI 协作者看）

> 本文件是项目的"宪法"。Codex 会自动读取它；用 Codex 时，把本文件内容粘到上下文里。
> 任何代码生成都必须遵守下面的【硬约束】。违反硬约束的代码一律不接受。

---

## 0. 项目一句话

把一个传统的"简历—岗位语义匹配 RAG"系统，升级为 **Supervisor 监督的双空间 Agentic RAG 职业匹配系统**。
本仓库是**毕业设计**，开发周期 **1 个月**，目标是：**主线一条龙能跑通、能多人同时使用、能算出评估指标**。

## 0.1 范围纪律（极其重要）

这是一个月的项目。下面的优先级是不可协商的：

- **P0（必须做，主线）**：数据入库 → 简历归一化 → 混合检索（metadata + BM25 + dense + RRF + bi-encoder）→ Top-K → 三 Agent + Supervisor → FastAPI 多人服务 → 评估指标。
- **P1（机制演示即可，塞样例证明流程通，不追求真实效果）**：双空间记忆、反馈闭环、匿名案例库。
- **P2（如果还有时间才碰，否则只在论文里写"设计与接口已预留"）**：RAPTOR 离线层级树、Cross-encoder Top-20 重排。

**绝不要主动把 P2 的东西塞进主线。** 如果一个改动让 P0 变慢或变复杂，停下来问。

---

## 1. 技术栈（已锁定，不要替换）

| 层 | 选型 | 说明 |
|---|---|---|
| 语言 | Python 3.11+ | |
| Web 框架 | **FastAPI**（异步） | 不用 Flask 同步模式 |
| 并发模型 | **asyncio** | 见硬约束。不用多线程/多进程 |
| 数据库 | **PostgreSQL + pgvector**（HNSW 索引） | 同一个库既存 JD 向量，也存所有用户态 |
| DB 驱动 | **asyncpg** + 连接池（pool） | 不要每请求开新连接 |
| LLM | **DeepSeek V4**（flash / pro，env 配置）| OpenAI 兼容接口 |
| Embedding | **Qwen Embedding**（DashScope）| 维度必须与 pgvector 列维度一致 |
| BM25 | Postgres 全文检索 或 `rank_bm25` 库 | MVP 先用 Postgres `ts_rank`，够用 |
| Rerank | bi-encoder（cosine）默认；cross-encoder 为 P2 可选 | |
| 任务异步 | 先用"提交→轮询"模式；队列（RQ/Celery）为可选增强 | |

模型名、API key、维度全部走 `.env`，不要硬编码。

---

## 2. 硬约束（违反即重写）

1. **状态绝不进进程全局变量。** 所有 Shared Structured State 按 `session_id` 存进 Postgres。
   原因：多人同时使用时全局变量会互相覆盖。服务进程必须是**无状态**的。
2. **并发用 asyncio，不用 threading / multiprocessing。** 本系统是 I/O 密集（等 DB、等 embedding、等 LLM），异步足够。
3. **三个业务 Agent ＝ 三次带不同 system prompt 的 LLM 调用**，共享同一个 state 对象。
   **不是**三个微服务，**不要**引入 LangGraph / AutoGen / CrewAI 等重框架。Harness 自己用普通函数写。
4. **Supervisor ＝ 核查 prompt + 有界循环（bounded loop）。** 每类 loop（clarification / re-retrieval / repair）默认最多触发 1 次，必须有最大次数上限，禁止开放式 while True。
5. **硬过滤走 SQL / metadata，不交给 LLM 判断。** 签证、地点、学历、经验年限、岗位是否关闭等，用 WHERE 子句过滤。
6. **简历归一化阶段必须保留 `evidence_spans`（原文片段）。** 后续 Agent 写简历建议时只能基于真实经历，禁止编造。匹配解释也必须能追溯到 JD 原文。
7. **所有外部调用（LLM / embedding）必须经过 Semaphore 限流**，防止触发 API 速率限制。
8. **一次只实现一个模块并跑通**，不要一次生成多个互相依赖的模块再一起调。

---

## 3. 目录结构

```
career-rag/
├── AGENTS.md                  # 本文件
├── .env.example               # 配置模板（复制成 .env 填真实值）
├── requirements.txt
├── app/
│   ├── config.py              # 读 .env，集中配置
│   ├── state/
│   │   └── schema.py          # Shared Structured State 的数据类定义（单一事实来源）
│   ├── db/
│   │   ├── pool.py            # asyncpg 连接池
│   │   ├── schema.sql         # 建表 + pgvector + HNSW 索引
│   │   └── state_store.py     # 按 session_id 读写 state（无状态服务的关键）
│   ├── llm/
│   │   ├── deepseek.py        # DeepSeek 异步客户端 + Semaphore 限流
│   │   └── qwen_embed.py      # Qwen embedding 异步客户端 + 缓存 + 限流
│   ├── normalization/
│   │   └── resume_intake.py   # Stage 0：解析 → 排版诊断 → normalize → base resume + evidence_spans
│   ├── retrieval/
│   │   ├── hybrid_search.py   # metadata + BM25 + dense → RRF → bi-encoder（三路并行）
│   │   ├── rrf.py             # RRF 融合
│   │   └── raptor.py          # P2：离线层级树，先留空接口
│   ├── agents/
│   │   ├── base.py            # Agent 基类：load_state → prompt → call_llm → write_state
│   │   ├── intent_agent.py    # Agent 1：意图 + 长期职业画像
│   │   ├── matching_agent.py  # Agent 2：检索 + 匹配 + 三分层
│   │   ├── strategy_agent.py  # Agent 3：简历优化 + 缺口 + 路径
│   │   └── supervisor.py      # Supervisor：planning / verification / bounded loops
│   ├── memory/
│   │   ├── private_memory.py  # 用户私有记忆
│   │   ├── feedback.py        # 投递反馈记录
│   │   └── case_base.py       # P1：匿名案例库（写入规则 + 去标识化）
│   ├── evaluation/
│   │   └── metrics.py         # Recall@K / Precision@K / MRR / NDCG@K
│   └── api/
│       ├── main.py            # FastAPI 入口
│       └── routes.py          # 上传简历 / 提交匹配 / 查进度 / 提交反馈
├── scripts/
│   ├── load_jobs.py           # 把公开 JD 数据集解析入库 + 建向量
│   └── seed_cases.py          # 塞样例案例（P1 机制演示用）
├── data/
│   ├── jobs/                  # 原始 JD 数据集
│   ├── resumes/               # 测试简历
│   └── cases/                 # 样例匿名案例
└── tests/
```

---

## 4. Shared Structured State（数据契约 — 单一事实来源）

所有 Agent 读写同一个结构，定义在 `app/state/schema.py`。新增字段先改这里。

```python
# 概念结构（实现用 pydantic / dataclass）
{
  "session_id": str,
  "user_id": str,
  "resume_state": {
    "education": [], "experience": [], "projects": [],
    "skills": [], "resume_quality_issues": [],
    "original_evidence_spans": [],     # 禁止编造的依据
    "normalized_base_resume": str
  },
  "career_state": {
    "current_goal": [], "long_term_goal": [],
    "hard_constraints": {},            # 走 SQL 过滤
    "soft_preferences": {},            # 走排序加权
    "avoid_roles": []
  },
  "retrieval_state": {
    "candidate_job_ids": [], "filter_log": [],
    "ranking_scores": [], "evidence_span_ids": []
  },
  "strategy_state": {
    "recommended_roles": [],           # 分 Now Fit / Stretch Fit / Bridge Role
    "resume_revision_plan": [],
    "career_path": [], "skill_gap_analysis": []
  },
  "feedback_state": {
    "application_history": [], "interview_outcomes": [], "user_feedback": []
  },
  "supervisor_log": []                 # 每次核查/触发 loop 的记录，便于答辩讲解
}
```

---

## 5. 流程（Stage 0–5）

```
用户上传简历/输入
  → Stage 0  Resume Intake & Normalization      (normalization/resume_intake.py)
  → 写入 Shared State (Postgres, by session_id)
  → Stage 1  Intent & Career Profile Agent       (agents/intent_agent.py)
  → Stage 2  Supervisor Planning                  (agents/supervisor.py，可触发 1 次 clarification)
  → Stage 3  Retrieval & Matching Agent           (agents/matching_agent.py → retrieval/hybrid_search.py)
       硬过滤(SQL) → role routing → BM25 ∥ dense → RRF → bi-encoder → 三分层
  → Stage 4  Resume & Career Strategy Agent        (agents/strategy_agent.py)
  → Stage 5  Supervisor Final Verification         (agents/supervisor.py，可触发 1 次 re-retrieval/repair)
  → 返回：分层岗位 + 匹配解释(带 evidence) + 缺口 + 定制简历建议 + 职业路径
  → 用户反馈 → feedback → Supervisor 判断是否沉淀 → 匿名案例库
```

并发要点：Stage 3 里 BM25 / dense / metadata 三路用 `asyncio.gather` 并行；Top-5 匹配解释的多次 LLM 调用并行（受 Semaphore 约束）。

---

## 6. 多人并发架构（"上线"的核心）

1. FastAPI 异步服务，无状态。
2. 每个请求带 `session_id`；所有 state 经 `db/state_store.py` 读写 Postgres。
3. asyncpg 连接池复用连接。
4. 完整匹配耗时长 → "提交即返回 task_id + 前端轮询" 模式；队列为可选增强。
5. LLM / embedding 调用统一过 Semaphore。
6. 水平扩展：因服务无状态，理论上可多实例 + 负载均衡（论文写设计即可，不必真搭）。

---

## 7. 给 AI 协作者的工作方式

- **按模块下单，给清晰的输入/输出契约。** 例：
  "实现 `hybrid_search(query: str, hard_constraints: dict, soft_prefs: dict, top_k: int) -> list[JobCandidate]`，
   内部并行 BM25 与 dense，RRF 融合，bi-encoder 排序，返回带分数与 evidence_span_ids 的候选。"
- **一次一个模块，跑通再下一个。** 不要攒着一起调。
- **写完给一个最小可运行示例 / 测试**，证明它能跑。
- **遇到与硬约束冲突时停下来问**，不要自作主张换架构。

## 8. 实现顺序（建议）

Week1: config → db(schema.sql + pool) → llm(deepseek + qwen) → scripts/load_jobs → normalization → retrieval(hybrid + rrf) → 命令行跑通 Top-K
Week2: state/schema + state_store → agents(base + 1/2/3) → supervisor → api(FastAPI 多人 + 轮询)
Week3: memory(private/feedback/case_base + seed_cases) → evaluation/metrics → 并发优化(gather + semaphore)
Week4: 简单前端 → 打磨 → 论文 → 演示

RAPTOR / cross-encoder 全部排在缓冲区，做不完不影响主线叙事。
