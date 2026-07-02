import os

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")
os.environ.setdefault("QWEN_API_KEY", "sk-test")

from app.retrieval.raptor import (
    build_job_summary_node,
    build_role_summary_node,
    expand_raptor_hits,
)


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


def test_expand_raptor_hits_maps_role_nodes_back_to_allowed_jobs():
    hits = expand_raptor_hits(
        rows=[
            {
                "node_id": "role:software_engineering",
                "node_type": "role_summary",
                "job_id": None,
                "source_job_ids": ["job-1", "job-2", "job-3"],
                "score": 0.83,
            },
            {
                "node_id": "job:job-3",
                "node_type": "job_summary",
                "job_id": "job-3",
                "source_job_ids": ["job-3"],
                "score": 0.91,
            },
        ],
        allow_ids=["job-2", "job-3"],
        max_jobs_per_role=2,
    )

    assert [(hit.job_id, hit.node_id, hit.score) for hit in hits] == [
        ("job-3", "job:job-3", 0.91),
        ("job-2", "role:software_engineering", 0.83),
    ]
