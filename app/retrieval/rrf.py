"""Reciprocal Rank Fusion：把多路召回结果按排名融合，对分数量纲不敏感。"""


def rrf_fuse(rank_lists: list[list[tuple[str, float]]], k: int = 60):
    """每个 rank_list 是按相关性降序的 [(job_id, score), ...]。
    返回融合后按 RRF 分数降序的 [(job_id, rrf_score), ...]。
    """
    scores: dict[str, float] = {}
    for lst in rank_lists:
        for rank, (job_id, _orig) in enumerate(lst):
            scores[job_id] = scores.get(job_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)
