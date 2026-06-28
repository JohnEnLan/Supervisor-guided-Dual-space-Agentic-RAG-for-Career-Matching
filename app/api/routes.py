"""路由：上传简历 / 提交匹配(返回 session_id) / 查进度(轮询) / 提交反馈。

多人并发要点：每个请求带/生成 session_id；匹配是耗时任务，
提交后立即返回 session_id，后台跑流水线并更新 session_state.status，
前端轮询 /status/{session_id}。所有状态进 Postgres，进程无状态。
"""
from fastapi import APIRouter
router = APIRouter()
# TODO(P0): POST /resume  POST /match  GET /status/{sid}  POST /feedback
