# Cross-Encoder 四通道消融报告（2026-08-06）

语料：`linkedin_ml_cnuk_demo_v1`（31,879 岗，线上服务语料）
命令：`scripts/evaluate_demo_corpus.py --include-raptor --use-cross-encoder`
产物：`data/eval/demo_corpus_cross_v1/`（版本化目录，不覆盖 08-05 的 v1 产物）
方法：同 08-05 报告（15 查询 TREC 池化 + DeepSeek 评审），本轮池 = 四 run 并集
（每池 52–62 岗，共 852 对判定）；诚实口径同前（LLM 标注、池内召回偏乐观）。

## 结果（15 case 宏平均）

| run | P@5 | R@10 | MRR | NDCG@5 |
|---|---|---|---|---|
| bm25_within_pool | 0.413 | 0.149 | 0.680 | 0.458 |
| dense_within_pool | 0.707 | 0.244 | 0.900 | 0.726 |
| base（混合主线） | 0.720 | 0.262 | 0.822 | 0.720 |
| + RAPTOR | 0.800 | 0.284 | 0.967 | 0.839 |
| + Cross-Encoder | 0.907 | 0.310 | 0.900 | 0.897 |
| **+ RAPTOR + Cross** | **0.920** | **0.323** | **1.000** | **0.939** |

## 读数

- **2×2 因子设计**（RAPTOR 与 Cross 为并列单因素 run，非顺序叠加）：
  BM25 池内 < dense 池内 < 混合 base < RAPTOR-only < Cross-only < 两者同开——
  两个增强各自相对 base 的增益独立可归因，组合有叠加收益。
- **raptor_cross 的 MRR = 1.000**：15 条查询的**首位结果全部相关**——对"用户第一眼
  看到什么"这个体验指标是满分。
- Cross 的主要贡献在精度端（P@5 +18.7pp vs base）；RAPTOR 的主要贡献在首位命中
  （MRR +0.145）；两者互补而非重叠。
- 与 08-05 报告的 hybrid_with_raptor（P@5 0.853）不可直接比：本轮池更大
  （四 run 并集 52–62 vs 上轮 38–48）、判定对更多（852 vs 652），池化口径不同。

## 诚实记账（manifest 摘录）

- cross 两 run **applied 比率均 1.0**（15/15 真实精排，无静默降级）；
- requested=60、effective=48–55：CJK 感知预算按设计裁剪窗口并如实记录；
- 池指纹（规范化 {case_id: ordered_job_ids} 的 SHA-256）与预算参数入 manifest；
- 标签仍为 LLM 评审（`llm_judged_pooled`），未经人工复核，论文写作时与人工标注
  数字分开呈现。

## 生产建议

本表最优组合 = RAPTOR + Cross 同开。注意两者启用方式不同：Cross 有环境开关
（`RERANK_ENABLED=true` + `RERANK_ENDPOINT`）；**RAPTOR 无环境开关**——标准产品
主链的 plan 固定 `include_raptor=False`（orchestrator.lock_approved_brief），
目前仅评估脚本与直调检索可开，产品侧启用需在 plan 构造处改一行。
每 run 增加 1–2 次精排调用（单次 135–237ms、约 2 分钱）。

## 附录：实现验收证据摘要（2026-08-06；完整响应见工程线程执行报告，此处为可核对要点）

探针（真实 DashScope key，经典公共端点）：

- 英文 query + 5 文档：`200 / 237.1 ms`，results 按相关性降序、索引完整、分数 ∈[0,1]
  （首名 0.6155…，usage 149 token，request_id 042534b8-…）
- 中文 query + 5 文档：`200 / 134.5 ms`（首名 0.9088…，usage 92 token，
  request_id 63dd4240-…）
- workspace 形态端点以占位 ID 探测返回 `400 BadRequest.IllegalEndpoint`（本机无真实
  WorkspaceId；官方文档以 workspace 形态为生产推荐，经典共享端点实测可用）。

P1 persona 真机对比（同一简历与咨询路径）：

- 开启精排（run 431866c1，203.5 s）：5 条结果 cross_score/cross_rank 全部落袋
  （0.2702/0.1650/0.1576/0.1511/0.1473，rank 0–4），Top-5 变为
  Senior Backend Python Developer / SQL Developer / Software Engineer /
  Senior Software Engineer / Infrastructure Engineer IV；
- 关闭回归（run 3340aef4，98.5 s）：cross 字段全 None，排序与基线一致
  （Senior Backend Python Developer / Azure Data engineer / Cloud Infrastructure
  Engineer / Principal Architect / Senior Java Software Engineer）。

真机彩排还暴露并修复了 mock 覆盖不到的缺陷：`required_skills` 为 `TEXT[]`，
不能与空字符串 COALESCE，已改 `array_to_string(COALESCE(..., ARRAY[]::TEXT[]), ', ')`
并先行红测。
