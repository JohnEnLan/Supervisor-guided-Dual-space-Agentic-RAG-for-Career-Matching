"""把公开 JD 数据集(如 Kaggle job postings)解析入库：
用 DeepSeek 字段化解析 JD -> 写 jobs 表 -> field-aware 分块 -> Qwen embedding ->
写 job_chunks(embedding + tsv) -> 已由 schema.sql 建好 HNSW/gin 索引。
这是 Week1 第一件事，整个系统的地基。
"""
# TODO(P0)
