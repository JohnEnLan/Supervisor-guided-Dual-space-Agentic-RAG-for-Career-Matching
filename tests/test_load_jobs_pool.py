import os
from datetime import date

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")
os.environ.setdefault("QWEN_API_KEY", "sk-test")


class FakeAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeTransaction:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePool:
    def __init__(self, conn):
        self.conn = conn
        self.acquire_calls = 0

    def acquire(self):
        self.acquire_calls += 1
        return FakeAcquire(self.conn)


class FakeConn:
    def __init__(self, fetch_rows=None):
        self.fetch_rows = fetch_rows or []
        self.executemany_calls = []
        self.execute_calls = []
        self.transaction_calls = 0

    async def executemany(self, sql, records):
        self.executemany_calls.append((sql, records))

    async def execute(self, sql, *args):
        self.execute_calls.append((sql, args))

    async def fetch(self, sql, *args):
        return self.fetch_rows

    def transaction(self):
        self.transaction_calls += 1
        return FakeTransaction()


def _fail_direct_connect(*args, **kwargs):
    raise AssertionError("scripts.load_jobs must use get_pool(), not asyncpg.connect()")


@pytest.mark.asyncio
async def test_upsert_jobs_uses_shared_pool(monkeypatch):
    from scripts import load_jobs

    conn = FakeConn()
    pool = FakePool(conn)

    async def fake_get_pool():
        return pool

    monkeypatch.setattr(load_jobs, "get_pool", fake_get_pool, raising=False)
    monkeypatch.setattr(load_jobs.asyncpg, "connect", _fail_direct_connect)

    await load_jobs._upsert_jobs(
        [
            load_jobs.ParsedJob(
                job_id="job-1",
                title="Data Analyst",
                company="Example",
                location="Birmingham",
                visa_sponsor=True,
                degree_required="bachelor",
                min_years_exp=1,
                role_cluster="data_ai",
                is_open=True,
                deadline=date(2026, 1, 1),
                responsibilities="Build dashboards.",
                required_skills=["Python", "SQL"],
                nice_to_have=["Tableau"],
                raw_jd="Full JD text",
            )
        ]
    )

    assert pool.acquire_calls == 1
    assert len(conn.executemany_calls) == 1
    assert conn.executemany_calls[0][1][0][0] == "job-1"


@pytest.mark.asyncio
async def test_chunk_fetch_and_write_use_shared_pool(monkeypatch):
    from scripts import load_jobs

    rows = [
        {
            "job_id": "job-1",
            "title": "Data Analyst",
            "company": "Example",
            "location": "Birmingham",
            "degree_required": "bachelor",
            "min_years_exp": 1,
            "role_cluster": "data_ai",
            "responsibilities": "Build dashboards.",
            "required_skills": ["Python", "SQL"],
            "nice_to_have": ["Tableau"],
            "raw_jd": "Analyse data and prepare reports.",
        }
    ]
    conn = FakeConn(fetch_rows=rows)
    pool = FakePool(conn)

    async def fake_get_pool():
        return pool

    async def fake_embed_specs(specs, batch_size):
        return [[0.1] * load_jobs.settings.embed_dim for _ in specs]

    monkeypatch.setattr(load_jobs, "get_pool", fake_get_pool, raising=False)
    monkeypatch.setattr(load_jobs.asyncpg, "connect", _fail_direct_connect)
    monkeypatch.setattr(load_jobs, "_embed_specs", fake_embed_specs)

    fetched = await load_jobs._fetch_jobs_for_chunking(limit=1)
    count = await load_jobs.build_job_chunks(limit=1, batch_size=10)

    assert fetched == rows
    assert pool.acquire_calls == 3
    assert conn.transaction_calls == 1
    assert any("DELETE FROM job_chunks" in sql for sql, _args in conn.execute_calls)
    assert count >= 1
