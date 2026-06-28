"""Supervisor — 不是被动 Memory，而是监督者/评估者/编排者/最终核查者。

职能：Planning(Stage 2) / Quality Evaluation / Replanning / Final Verification(Stage 5)。
有界循环：clarification / re-retrieval / repair 各自最多触发 settings.max_*_loops 次。
禁止开放式 while True。每次介入都往 state.supervisor_log 写一条，便于答辩讲解。
"""
from app.config import settings
# TODO(P0): plan(state) -> 检索计划 ; verify(state) -> 是否需要重试
