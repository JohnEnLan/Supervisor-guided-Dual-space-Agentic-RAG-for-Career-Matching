"""Stage 3 — Retrieval & Matching Agent。
调用 retrieval.hybrid_search，然后让 LLM 把候选分为 now_fit / stretch_fit / bridge_role，
并抽取匹配证据(evidence)，写入 retrieval_state 与 strategy_state.recommended_roles。
Top-5 匹配解释的多次 LLM 调用用 asyncio.gather 并行（受 deepseek 的 Semaphore 约束）。
"""
# TODO(P0): 实现
