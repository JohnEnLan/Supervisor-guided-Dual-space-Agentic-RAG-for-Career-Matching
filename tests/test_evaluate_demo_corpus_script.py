from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest


def test_run_specs_use_two_explicit_booleans_and_flags_gate_runs() -> None:
    from scripts import evaluate_demo_corpus as evaluation

    assert evaluation.RUN_SPECS == {
        "base": {"include_raptor": False, "use_cross_encoder": False},
        "raptor": {"include_raptor": True, "use_cross_encoder": False},
        "cross": {"include_raptor": False, "use_cross_encoder": True},
        "raptor_cross": {"include_raptor": True, "use_cross_encoder": True},
    }
    assert list(
        evaluation._selected_run_specs(
            include_raptor=False,
            use_cross_encoder=False,
        )
    ) == ["base"]
    assert list(
        evaluation._selected_run_specs(
            include_raptor=True,
            use_cross_encoder=False,
        )
    ) == ["base", "raptor"]
    assert list(
        evaluation._selected_run_specs(
            include_raptor=False,
            use_cross_encoder=True,
        )
    ) == ["base", "cross"]
    assert list(
        evaluation._selected_run_specs(
            include_raptor=True,
            use_cross_encoder=True,
        )
    ) == ["base", "raptor", "cross", "raptor_cross"]


def test_cross_eval_uses_versioned_output_and_order_sensitive_pool_fingerprint() -> None:
    from scripts import evaluate_demo_corpus as evaluation

    first = {"case-b": ["job-2"], "case-a": ["job-1", "job-3"]}
    reordered_keys = {"case-a": ["job-1", "job-3"], "case-b": ["job-2"]}
    changed_order = {"case-a": ["job-3", "job-1"], "case-b": ["job-2"]}

    assert evaluation.OUTPUT_DIR.name == "demo_corpus_cross_v1"
    assert evaluation._pool_fingerprint(first) == evaluation._pool_fingerprint(
        reordered_keys
    )
    assert evaluation._pool_fingerprint(first) != evaluation._pool_fingerprint(
        changed_order
    )


@pytest.mark.asyncio
async def test_main_runs_flagged_ablations_and_writes_cross_manifest(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.retrieval.hybrid_search import JobCandidate
    from scripts import evaluate_demo_corpus as evaluation

    calls = []
    endpoint_checks = []

    def candidate(job_id: str, score: float, *, cross: bool) -> JobCandidate:
        return JobCandidate(
            job_id=job_id,
            score=score,
            explicit_score=score,
            cross_score=0.5 if cross else None,
            cross_rank=0 if cross else None,
            bm25_score=score,
            dense_score=score / 2,
            evidence_span_ids=[],
        )

    async def search(query, **kwargs):
        assert query == "data analyst"
        calls.append(dict(kwargs))
        is_cross = kwargs["use_cross_encoder"]
        if kwargs.get("rerank_audit") is not None:
            kwargs["rerank_audit"].update(
                {
                    "requested": 4,
                    "effective": 2,
                    "applied": True,
                    "reason_code": "applied",
                }
            )
        if kwargs["include_raptor"] and is_cross:
            ids = ["job-d", "job-a"]
        elif kwargs["include_raptor"]:
            ids = ["job-b", "job-c"]
        elif is_cross:
            ids = ["job-c", "job-a"]
        else:
            ids = ["job-a", "job-b"]
        return [
            candidate(job_id, 1.0 - index / 10, cross=is_cross)
            for index, job_id in enumerate(ids)
        ]

    async def get_pool():
        return object()

    async def fetch_texts(_pool, job_ids):
        return {job_id: job_id for job_id in job_ids}

    async def judge(_query, _job_text):
        return True

    async def close_pool():
        return None

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluate_demo_corpus.py",
            "--top-k",
            "2",
            "--k-values",
            "1",
            "2",
            "--limit",
            "1",
            "--include-raptor",
            "--use-cross-encoder",
            "--output-dir",
            str(tmp_path),
        ],
    )
    monkeypatch.setattr(
        evaluation,
        "load_jsonl",
        lambda _path: [{"case_id": "case-1", "query": "data analyst"}],
    )
    monkeypatch.setattr(evaluation, "hybrid_search", search)
    monkeypatch.setattr(evaluation, "get_pool", get_pool)
    monkeypatch.setattr(evaluation, "_fetch_job_texts", fetch_texts)
    monkeypatch.setattr(evaluation, "_judge", judge)
    monkeypatch.setattr(evaluation, "close_pool", close_pool)
    monkeypatch.setattr(
        evaluation,
        "_require_rerank_endpoint",
        lambda: endpoint_checks.append("checked") or "https://test",
        raising=False,
    )

    await evaluation.main()

    assert endpoint_checks == ["checked"]
    assert [
        (call["include_raptor"], call["use_cross_encoder"])
        for call in calls
    ] == [(False, False), (True, False), (False, True), (True, True)]
    assert "rerank_top_n" not in calls[0]
    assert "rerank_top_n" not in calls[1]
    assert calls[2]["rerank_top_n"] == 4
    assert calls[3]["rerank_top_n"] == 4

    rankings = json.loads((tmp_path / "rankings.json").read_text(encoding="utf-8"))
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert rankings["bm25_within_pool"]["case-1"] == ["job-a", "job-b"]
    assert rankings["dense_within_pool"]["case-1"] == ["job-a", "job-b"]
    assert set(rankings) == {
        "base",
        "raptor",
        "cross",
        "raptor_cross",
        "bm25_within_pool",
        "dense_within_pool",
    }
    assert manifest["schema_version"] == "demo_corpus_cross_v1"
    assert manifest["runs"] == [
        {"name": "base", "include_raptor": False, "use_cross_encoder": False},
        {"name": "raptor", "include_raptor": True, "use_cross_encoder": False},
        {"name": "cross", "include_raptor": False, "use_cross_encoder": True},
        {"name": "raptor_cross", "include_raptor": True, "use_cross_encoder": True},
    ]
    assert manifest["pool_job_ids"] == {
        "case-1": ["job-a", "job-b", "job-c", "job-d"]
    }
    assert manifest["pool_fingerprint_sha256"] == evaluation._pool_fingerprint(
        manifest["pool_job_ids"]
    )
    assert manifest["cross_encoder_windows"]["cross"]["case-1"] == {
        "requested": 4,
        "effective": 2,
        "applied": True,
        "reason_code": "applied",
    }
    assert manifest["cross_encoder_applied_ratio"] == {
        "cross": 1.0,
        "raptor_cross": 1.0,
    }


@pytest.mark.asyncio
async def test_cross_endpoint_preflight_happens_before_pool_open(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.llm.reranker import RerankMisconfigured
    from scripts import evaluate_demo_corpus as evaluation

    def invalid_endpoint():
        raise RerankMisconfigured("invalid endpoint")

    async def forbidden_pool():
        raise AssertionError("pool must not open before endpoint preflight")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluate_demo_corpus.py",
            "--use-cross-encoder",
            "--output-dir",
            str(tmp_path),
        ],
    )
    monkeypatch.setattr(evaluation, "_require_rerank_endpoint", invalid_endpoint, raising=False)
    monkeypatch.setattr(evaluation, "get_pool", forbidden_pool)

    with pytest.raises(RerankMisconfigured):
        await evaluation.main()


@pytest.mark.asyncio
async def test_cross_run_requires_positive_applied_ratio(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.retrieval.hybrid_search import JobCandidate
    from scripts import evaluate_demo_corpus as evaluation

    async def search(_query, **kwargs):
        return [
            JobCandidate(job_id="job-a", score=0.5, evidence_span_ids=[])
        ]

    async def get_pool():
        return object()

    async def fetch_texts(_pool, job_ids):
        return {job_id: job_id for job_id in job_ids}

    async def judge(_query, _job_text):
        return True

    async def close_pool():
        return None

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluate_demo_corpus.py",
            "--top-k",
            "2",
            "--limit",
            "1",
            "--use-cross-encoder",
            "--output-dir",
            str(tmp_path),
        ],
    )
    monkeypatch.setattr(
        evaluation,
        "load_jsonl",
        lambda _path: [{"case_id": "case-1", "query": "data analyst"}],
    )
    monkeypatch.setattr(evaluation, "hybrid_search", search)
    monkeypatch.setattr(evaluation, "get_pool", get_pool)
    monkeypatch.setattr(evaluation, "_fetch_job_texts", fetch_texts)
    monkeypatch.setattr(evaluation, "_judge", judge)
    monkeypatch.setattr(evaluation, "close_pool", close_pool)
    monkeypatch.setattr(evaluation, "_require_rerank_endpoint", lambda: "https://test", raising=False)

    with pytest.raises(RuntimeError, match="applied ratio"):
        await evaluation.main()
