"""Stage 0 — Resume Intake & Normalization。
输入：PDF/docx/纯文本简历。
输出：写入 resume_state —— 解析(教育/实习/项目/技能) + 排版诊断 +
      内容标准化(背景/任务/行动/结果/技术/能力) + 关键词 +
      original_evidence_spans(保留原文，防编造) + normalized_base_resume。
约束：normalized resume 是 query-side 表示，绝不混入公开 JD 库。
"""
# TODO(P0)
