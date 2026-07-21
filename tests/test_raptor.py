import os
from pathlib import Path

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")
os.environ.setdefault("QWEN_API_KEY", "sk-test")

from app.retrieval.raptor import (
    build_job_summary_node,
    build_role_summary_node,
)


ROOT = Path(__file__).resolve().parents[1]


def test_build_job_summary_node_uses_job_metadata_and_field_chunks():
    node = build_job_summary_node(
        job={
            "job_id": "175485704",
            "title": "Software Engineer",
            "company": "GOYT",
            "location": "Denver, CO",
            "role_cluster": "software_engineering",
        },
        chunks=[
            {
                "chunk_id": "175485704:required_skills:1",
                "field": "required_skills",
                "content": "Required skills: Python; APIs; debugging",
            },
            {
                "chunk_id": "175485704:responsibilities:2",
                "field": "responsibilities",
                "content": "Responsibilities: build backend features",
            },
        ],
    )

    assert node.node_id == "job:175485704"
    assert node.node_type == "job_summary"
    assert node.job_id == "175485704"
    assert node.parent_id == "role:software_engineering"
    assert node.source_job_ids == ["175485704"]
    assert "Title: Software Engineer" in node.content
    assert "Required skills: Python" in node.content
    assert "Responsibilities: build backend features" in node.content


def test_build_role_summary_node_collects_source_jobs():
    job_nodes = [
        build_job_summary_node(
            job={
                "job_id": "133130219",
                "title": "Software Engineer",
                "company": "",
                "location": "Los Angeles",
                "role_cluster": "software_engineering",
            },
            chunks=[],
        ),
        build_job_summary_node(
            job={
                "job_id": "175485704",
                "title": "Software Engineer",
                "company": "GOYT",
                "location": "Denver",
                "role_cluster": "software_engineering",
            },
            chunks=[],
        ),
    ]

    node = build_role_summary_node("software_engineering", job_nodes)

    assert node.node_id == "role:software_engineering"
    assert node.node_type == "role_summary"
    assert node.job_id is None
    assert node.source_job_ids == ["133130219", "175485704"]
    assert "Role cluster: software_engineering" in node.content
    assert "Software Engineer" in node.content


def test_build_node_chunk_mappings_records_job_and_role_depths():
    from app.retrieval.raptor import build_node_chunk_mappings

    job_nodes = [
        build_job_summary_node(
            job={
                "job_id": "job-1",
                "title": "Data Analyst",
                "role_cluster": "data",
            },
            chunks=[
                {
                    "chunk_id": "job-1:required_skills:1",
                    "field": "required_skills",
                    "content": "Python and SQL",
                },
                {
                    "chunk_id": "job-1:responsibilities:1",
                    "field": "responsibilities",
                    "content": "Build dashboards",
                },
            ],
        ),
        build_job_summary_node(
            job={
                "job_id": "job-2",
                "title": "BI Analyst",
                "role_cluster": "data",
            },
            chunks=[
                {
                    "chunk_id": "job-2:required_skills:1",
                    "field": "required_skills",
                    "content": "Power BI",
                }
            ],
        ),
    ]
    role_node = build_role_summary_node("data", job_nodes)
    jobs_with_chunks = {
        "job-1": {
            "job": {"job_id": "job-1"},
            "chunks": [
                {"chunk_id": "job-1:required_skills:1"},
                {"chunk_id": "job-1:responsibilities:1"},
            ],
        },
        "job-2": {
            "job": {"job_id": "job-2"},
            "chunks": [{"chunk_id": "job-2:required_skills:1"}],
        },
    }

    mappings = build_node_chunk_mappings(
        [*job_nodes, role_node],
        jobs_with_chunks=jobs_with_chunks,
    )

    assert [
        (item.node_id, item.chunk_id, item.job_id, item.depth, item.leaf_rank)
        for item in mappings
    ] == [
        ("job:job-1", "job-1:required_skills:1", "job-1", 1, 1),
        ("job:job-1", "job-1:responsibilities:1", "job-1", 1, 2),
        ("job:job-2", "job-2:required_skills:1", "job-2", 1, 1),
        ("role:data", "job-1:required_skills:1", "job-1", 2, 1),
        ("role:data", "job-1:responsibilities:1", "job-1", 2, 2),
        ("role:data", "job-2:required_skills:1", "job-2", 2, 3),
    ]


def test_raptor_node_chunk_schema_is_additive_and_indexed():
    schema = (ROOT / "app/db/schema.sql").read_text(encoding="utf-8")
    migration_path = ROOT / "app/db/migrations/0004_raptor_node_chunks.sql"

    assert migration_path.exists()
    migration = migration_path.read_text(encoding="utf-8")
    for sql in (schema, migration):
        assert "CREATE TABLE IF NOT EXISTS raptor_node_chunks" in sql
        assert "PRIMARY KEY (node_id, chunk_id)" in sql
        assert "idx_raptor_node_chunks_job" in sql


def test_propagate_raptor_hits_decays_normalizes_and_combines_leaf_scores():
    from app.retrieval.raptor import propagate_raptor_hits

    hits = propagate_raptor_hits(
        node_rows=[
            {
                "node_id": "job:job-1",
                "node_type": "job_summary",
                "score": 0.9,
            },
            {
                "node_id": "role:data",
                "node_type": "role_summary",
                "score": 0.8,
            },
        ],
        leaf_rows=[
            {
                "node_id": "job:job-1",
                "chunk_id": "job-1:skills:1",
                "job_id": "job-1",
                "field": "required_skills",
                "depth": 1,
                "leaf_score": 0.9,
            },
            {
                "node_id": "job:job-1",
                "chunk_id": "job-1:responsibilities:1",
                "job_id": "job-1",
                "field": "responsibilities",
                "depth": 1,
                "leaf_score": 0.6,
            },
            {
                "node_id": "role:data",
                "chunk_id": "job-1:skills:1",
                "job_id": "job-1",
                "field": "required_skills",
                "depth": 2,
                "leaf_score": 0.9,
            },
            {
                "node_id": "role:data",
                "chunk_id": "job-1:responsibilities:1",
                "job_id": "job-1",
                "field": "responsibilities",
                "depth": 2,
                "leaf_score": 0.8,
            },
            {
                "node_id": "role:data",
                "chunk_id": "job-2:skills:1",
                "job_id": "job-2",
                "field": "required_skills",
                "depth": 2,
                "leaf_score": 0.7,
            },
            {
                "node_id": "role:data",
                "chunk_id": "job-3:skills:1",
                "job_id": "job-3",
                "field": "required_skills",
                "depth": 2,
                "leaf_score": 0.95,
            },
        ],
        allow_ids=["job-1", "job-2"],
        max_leaf_chunks_per_node=2,
        level_decay=0.65,
    )

    assert [
        (hit.job_id, hit.chunk_id, hit.node_id, hit.node_type, hit.field, hit.score)
        for hit in hits
    ] == [
        (
            "job-1",
            "job-1:skills:1",
            "job:job-1",
            "job_summary",
            "required_skills",
            0.639,
        ),
        (
            "job-1",
            "job-1:responsibilities:1",
            "job:job-1",
            "job_summary",
            "responsibilities",
            0.27,
        ),
        (
            "job-2",
            "job-2:skills:1",
            "role:data",
            "role_summary",
            "required_skills",
            0.182,
        ),
    ]


def test_propagate_role_node_keeps_one_top_leaf_per_job_before_limit():
    from app.retrieval.raptor import propagate_raptor_hits

    hits = propagate_raptor_hits(
        node_rows=[
            {"node_id": "role:data", "node_type": "role_summary", "score": 1.0}
        ],
        leaf_rows=[
            {
                "node_id": "role:data",
                "chunk_id": "job-1:skills:1",
                "job_id": "job-1",
                "field": "required_skills",
                "depth": 2,
                "leaf_score": 1.0,
            },
            {
                "node_id": "role:data",
                "chunk_id": "job-1:skills:2",
                "job_id": "job-1",
                "field": "required_skills",
                "depth": 2,
                "leaf_score": 0.9,
            },
            {
                "node_id": "role:data",
                "chunk_id": "job-2:skills:1",
                "job_id": "job-2",
                "field": "required_skills",
                "depth": 2,
                "leaf_score": 0.8,
            },
        ],
        allow_ids=["job-1", "job-2"],
        max_leaf_chunks_per_node=2,
        level_decay=0.5,
    )

    assert [(hit.job_id, hit.chunk_id, hit.score) for hit in hits] == [
        ("job-1", "job-1:skills:1", 0.25),
        ("job-2", "job-2:skills:1", 0.2),
    ]


@pytest.mark.asyncio
async def test_search_raptor_nodes_returns_original_leaf_chunks(monkeypatch):
    from app.retrieval import raptor

    fetch_calls: list[tuple[str, tuple[object, ...]]] = []

    class Connection:
        async def execute(self, _sql, *_args):
            return None

        async def fetch(self, sql, *args):
            fetch_calls.append((sql, args))
            if "FROM raptor_nodes" in sql:
                return [
                    {
                        "node_id": "role:data",
                        "node_type": "role_summary",
                        "job_id": None,
                        "source_job_ids": ["job-1", "job-2"],
                        "score": 0.8,
                    }
                ]
            if "FROM raptor_node_chunks" in sql:
                return [
                    {
                        "node_id": "role:data",
                        "chunk_id": "job-1:skills:1",
                        "job_id": "job-1",
                        "field": "required_skills",
                        "depth": 2,
                        "leaf_score": 0.9,
                    },
                    {
                        "node_id": "role:data",
                        "chunk_id": "job-2:skills:1",
                        "job_id": "job-2",
                        "field": "required_skills",
                        "depth": 2,
                        "leaf_score": 0.7,
                    },
                ]
            raise AssertionError(sql)

    class Acquire:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, *_args):
            return None

    class Pool:
        def acquire(self):
            return Acquire()

    async def fake_embed_one(_query):
        return [0.0] * raptor.settings.embed_dim

    monkeypatch.setattr(raptor, "embed_one", fake_embed_one)

    hits = await raptor.search_raptor_nodes(
        Pool(),
        query="python data analyst",
        allow_ids=["job-1", "job-2"],
        top_k=3,
        max_leaf_chunks_per_node=2,
    )

    assert [(hit.job_id, hit.chunk_id, hit.node_id) for hit in hits] == [
        ("job-1", "job-1:skills:1", "role:data"),
        ("job-2", "job-2:skills:1", "role:data"),
    ]
    assert len(fetch_calls) == 2
    leaf_sql, leaf_args = fetch_calls[1]
    assert "ROW_NUMBER() OVER" in leaf_sql
    assert "PARTITION BY mapping.node_id, mapping.job_id" in leaf_sql
    assert "node_leaf_rank <= $4" in leaf_sql
    assert leaf_args[3] == 2


@pytest.mark.asyncio
async def test_search_raptor_nodes_applies_top_k_after_job_aggregation(monkeypatch):
    from app.retrieval import raptor

    class Connection:
        async def execute(self, _sql, *_args):
            return None

        async def fetch(self, sql, *_args):
            if "FROM raptor_nodes" in sql:
                return [
                    {
                        "node_id": "job:job-1",
                        "node_type": "job_summary",
                        "job_id": "job-1",
                        "source_job_ids": ["job-1"],
                        "score": 1.0,
                    },
                    {
                        "node_id": "job:job-2",
                        "node_type": "job_summary",
                        "job_id": "job-2",
                        "source_job_ids": ["job-2"],
                        "score": 0.4,
                    },
                ]
            if "FROM raptor_node_chunks" in sql:
                return [
                    {
                        "node_id": "job:job-1",
                        "chunk_id": "job-1:skills:1",
                        "job_id": "job-1",
                        "field": "required_skills",
                        "depth": 1,
                        "leaf_score": 1.0,
                    },
                    {
                        "node_id": "job:job-1",
                        "chunk_id": "job-1:skills:2",
                        "job_id": "job-1",
                        "field": "required_skills",
                        "depth": 1,
                        "leaf_score": 0.9,
                    },
                    {
                        "node_id": "job:job-2",
                        "chunk_id": "job-2:skills:1",
                        "job_id": "job-2",
                        "field": "required_skills",
                        "depth": 1,
                        "leaf_score": 1.0,
                    },
                ]
            raise AssertionError(sql)

    class Acquire:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, *_args):
            return None

    class Pool:
        def acquire(self):
            return Acquire()

    async def fake_embed_one(_query):
        return [0.0] * raptor.settings.embed_dim

    monkeypatch.setattr(raptor, "embed_one", fake_embed_one)

    hits = await raptor.search_raptor_nodes(
        Pool(),
        query="python data analyst",
        allow_ids=["job-1", "job-2"],
        top_k=2,
        max_leaf_chunks_per_node=2,
    )

    assert [(hit.job_id, hit.chunk_id) for hit in hits] == [
        ("job-1", "job-1:skills:1"),
        ("job-1", "job-1:skills:2"),
        ("job-2", "job-2:skills:1"),
    ]
