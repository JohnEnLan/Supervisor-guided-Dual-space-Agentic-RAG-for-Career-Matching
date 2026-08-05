# Cross-Encoder 精排实施方案（v6 — 双审第四轮候选稿）

> 修订史：
> v1→v2 窗口前移 + 单调重映射（双审阻断三点）。
> v2→v3 子 agent 二审 10 条（CJK 预算、flag 门控、退化情形等）。
> v3→v4 Codex 二审 9 条（撤销跨批合并、双分支降级、cross_rank 平局键、
> explicit_score Optional、endpoint fail-fast、评估版本化等）。
> v4→v5 子 agent 三审 W1–W7（raptor 前缀不等价、BM25 次键、全平分惰性等）。
> v5→v6 Codex 三审：**降级机制第三次简化定稿——"失败时懒执行完整关闭路径"**，
> 双分支与全部前缀等价假设（连 HNSW 近似检索都不严格前缀）整体删除；
> requested/applied 窗口术语钉死；Semaphore 硬约束回补；endpoint 校验覆盖显式
> 开关路径；est_tokens 覆盖全部非 ASCII；manifest 按 run×case 记账。
> 架构骨架（重映射语义、单请求、cross_rank 平局键）已获双方两轮裁决认可，不再变。

## 0. 现状锚点（双审三轮核验，个别行号随 HEAD 漂移以函数名为准）

- 排序公式 `_rerank_candidates`（hybrid_search.py:446 定义 / 475-481 公式 / 511 截断，
  top_k 仅末尾切片）：`0.30×RRF + 0.10×BM25 + 0.60×max(dense,raptor)
  + 软偏好加分(上限 0.20，hybrid_search.py:418) + 字段加分(上限 0.08，:601)`。
- 关闭路径 `recall_k = max(top_k*4, top_k, 10)`（686）；融合池
  `fused[:max(top_k*3, top_k)]`（731）；RRF/通道分归一化为池内 min/max（458-461）。
- **前缀等价性不可依赖（v6 设计前提）**：BM25 `ts_rank_cd` 平分序在不同 LIMIT 下
  无保证（PostgreSQL 官方口径）；dense 是 HNSW **近似**检索，LIMIT/ef_search/迭代
  扫描都影响返回集合；raptor 内部节点→叶→按 job 聚合→过滤（raptor.py:235/281/352），
  完全不是前缀可切结构。**因此任何"宽召回切前缀重建关闭路径"的方案都不成立**，
  v6 的降级不再依赖该假设。
- `JobCandidate` frozen（114）；`explicit_score: float = 0.0` 非 Optional（137）。
- dual_space_search：β 混合后 `sorted(fused, key=(-score, -explicit_score, job_id))`
  （89-96）；`_bounded_float` 只对隐式命中候选夹 [0,1]（69-72）——既有不对称，
  本次不修；**cross 重映射会重新分配区间内分数，可能改变哪个候选越过 1.0 被夹**，
  如实记录该继承效应（见 §1 末），并加 characterization 测试。
- 开关经 approved_plan 流转（supervisor:96 / orchestrator:423 / 白名单 :501 /
  浅复制保键 :382）；graph checkpoint 持久化 plan（nodes.py:34/42 消费）；
  runner 的 `_latest_retrieval_plan`（231-243）仅用于终态报告不回流执行。
- bounded re-retrieval → 一次 run 至多两次逻辑精排。
- `ranking_scores` 唯一写入方 matching_agent（327-363）；读取方全 `.get`；
  trace/DTO 白名单（trace.py:43、schemas.py:268 extra=forbid）→ cross 不进公开面。
- `query_builder.py:39` 查询文本无长度帽（CJK 预算动机）。
- **DashScope Text Rerank 官方契约**：score ∈ [0,1] 且**禁止跨请求比较**；
  results 按相关性降序返回（须按 index 重建输入对齐）；单项 4,000 token、
  单请求 30,000 token；当前官方文档展示 workspace 形态端点。
- 现有测试 fake 均 `**kwargs`；基线 427 项全绿。

## 1. 分数与排序语义

`JobCandidate` 新增：`cross_score: float | None = None`、`cross_rank: int | None = None`。

**窗口术语（钉死）**：

```
requested_window = pool[:cross_count]        # 想精排的候选
applied_window   = pool[:effective_count]    # 预算允许、实际发送 provider 的前缀
untouched_tail   = pool[effective_count:]    # 保持原分，cross_score/cross_rank 全 None
```

`lo/hi`、全平判断、cross_rank 都只定义在 **applied_window** 上；
`effective_count < 2` → `applied=False` 整体走基线。

**applied_window 重排规则**：

1. 按 `(cross_score 降序, 原位置升序)` 排序。
2. **provider 分全相等**：顺序与分数保持基线，仅记 cross_score；**cross_rank 全部
   保持 None**（写了会让 dual 平局键用"原位置序"顶掉关闭路径的 job_id 断平序）。
   cross_rank 只在 provider 给出**至少两个不同分数**时写入。
3. 一般情形（applied_window 原分区间 `[lo, hi]`，`hi > lo`）：第 i 名（**0 基**，
   首名=hi、末名=lo）`score = explicit_score = hi - i×(hi-lo)/max(len-1, 1)`，
   **全精度不 round**；前缀 lo ≥ 残段首分 → 拼接单调自然成立。
4. **hi == lo 且 cross 有区分**：分数保 hi，排序靠 cross_rank——dual 排序键扩展为
   `(-score, -effective_explicit, cross_rank if not None else +inf, job_id)`。
   平局键同时解决尾部分数恰等于 hi 的倒挂。已核验：现有 dual 测试候选 cross_rank
   全 None → 键第三元全 +inf → 退化为原语义，零破坏。
5. `len == 1`：保留原分；provider 无对比对象，按 §1.2 统治规则（至少两个不同分数
   才写 rank）**不写 cross_rank**。

**clamp 继承声明**：β 混合消费的是 `_bounded_float(重映射后的显式分)`（仅隐式命中
候选被夹 [0,1]）——cross 继承并可能触发该既有不对称（重排可改变谁越过 1.0），
本次不修复；加 `score>1 + 部分隐式命中` 的 characterization 测试锚定行为。

**口径声明**：cross 生效时 applied_window 内顺序完全由语义相关性决定；软偏好
只作用于召回与窗口准入（论文/答辩按此表述）。

## 2. 窗口、池深与召回

```
enabled     = settings.rerank_enabled if use_cross_encoder is None else use_cross_encoder
n           = settings.rerank_top_n if rerank_top_n is None else rerank_top_n   # 参数与配置同界 1..200
pool_depth  = max(top_k * 3, n)
cross_count = min(n, len(scored_pool))     # provider 收到的文档数永远 ≤ n
recall_k    = max(top_k * 4, n * 4, 10)    # enabled 时；disabled 走原式（同一 helper）
```

- `top_k=50, n=20` → 只精排 20（测试断言发送文档数恰为 n）；
- `top_k=5, n=20` → 池内 6–20 名可进前 5；
- 说明：`hnsw.ef_search`（默认 40）对宽召回 dense 通道封顶（n*4>40 时至多产出
  ef_search 条 chunk）——影响窗口填充度，非正确性问题，记录即可；
- BM25 平分次键：与懒降级正确性**无关**，且会改变关闭路径历史平分序——
  **移出本次改动范围**（Codex 四审建议），留作独立的确定性修缮事项。
- **实施守则（四审 APPROVE 附带，验收时逐条核）**：
  1) `pool_depth = max(top_k*3, n) if enabled else max(top_k*3, top_k)`——
     关闭路径的池深/召回不受 n 任何影响；
  2) 懒降级递归调用**原样透传** query/hard_constraints/soft_prefs/top_k/
     include_raptor，仅强制 use_cross_encoder=False；
  3) `RerankMisconfigured` 与 `CancelledError` 在宽泛 except 之前单独穿透；
     **fallback 调用放在 catch 块之外**（其自身的 DB/embedding 异常直接传播，
     不被二次捕获、不再递归）；
  4) `effective_count<2` 直接 fallback ⇒ len==1 重排分支在完整管线不可达，
     实现按 fallback 规则即可（单元测试仍可直测该函数分支）；
  5) "逐字节一致"指同参数、同代码路径的**构造等价**；跨时刻数据库快照差异
     本就不在承诺内。

## 3. 新模块 `app/llm/reranker.py`

```
class RerankMisconfigured(RuntimeError): ...   # 配置类失败：上抛不降级
class RerankUnavailable(RuntimeError): ...     # 运行类失败：调用方降级

async def rerank_documents(query: str, documents: list[str]) -> list[float]
    # 严格等长、按输入序对齐；绝不静默增删文档
```

- **Semaphore（仓库硬约束 AGENTS.md:60，v4 遗漏回补）**：模块级
  `asyncio.Semaphore(settings.rerank_max_concurrency)`；**每次 HTTP attempt 在
  信号量内、退避等待在信号量外**；并发峰值测试参照现有 LLM/embedding 模式。
- **端点**：`RERANK_ENDPOINT`（完整 URL）。`.env.example` 给出 workspace 形态
  （当前官方文档形态）为主、经典公共端点标注 **legacy/以探针实测为准**。校验三层：
  1) 启动 fail-fast：`RERANK_ENABLED=true` 时直接执行 `_require_rerank_endpoint()`
     全套校验（空/非法 URL/`{WorkspaceId}` 字面量都在 boot 就死，不等首次 run）；
  2) **解析出 enabled=True 的一切路径**（含评估显式 True）在调用前
     `_require_rerank_endpoint()`——空/非法 URL/含未替换 `{WorkspaceId}` 字面量 →
     `RerankMisconfigured` 上抛不降级；
  3) 评估脚本在进入循环前预检 fail-fast，绝不跑到一半静默降级。
- 请求体：`{"model", "input": {"query", "documents"},
  "parameters": {"return_documents": false, "top_n": len(documents)}}`。
- **响应严格校验**：按 index 重建输入对齐（官方按相关性降序返回）；索引恰为
  `{0..len-1}`；分数有限且 ∈[0,1]；违例 → RerankUnavailable。含乱序 index 测试。
- **token 预算（三层检查，估算覆盖全部字符）**：
  - `est_tokens(text) = non_ascii_chars + ceil(ascii_chars / 3)`（CJK/阿拉伯文/
    西里尔/emoji 一律按 1 token/字符保守计）；
  - 三层：query ≤ 3,800；每文档 ≤ 3,800；`query×count + Σdoc ≤ 27,000`；
    **单项按 token 估算超限时做二次截断（截字符到 token 达标），不剔除文档**；
  - 截断配置双界：`RERANK_QUERY_MAX_CHARS`（默认 600，100..4000）、
    `RERANK_DOC_MAX_CHARS`（默认 1500，100..4000）；
  - effective_count = 满足三层检查的最大前缀；计算在**集成层**，client 只校验
    （等长契约，不内部缩减）；
  - 测试：中文/阿拉伯文/emoji 估算、超大配置值、单项超限、effective<requested。
- 重试：仅超时/连接错/429/5xx 重试 1 次（0.5s 退避）；401/403 →
  RerankMisconfigured；其余 4xx → RerankUnavailable 不重试；CancelledError 穿透。
  口径：**一个逻辑请求 = 最多两个 HTTP attempts**。
- 每次调用 `async with httpx.AsyncClient(timeout=...)`；日志只记原因码。

## 4. 管线集成

### 4.1 懒降级（v6 定稿——第三次简化，删除全部前缀假设）

```
enabled 路径（hybrid_search 内）:
  宽召回(recall_k) → collapse → RRF → fused[:pool_depth] → 水合
  → _rerank_candidates(top_k=len(pool)) 全池打分
  → requested/applied 窗口 → 文档补充 SQL（title/required_skills/raw_jd 全 coalesce）
  → rerank_documents（单请求）→ §1 重排 → 拼尾 → [:top_k]

降级（RerankUnavailable / 文档 SQL 异常 / budget_empty 等一切可降级失败）:
  **懒执行完整关闭路径**：以 use_cross_encoder=False 重新走同一 hybrid_search
  流程（内部递归一次，递归保护：fallback 调用显式 False 不可再进 cross 分支）。
  等价性由"同一代码路径、同一参数"**按构造保证**——不存在前缀假设。
  成本：仅失败路径多一轮召回（查询 embedding 有 LRU 缓存命中、DB 查询毫秒级）。
```

- **失败通道三轨**：
  - `RerankMisconfigured`（endpoint 缺失/非法、401/403）→ **上抛不降级**；
  - `RerankUnavailable`（超时/连接/429/5xx/契约违例）与文档 SQL 异常 → 懒降级；
  - `budget_empty`（effective_count<2）→ `(applied=False)` 懒降级；
  - `_apply_cross_encoder` 返回 `(applied, candidates, reason_code)`；applied 与
    原因码记日志；**可选加强（不强制）**：matching_agent 侧检测
    "plan 标 True 而候选 cross_score 全 None"时补一条 supervisor_log 审计条目，
    hybrid_search 保持纯检索函数不动。
- **文档缺失三态**：部分字段 NULL → coalesce 照常精排；SQL 异常 → 懒降级；
  窗口岗位整行缺失或全部文档三字段皆空 → 视同 SQL 异常懒降级。三态分立测试。
- 元数据/证据查询按 enabled 池执行（降级路径自带自己的查询，无并集问题）。

### 4.2 开关流转与旧 checkpoint

- 新 plan：`plan_retrieval` / `_lock_approved_brief` 写入
  `"use_cross_encoder": settings.rerank_enabled`（run 级一次解析）；
  `_public_retrieval_plan` 白名单透出；`_build_reretrieval_plan` 浅复制保键。
- 旧 checkpoint 缺键 → 恢复边界确定性写回 **False** 并持久化；matching_agent 只消费
  已解析布尔不读 settings；`hybrid_search(None)` 直调才回落全局设置。
  测试："旧 checkpoint + 新环境 RERANK_ENABLED=true 恢复后仍 False"。
- CLI：`hybrid_search.py` 入口加 `--use-cross-encoder`。

### 4.3 explicit_score 改 Optional + 统一取值

- 字段改 `explicit_score: float | None = None`（hybrid 构造点照旧显式赋值）；
- `effective_explicit_score(c) = c.explicit_score if is not None else c.score`；
- 消费点全清单（三审封闭核验）：matching_agent 342/386/397/449、
  dual_space_search 69（helper 化）+ 93 排序键（用 helper 值，不对 Optional 负号）；
  trace/schemas 读落库值本就安全；implicit_search 不读该字段。
- 三态测试：未赋值回落 / 合法 0.0 不回落 / 正分。

### 4.4 其余

- `_write_retrieval_state` 加 `"cross_score"`、`"cross_rank"`。
- 公开面零变化（DTO/OpenAPI/generated.ts/前端不动）；隐式检索不接 cross。

## 5. 配置

| 键 | 默认 | 约束 |
|---|---|---|
| `RERANK_ENABLED` | `false` | bool |
| `RERANK_MODEL` | `gte-rerank-v2` | Literal |
| `RERANK_ENDPOINT` | `None` | enabled 时必填；URL 校验 + 拒绝 `{WorkspaceId}` 字面量 |
| `RERANK_TOP_N` | `20` | Field(ge=1, le=200)；调用参数同界 |
| `RERANK_TIMEOUT_SECONDS` | `5` | gt=0 |
| `RERANK_MAX_CONCURRENCY` | `4` | ge=1 |
| `RERANK_DOC_MAX_CHARS` | `1500` | ge=100, le=4000 |
| `RERANK_QUERY_MAX_CHARS` | `600` | ge=100, le=4000 |

## 6. 测试矩阵（全 mock）

reranker：契约对齐（乱序 index 重建）/ 索引与分数校验（含 >1.0）/ 重试三轨
（429 重试、401 Misconfigured、400 Unavailable 不重试、Cancelled 穿透）/ 等长契约 /
Semaphore 并发峰值 / est_tokens（中文、阿拉伯文、emoji）/ 三层预算与单项超限。

hybrid×cross：默认关零请求 / 显式覆盖 / 窗口边界四组（含 top_k=50,n=20 恰发 20 文档、
窗口=1）/ 重排一般情形（区间=applied_window、全精度、全局单调）/ provider 全平分
（与基线逐字节一致、cross_rank 全 None、"全平+dual 完全平局+job_id 逆序输入"用例）/
hi==lo 平局键 / cross 分 0.0 / **懒降级等价**（API 失败、SQL 异常、全空文档 → 与独立
False 调用逐字节一致；递归保护）/ NULL 三态 / effective<requested（尾部原分、
拼接单调断言）/ clamp 继承 characterization（score>1 + 部分隐式）。

流转：plan 写入/透传/保键/白名单 / 旧 checkpoint 缺键→False / explicit_score 三态 /
ranking_scores 新键 characterization / 配置 Field 边界 + enabled 无 endpoint
启动 fail-fast + 显式 True 路径 Misconfigured。

评估脚本：RUN_SPECS 两布尔全显式 / flag 门控 / within_pool 派生自 base run /
版本化目录不覆盖 v1 / applied 比率断言 / endpoint 预检。

全量 pytest 绿（基线 427 → N 列账）；pyflakes 干净；OpenAPI 快照 diff 为空。

## 7. 评估消融

- RUN_SPECS（两布尔全显式 + flag 门控）：base(F,F) 恒跑；raptor(T,F)；cross(F,T)；
  raptor_cross(T,T)——后三者各随其 flag。
- `bm25_within_pool` / `dense_within_pool` 派生自 base run（命名如实）。
- cross run `rerank_top_n = 2×args.top_k`（60）；实际 effective_count 由预算决定，
  **manifest 按 run × case_id 记录 requested/effective**；可选在 eval 降低
  `RERANK_DOC_MAX_CHARS` 换更深 effective 并记录。
- 输出目录默认 `data/eval/demo_corpus_cross_v1/`（--output-dir 可改），不覆盖 v1；
  manifest 含 schema_version、run 清单与开关、**池指纹 = 规范化
  `{case_id: ordered_job_ids}` 映射的 SHA-256**、applied 比率、截断预算。
- 脚本开跑前 endpoint 预检 fail-fast；cross run applied 比率必须 > 0。

## 8. 真实验证（执行方，报告附原始输出）

1. 探针：英文 query + 5 文档；中文 query + 5 文档。验证端点形态/契约/延迟，
   实测与 §3 不符则以实测为准修正并注明。
2. `RERANK_ENABLED=true` + 显式 endpoint 跑 P1 persona：对比关闭时首位变化或
   cross 字段落袋；run 时长可接受。
3. 关闭开关回归。

## 9. 交付物与边界

代码：`app/llm/reranker.py`（新）、`hybrid_search.py`、`dual_space_search.py`、
`matching_agent.py`、`orchestrator.py`、`supervisor.py`、`graph`（旧 plan 迁移点）、
`config.py`、`api/main.py`、`.env.example`、`scripts/evaluate_demo_corpus.py`；
不动：结果 DTO / trace / OpenAPI / 前端 / 隐式检索；
报告：探针输出、彩排对比、测试账目、OpenAPI 零 diff；**不执行 git commit**。

## 10. 成本与延迟

- 每 run ≤2 次逻辑精排；每次 = 1 个逻辑请求 = **最多 2 个 HTTP attempts**；
  单次最坏 5s×2+0.5s ≈ 10.5s 后懒降级（多付一轮召回，毫秒级 DB + 缓存命中的
  query embedding）；
- 单请求 ≤27K token ≈ 2 分钱内；评估 15 查询 × 2 cross run ≈ 几毛钱。

---

## 附录：处置索引（四轮）

一审/二审处置见 v4 附录（git 历史 `docs/cross_encoder_plan.md@9d518f1..`）。

### 三审子 agent（W1–W7）→ v5/v6
| W1 raptor 前缀不等价 | v6 懒降级整体删除前缀依赖（连同 v5 的独立窄调用一并简化掉） |
| W2 BM25 平分序 | §2 chunk_id 次键（确定性修缮，与降级无关）；HNSW/ef_search 说明入 §0/§2 |
| W3 base_recall_k 抄漏 | v6 懒降级后无此概念；recall helper 单一事实来源仍保留 |
| W4 假 cross run | §3 三层 endpoint 校验 + §4.1 Misconfigured 不降级 + §7 applied 断言 |
| W5 全平分 cross_rank | §1.2 全平不写 rank |
| W6 effective 区间 | §1 窗口术语三分 + 区间=applied_window |
| W7 est_tokens 漏字符 | §3 non_ascii 全按 1 token/char |

### 三审 Codex（1–8）→ v6
| 1 [阻断] 前缀假设四反例 | §4.1 懒降级（按构造等价，选其"懒执行窄召回"修法并推广到整条路径） |
| 2 全平分新 bug | §1.2 cross_rank 全 None + 逆序 job_id 测试 |
| 3 clamp 理由修正 + 锚点数字 | §0/§1 软偏好 0.20、字段 0.08 更正；clamp 继承声明 + characterization |
| 4 Semaphore 遗漏 | §3 回补（硬约束）+ 并发测试 |
| 5 endpoint 显式路径缺口 | §3 三层校验 + `{WorkspaceId}` 拒绝 + 评估预检 |
| 6 effective/窗口歧义 | §1 术语三分钉死 |
| 7 est_tokens + 单项上限 | §3 三层检查 + 配置双界 |
| 8 manifest/成本口径 | §7 run×case 记账 + 池指纹规范化 + §10 attempts 口径 |
