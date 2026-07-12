from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from app.db.pool import get_pool


MIGRATIONS_DIR = Path(__file__).with_name("migrations")


def discover_migrations(migrations_dir: Path = MIGRATIONS_DIR) -> list[Path]:
    return sorted(migrations_dir.glob("[0-9][0-9][0-9][0-9]_*.sql"))


async def apply_migrations(
    *, pool: Any | None = None, migrations_dir: Path = MIGRATIONS_DIR
) -> list[str]:
    database_pool = pool or await get_pool()
    applied_now: list[str] = []

    async with database_pool.acquire() as connection:
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                name TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        rows = await connection.fetch("SELECT name FROM schema_migrations")
        applied = {str(row["name"]) for row in rows}

        for path in discover_migrations(migrations_dir):
            if path.name in applied:
                continue
            sql = path.read_text(encoding="utf-8")
            async with connection.transaction():
                await connection.execute(sql)
                await connection.execute(
                    "INSERT INTO schema_migrations (name) VALUES ($1)", path.name
                )
            applied_now.append(path.name)

    return applied_now


def main() -> None:
    asyncio.run(apply_migrations())


if __name__ == "__main__":
    main()
