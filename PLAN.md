# PLAN.md — Career-RAG 一个月逐日执行计划

> 配合 `CLAUDE.md` 使用。每天开工前看今天的【目标】，收工前对照【完成标准】打勾。
> 落后了不要慌，看文末【落后了怎么救】。

---

## 贯穿全程的 4 条铁律

1. **每天一个可验证的"完成标准"。** 没达到不进下一天的核心任务（可以挪到 buffer 日补）。
2. **一次一个模块，跑通再下一个。** 让 AI 写 → 你跑 → 你 commit → 下一个。绝不攒一堆一起调。
3. **论文边做边写，不要堆到最后一周。** 每周末把当周做的写进论文对应章节，趁记忆还热。
4. **守住 P0 主线。** RAPTOR / cross-encoder 是 P2，永远排在 buffer，做不完不影响答辩叙事。

**每日节奏模板**：开 Claude Code/Codex → "读 CLAUDE.md，今天做 X，先说方案再写代码" → 验收 → `git commit` → 写两行当天日志（踩了什么坑，便于写论文）。

**周里程碑（每周必须达到，否则触发救援预案）**
- 周一结束：命令行能对一份真实简历跑出 Top-K 岗位。
- 周二结束：FastAPI 服务起来，多人能同时提交、互不串。
- 周三结束：双空间机制能演示 + 检索指标能算出来。
- 周四结束：有前端、能整套演示、论文初稿齐。

---

## Week 1 — 数据 + 单条检索流水线（不上 Agent）

> 目标：把"简历进 → Top-K 岗位出"这条命令行链路打通。这是整个系统的地基。

### Day 1 — 环境 + 数据（最关键的一天，别省）
- [ ] 装 PostgreSQL + pgvector（本地或 Docker），建库，跑 `app/db/schema.sql`。
- [ ] 建 venv，`pip install -r requirements.txt`。
- [ ] `.env.example` → `.env`，填 DeepSeek、Qwen 的 key。
- [ ] 写两个最小测试：一次 DeepSeek 对话返回文本；一次 Qwen embedding 返回向量，**确认维度 == `EMBED_DIM` == `schema.sql` 的 `vector(N)`**（不一致现在就改）。
- [ ] 去 Kaggle 下载一个 job postings 数据集，放进 `data/jobs/`。
- **完成标准**：DeepSeek 返回文本、Qwen 返回正确维度向量、schema.sql 无报错执行、数据集在本地。

### Day 2 — `scripts/load_jobs.py` 上半：JD 字段化入库
- [ ] 先拿 **50 条**做：DeepSeek 解析 JD → 抽取标题/公司/地点/签证/学历/经验/职责/技能等 → 写 `jobs` 表。
- **完成标准**：`SELECT * FROM jobs LIMIT 50` 字段干净、合理。

### Day 3 — `load_jobs.py` 下半：分块 + 向量 + 索引 + 扩量
- [ ] field-aware 分块 → Qwen embedding → 写 `job_chunks`（embedding + tsv）。
- [ ] 跑通后扩到全量（几千条）。HNSW / gin 索引已由 schema.sql 建好。
- **完成标准**：手写一条向量近邻 SQL，能返回语义相关的 chunk。

### Day 4 — `normalization/resume_intake.py`（Stage 0）
- [ ] PDF/docx/文本解析 → DeepSeek 归一化 → 写 `resume_state`：结构化经历 + 排版诊断 + **`original_evidence_spans`（保留原文，防编造）** + `normalized_base_resume`。
- **完成标准**：喂一份样例简历，得到干净的 base resume + evidence spans。

### Day 5 — `retrieval/hybrid_search.py`（已有骨架，填实）
- [ ] 硬过滤(SQL) → BM25 ∥ dense（`asyncio.gather` 并行）→ RRF → bi-encoder 排序。
- **完成标准**：用 normalized resume 当 query，命令行返回带分数的 Top-K `job_id`。

### Day 6 — 端到端命令行串联
- [ ] 一个脚本：简历文件 → 归一化 → 检索 → 打印 Top-K + 基本匹配信息。
- **完成标准**：一条命令，对一份真实简历产出 Top-K。**Week1 里程碑达成。**

### Day 7 — Buffer + 写论文「系统设计」章节
- [ ] 补前 6 天没填完的坑。
- [ ] 趁热写论文：整体架构、Stage 0–5、双空间设计（实现部分先占位）。

---

## Week 2 — 三 Agent + Supervisor + 多人 FastAPI 服务

> 目标：套上 Agent 层，并做成多人能同时用的无状态服务。

### Day 8 — Agent 1：`agents/intent_agent.py`
- [ ] 继承 `BaseAgent`，提取 current/long-term goal、硬约束、软偏好、avoid_roles → 写 `career_state`。区分硬约束与软偏好，不过度推断长期目标。
- **完成标准**：给定 base resume + 一句用户意图，输出结构化 career_state。

### Day 9 — Agent 2：`agents/matching_agent.py`
- [ ] 包 `hybrid_search`，再让 LLM 把候选分 now_fit / stretch_fit / bridge_role，抽匹配证据 → 写 retrieval_state + recommended_roles。
- **完成标准**：输出三分层岗位，每条带匹配证据。

### Day 10 — Agent 3：`agents/strategy_agent.py`
- [ ] 匹配解释 + 能力缺口 + 定制简历建议 + 短/中/长期路径 → 写 strategy_state。**只能基于 evidence_spans，禁止编造。**
- **完成标准**：产出一份完整"推荐+改简历+补能力+路径"建议。

### Day 11 — `agents/supervisor.py`
- [ ] Stage 2 planning（生成检索计划、可触发 1 次 clarification）+ Stage 5 final verification（可触发 1 次 re-retrieval/repair）。所有 loop 有最大次数；每次介入写 `supervisor_log`。
- **完成标准**：能演示一次"检索结果太少→Supervisor 放宽软偏好→重检索"。

### Day 12 — Orchestrator：把 Stage 0–5 串起来
- [ ] 一个流程函数，按 0→5 顺序跑，全程经 `state_store` 按 session_id 读写 Postgres。
- **完成标准**：一次调用，从简历到完整输出，state 全程落库。

### Day 13 — `api/`：FastAPI 多人服务
- [ ] 路由：`POST /resume`、`POST /match`（提交即返回 session_id，后台跑）、`GET /status/{sid}`（轮询）、`POST /feedback`。
- **完成标准**：浏览器/curl 提交简历，轮询拿到结果。

### Day 14 — Buffer + 并发自测 + 写论文
- [ ] 同时开 2–3 个 session 并发提交，确认 state 不串、status 各自独立。**Week2 里程碑达成。**
- [ ] 写论文：Agent 设计、Shared State、多人并发架构。

---

## Week 3 — 双空间记忆 + 评估指标 + 并发优化

> 目标：把隐性职业空间的机制跑通（塞样例），算出指标，做并发优化。

### Day 15 — `memory/private_memory.py` + `memory/feedback.py`
- [ ] 私有记忆读写、投递反馈记录（过初筛/OA/面试/offer/拒+原因）。
- **完成标准**：能写入并读回某用户的历史与反馈。

### Day 16 — `memory/case_base.py` + `scripts/seed_cases.py`
- [ ] 去标识化写入规则 + 案例检索；塞 10–20 条匿名样例案例。
- **完成标准**：能按背景相似度检索到相关案例。

### Day 17 — 反馈闭环（机制演示）
- [ ] 串起来：用户反馈 → Supervisor 判断是否有价值 → 匿名化 → 写案例库 → 影响后续推荐权重。
- **完成标准**：能完整演示一遍闭环（哪怕只是样例数据驱动）。

### Day 18 — `evaluation/metrics.py`
- [ ] 做一个小评估集（标注 简历→相关岗位），算 Recall@K / Precision@K / MRR / NDCG@K。
- **完成标准**：跑出一张指标表。**Week3 里程碑达成。**

### Day 19 — 并发优化（论文性能章节素材）
- [ ] Top-5 匹配解释的多次 LLM 调用改 `asyncio.gather` 并行；确认 Semaphore 生效；测优化前后单次响应耗时。
- **完成标准**：有一组"串行 vs 并行"的延迟对比数据。

### Day 20 — 缓冲 / 可选 RAPTOR
- [ ] 若进度超前，做 RAPTOR 离线层级树（P2）；否则纯 buffer 还债。

### Day 21 — Buffer + 写论文「评估」章节
- [ ] 把指标、并发对比、反馈闭环写进论文。

---

## Week 4 — 前端 + 打磨 + 论文 + 演示

> 目标：能完整演示给多人试用，论文定稿，答辩有备份。

### Day 22 — 最小前端
- [ ] 一个页面：上传简历 → 展示三分层岗位 + 匹配解释 + 能力缺口 + 职业路径。简单 HTML/JS 即可，别在前端花太多时间。
- **完成标准**：非技术的人也能点着用。

### Day 23 — 前端打磨 + 整体走查
- [ ] 端到端体验过一遍，修边角；确认轮询、长任务、错误提示都正常。

### Day 24 — 全系统测试 + 演示数据准备
- [ ] 修 bug；准备几份能体现 now/stretch/bridge 三分层效果的"演示简历"。
- **完成标准**：一套稳定可复现的演示流程。

### Day 25–26 — 论文定稿
- [ ] 补齐所有章节：背景、设计、实现、评估、隐私安全、创新点、总结。

### Day 27 — 答辩彩排 + 备份
- [ ] 做 slides，彩排一遍；**录一段演示视频**作备份（防现场翻车）。

### Day 28 — 总 Buffer
- [ ] 留给意外。每个一个月的项目，最后一天都在还债——这是设计好的，不是失败。

---

## 落后了怎么救（按顺序砍，从下往上保）

进度告急时，按这个顺序砍，越靠前越先砍，主线 P0 最后才动：

1. 砍 RAPTOR、cross-encoder（本来就是 P2，论文写"接口已预留"）。
2. 反馈闭环只演示"单向写入案例库"，不做"反哺权重"。
3. 前端退化成最简表单，甚至用 FastAPI 自带的 `/docs` 交互页演示。
4. 评估集缩到几十条，指标够算出一张表即可。
5. Agent 3 的职业路径建议减少花样，保证"推荐+改简历+缺口"三件套在就行。

**永远不能砍的底线（砍了就不成立）**：数据入库、简历归一化、混合检索出 Top-K、三 Agent + Supervisor 跑通、多人无状态服务、一套能算的指标。守住这六样，你就是一个完整、能答辩、能讲出创新点的毕业设计。

---

## 每周末自检三问
1. 这周的里程碑达到了吗？没达到，下周一优先补，而不是往前冲。
2. 这周做的写进论文了吗？
3. 有没有偷偷把 P2 的东西塞进主线？有就砍回去。
