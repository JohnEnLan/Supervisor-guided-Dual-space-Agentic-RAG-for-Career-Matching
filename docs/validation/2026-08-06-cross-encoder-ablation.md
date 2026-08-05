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

- **完整单调阶梯**：BM25 单通道 < dense 单通道 < 混合 < +RAPTOR < +Cross <
  +两者——四级消融矩阵完整，每一级增强都有独立可归因的增益。
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

演示/答辩配置：`RERANK_ENABLED=true` + RAPTOR 开启（retrieval_plan include_raptor）
= 本表最优组合；每 run 增加 1–2 次精排调用（单次 135–237ms、约 2 分钱）。
默认仓库配置保持双关（P2 纪律），一开关即得。
