"""FastAPI 入口。startup 建连接池，shutdown 关闭。无状态服务。"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg_pool import AsyncConnectionPool

from app.api.routes import router
from app.api.v1.router import router as v1_router
from app.config import settings
from app.db.pool import close_pool, get_pool
from app.db.run_store import (
    list_terminal_checkpoint_thread_ids,
    recover_stale_runs,
)
from app.domain.match_brief import MatchBrief
from app.domain.results import ProductResult
from app.state.schema import SharedState


@asynccontextmanager
async def lifespan(app: FastAPI):
    checkpoint_pool = None
    checkpointer = None
    await get_pool()
    try:
        if settings.langgraph_orchestrator_enabled:
            checkpoint_pool = AsyncConnectionPool(
                conninfo=settings.database_url,
                min_size=1,
                max_size=4,
                kwargs={"autocommit": True, "prepare_threshold": 0},
                open=False,
            )
            await checkpoint_pool.open()
            await checkpoint_pool.wait(timeout=5)
            checkpointer = AsyncPostgresSaver(
                checkpoint_pool,
                serde=JsonPlusSerializer(
                    allowed_msgpack_modules=[
                        SharedState,
                        MatchBrief,
                        ProductResult,
                    ],
                ),
            )
            await checkpointer.setup()
            app.state.langgraph_checkpointer = checkpointer
        await recover_stale_runs(
            stale_after_seconds=settings.run_stale_after_seconds,
        )
        if checkpointer is not None:
            terminal_thread_ids = (
                await list_terminal_checkpoint_thread_ids()
            )
            for thread_id in terminal_thread_ids:
                await checkpointer.adelete_thread(thread_id)
        yield
    finally:
        try:
            if hasattr(app.state, "langgraph_checkpointer"):
                del app.state.langgraph_checkpointer
            if checkpoint_pool is not None:
                await checkpoint_pool.close()
        finally:
            await close_pool()


app = FastAPI(title="Career-RAG", lifespan=lifespan)
app.include_router(router)
app.include_router(v1_router)
