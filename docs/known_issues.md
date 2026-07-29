# 已知问题清单（2026-07-29 Codex 全库巡检 · 暂缓项）

> 来源：Codex 只读巡检（11 high / 18 medium / 2 low）。高优先与低成本项已在同日修复批次处理；
> 本清单是**有意暂缓**的设计级事项，均不阻塞主线运行与 LangGraph 迁移。逐项给出暂缓理由与建议时机。

| # | 事项 | 位置 | 暂缓理由 | 建议时机 |
|---|---|---|---|---|
| 1 | 案例库双模型统一：`career_cases`（写入链）与 `anonymous_resume_cases + case_job_outcomes`（隐式检索读取链）互不连通 | app/memory/、scripts/seed_cases.py | 涉及表结构与读写链设计决策，P1 演示走 seed_cases 即可 | 迁移后 / 答辩后 |
| 2 | v1 反馈闭环服务化：v1 reaction 只持久化，不做 legacy 已有的 case 沉淀闭环 | app/api/v1/feedback.py | 依赖 #1 的模型统一；文档 v7.1 已如实声明 | 与 #1 一起 |
| 3 | RAPTOR 重建代际清理：数据源消失的旧节点不删除 | app/retrieval/raptor.py:518-602 | RAPTOR 主线关闭，仅消融实验用 | 重跑消融前 |
| 4 | RAPTOR role-summary 绕过 allow_ids：job_id 为 NULL 的节点不受硬过滤白名单约束 | app/retrieval/raptor.py:368-384 | 同上，主线关闭 | 重跑消融前 |
| 5 | case 软偏好从未被排序消费：`case_target_roles/case_bridge_roles` 持久化后无读取方 | app/memory/feedback_loop.py:59-63 | 产品决策（是否让历史案例影响排序）未定 | 与 #1/#2 一起 |
| 6 | resume 错误码细分：归一化失败只存 `resume_error`，preview 对 processing/error 同为 409 | app/api/v1/sessions.py:243-246 | 前端目前不区分，UX 优化级 | 前端打磨期 |
| 7 | vector 维度启动核验：DB 列固定 vector(1024)，`EMBED_DIM` 改动要到运行时才报错 | app/db/schema.sql, app/config.py | 单机部署维度不会变；加启动断言属防御性 | 部署工程化时 |
| 8 | 评估集重复 case ID 静默覆盖 | scripts/evaluate_system.py:30-48 | 当前数据集无重复；策略（报错 vs 合并）待定 | 扩数据集前 |
| 9 | AsyncOpenAI 客户端无 aclose：测试反复启停可能残留 transport | app/llm/*.py | 无生产影响，进程退出即释放 | 顺手时 |
| 10 | 持久任务队列：BackgroundTasks 进程内执行，重启丢 in-flight（已加启动 stale 回收缓解） | app/api/v1/ | Release 1 工程化范畴，计划文档已有设计 | 产品化阶段 |
