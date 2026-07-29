"""服务启动入口：先设事件循环策略，再启动 uvicorn。

Windows 下必须用 SelectorEventLoop（psycopg 异步不支持 Proactor），
而 `python -m uvicorn` 会在导入 app 之前创建事件循环，策略来不及生效；
因此本项目统一用 `python -m app.serve` 启动。
"""
from __future__ import annotations

import argparse
import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Career-RAG API server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    if args.reload or sys.platform != "win32":
        # reload 模式下 uvicorn 子进程走 use_subprocess=True，本身就是 SelectorEventLoop。
        uvicorn.run(
            "app.api.main:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
        )
        return

    # Windows 非 reload：uvicorn 0.49 的 asyncio_loop_factory 硬编码 ProactorEventLoop，
    # psycopg 异步池无法运行；改为手动驱动 Server 并显式指定 SelectorEventLoop。
    config = uvicorn.Config("app.api.main:app", host=args.host, port=args.port)
    server = uvicorn.Server(config)
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        runner.run(server.serve())


if __name__ == "__main__":
    main()
