"""FastAPI 入口。startup 建连接池，shutdown 关闭。无状态服务。"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.config import settings
from app.db.pool import get_pool, close_pool
from app.db.run_store import recover_stale_runs
from app.api.routes import router
from app.api.v1.router import router as v1_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()
    try:
        await recover_stale_runs(
            stale_after_seconds=settings.run_stale_after_seconds,
        )
        yield
    finally:
        await close_pool()

app = FastAPI(title="Career-RAG", lifespan=lifespan)
app.include_router(router)
app.include_router(v1_router)
