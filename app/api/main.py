"""FastAPI 入口。startup 建连接池，shutdown 关闭。无状态服务。"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.db.pool import get_pool, close_pool
from app.api.routes import router

@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()
    yield
    await close_pool()

app = FastAPI(title="Career-RAG", lifespan=lifespan)
app.include_router(router)
