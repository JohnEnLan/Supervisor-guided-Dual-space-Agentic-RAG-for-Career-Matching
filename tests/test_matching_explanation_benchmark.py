import os

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")
os.environ.setdefault("QWEN_API_KEY", "sk-test")


@pytest.mark.asyncio
async def test_benchmark_reports_serial_vs_parallel_latency_table():
    from scripts.benchmark_matching_explanations import (
        format_benchmark_markdown,
        run_benchmark,
    )

    rows = await run_benchmark(
        candidates=5,
        simulated_latency_ms=30,
        semaphore_limit=5,
    )
    markdown = format_benchmark_markdown(rows)

    serial = next(row for row in rows if row["mode"] == "serial")
    parallel = next(row for row in rows if row["mode"] == "parallel")

    assert serial["elapsed_ms"] > parallel["elapsed_ms"] * 2
    assert serial["max_active_calls"] == 1
    assert parallel["max_active_calls"] == 5
    assert "| mode | candidates | semaphore_limit | elapsed_ms | max_active_calls |" in markdown
