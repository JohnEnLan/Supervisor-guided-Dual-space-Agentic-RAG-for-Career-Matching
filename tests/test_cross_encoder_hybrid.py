from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace

import pytest

from app.retrieval import hybrid_search as hs


def _candidate(job_id: str, score: float) -> hs.JobCandidate:
    return hs.JobCandidate(
        job_id=job_id,
        score=score,
        explicit_score=score,
        evidence_span_ids=[f"{job_id}:required_skills:1"],
        title=f"Role {job_id}",
    )


def _install_pipeline(monkeypatch, *, count: int) -> dict[str, list]:
    job_ids = [f"job-{index:03d}" for index in range(count)]
    calls: dict[str, list] = {
        "hard_constraints": [],
        "bm25_k": [],
        "dense_k": [],
        "raptor_k": [],
        "metadata_ids": [],
        "document_ids": [],
        "rerank_documents": [],
    }

    async def get_pool():
        return object()

    async def hard_filter(_pool, constraints):
        calls["hard_constraints"].append(constraints)
        return job_ids

    async def bm25(_pool, _query, _allow_ids, k):
        calls["bm25_k"].append(k)
        return [
            hs.ChunkHit(
                job_id=job_id,
                chunk_id=f"{job_id}:required_skills:1",
                score=float(count - index),
                field="required_skills",
            )
            for index, job_id in enumerate(job_ids)
        ]

    async def dense(_pool, _query, _allow_ids, k):
        calls["dense_k"].append(k)
        return [
            hs.ChunkHit(
                job_id=job_id,
                chunk_id=f"{job_id}:required_skills:1",
                score=float(count - index),
                field="required_skills",
            )
            for index, job_id in enumerate(job_ids)
        ]

    async def raptor(_pool, *, query, allow_ids, top_k):
        del query, allow_ids
        calls["raptor_k"].append(top_k)
        return []

    async def metadata(_pool, candidate_ids):
        calls["metadata_ids"].append(list(candidate_ids))
        return {
            job_id: {
                "title": f"Role {job_id}",
                "company": "Example",
                "location": "London",
                "role_cluster": "data",
            }
            for job_id in candidate_ids
        }

    async def evidence(_pool, evidence_by_job):
        return {job_id: [] for job_id in evidence_by_job}

    async def documents(_pool, candidate_ids):
        calls["document_ids"].append(list(candidate_ids))
        return {
            job_id: f"Title: Role {job_id}\nRequired skills: SQL"
            for job_id in candidate_ids
        }

    async def forbidden_rerank(query, documents):
        calls["rerank_documents"].append((query, list(documents)))
        raise AssertionError("reranker must not be called")

    monkeypatch.setattr(hs, "get_pool", get_pool)
    monkeypatch.setattr(hs, "_hard_filter_ids", hard_filter)
    monkeypatch.setattr(hs, "_bm25", bm25)
    monkeypatch.setattr(hs, "_dense", dense)
    monkeypatch.setattr(hs, "search_raptor_nodes", raptor)
    monkeypatch.setattr(
        hs,
        "rrf_fuse",
        lambda _rank_lists: [
            (job_id, 1.0 / (60 + index))
            for index, job_id in enumerate(job_ids)
        ],
    )
    monkeypatch.setattr(hs, "_fetch_job_metadata", metadata)
    monkeypatch.setattr(hs, "_fetch_evidence_payloads", evidence)
    monkeypatch.setattr(hs, "_fetch_rerank_documents", documents, raising=False)
    monkeypatch.setattr(hs, "rerank_documents", forbidden_rerank, raising=False)
    monkeypatch.setattr(
        hs,
        "_require_rerank_endpoint",
        lambda: "https://test",
        raising=False,
    )
    monkeypatch.setattr(hs.settings, "rerank_enabled", False)
    monkeypatch.setattr(hs.settings, "rerank_top_n", 20)
    monkeypatch.setattr(hs.settings, "rerank_query_max_chars", 600)
    monkeypatch.setattr(hs.settings, "rerank_doc_max_chars", 1500)
    return calls


@pytest.mark.asyncio
async def test_default_disabled_path_makes_zero_rerank_requests(monkeypatch) -> None:
    calls = _install_pipeline(monkeypatch, count=30)

    result = await hs.hybrid_search(query="data analyst", top_k=5)

    assert len(result) == 5
    assert calls["rerank_documents"] == []
    assert calls["bm25_k"] == [20]
    assert len(calls["metadata_ids"][0]) == 15


@pytest.mark.asyncio
async def test_disabled_pool_depth_and_recall_ignore_rerank_top_n(monkeypatch) -> None:
    calls = _install_pipeline(monkeypatch, count=40)

    first = await hs.hybrid_search(
        query="data analyst",
        top_k=5,
        use_cross_encoder=False,
        rerank_top_n=1,
    )
    second = await hs.hybrid_search(
        query="data analyst",
        top_k=5,
        use_cross_encoder=False,
        rerank_top_n=200,
    )

    assert first == second
    assert calls["bm25_k"] == [20, 20]
    assert [len(ids) for ids in calls["metadata_ids"]] == [15, 15]


@pytest.mark.asyncio
async def test_explicit_true_overrides_disabled_setting_and_uses_one_request(
    monkeypatch,
) -> None:
    calls = _install_pipeline(monkeypatch, count=12)

    async def rerank(query, documents):
        calls["rerank_documents"].append((query, list(documents)))
        return [float(index) / 10 for index in range(len(documents))]

    monkeypatch.setattr(hs, "rerank_documents", rerank)

    result = await hs.hybrid_search(
        query="data analyst",
        top_k=5,
        use_cross_encoder=True,
        rerank_top_n=8,
    )

    assert len(calls["rerank_documents"]) == 1
    assert len(calls["rerank_documents"][0][1]) == 8
    assert result[0].job_id == "job-007"
    assert result[0].cross_rank == 0


@pytest.mark.asyncio
async def test_cross_encoder_audit_records_requested_effective_and_applied(
    monkeypatch,
) -> None:
    calls = _install_pipeline(monkeypatch, count=10)
    audit = {}

    async def rerank(query, documents):
        calls["rerank_documents"].append((query, list(documents)))
        return [float(index) for index in range(len(documents))]

    monkeypatch.setattr(hs, "rerank_documents", rerank)

    await hs.hybrid_search(
        query="data analyst",
        top_k=5,
        use_cross_encoder=True,
        rerank_top_n=8,
        rerank_audit=audit,
    )

    assert audit == {
        "requested": 8,
        "effective": 8,
        "applied": True,
        "reason_code": "applied",
    }


@pytest.mark.asyncio
async def test_explicit_false_overrides_enabled_setting(monkeypatch) -> None:
    calls = _install_pipeline(monkeypatch, count=10)
    monkeypatch.setattr(hs.settings, "rerank_enabled", True)

    result = await hs.hybrid_search(
        query="data analyst",
        top_k=5,
        use_cross_encoder=False,
    )

    assert len(result) == 5
    assert calls["rerank_documents"] == []


@pytest.mark.asyncio
async def test_top_k_fifty_and_n_twenty_send_exactly_twenty_documents(
    monkeypatch,
) -> None:
    calls = _install_pipeline(monkeypatch, count=80)

    async def rerank(query, documents):
        calls["rerank_documents"].append((query, list(documents)))
        return [0.5] * len(documents)

    monkeypatch.setattr(hs, "rerank_documents", rerank)

    await hs.hybrid_search(
        query="data analyst",
        top_k=50,
        use_cross_encoder=True,
        rerank_top_n=20,
    )

    assert calls["bm25_k"] == [200]
    assert len(calls["metadata_ids"][0]) == 80
    assert len(calls["rerank_documents"][0][1]) == 20


@pytest.mark.asyncio
async def test_candidate_outside_top_k_can_enter_from_wider_cross_pool(
    monkeypatch,
) -> None:
    calls = _install_pipeline(monkeypatch, count=20)

    async def rerank(query, documents):
        calls["rerank_documents"].append((query, list(documents)))
        return [0.0] * 19 + [1.0]

    monkeypatch.setattr(hs, "rerank_documents", rerank)

    result = await hs.hybrid_search(
        query="data analyst",
        top_k=5,
        use_cross_encoder=True,
        rerank_top_n=20,
    )

    assert calls["bm25_k"] == [80]
    assert len(calls["metadata_ids"][0]) == 20
    assert result[0].job_id == "job-019"


@pytest.mark.asyncio
async def test_window_of_one_is_budget_empty_and_lazily_falls_back(
    monkeypatch,
) -> None:
    calls = _install_pipeline(monkeypatch, count=10)

    baseline = await hs.hybrid_search(
        query="data analyst",
        top_k=5,
        use_cross_encoder=False,
    )
    result = await hs.hybrid_search(
        query="data analyst",
        top_k=5,
        use_cross_encoder=True,
        rerank_top_n=1,
    )

    assert result == baseline
    assert calls["rerank_documents"] == []
    assert len(calls["hard_constraints"]) == 3


def test_applied_window_remaps_its_own_interval_at_full_precision() -> None:
    baseline = [
        _candidate("job-a", 0.91),
        _candidate("job-b", 0.72),
        _candidate("job-c", 0.55),
        _candidate("job-d", 0.23),
        _candidate("job-tail", 0.10),
    ]

    result = hs._remap_cross_scores(
        baseline,
        [0.2, 0.8, 0.6, 0.4],
    )

    assert [candidate.job_id for candidate in result] == [
        "job-b",
        "job-c",
        "job-d",
        "job-a",
        "job-tail",
    ]
    expected = [0.91 - index * (0.91 - 0.23) / 3 for index in range(4)]
    assert [candidate.score for candidate in result[:4]] == expected
    assert [candidate.explicit_score for candidate in result[:4]] == expected
    assert result[4] is baseline[4]
    assert all(
        result[index].score >= result[index + 1].score
        for index in range(len(result) - 1)
    )


def test_provider_full_tie_only_records_cross_score() -> None:
    baseline = [_candidate("job-z", 0.8), _candidate("job-a", 0.8)]

    result = hs._remap_cross_scores(baseline, [0.5, 0.5])

    assert [candidate.job_id for candidate in result] == ["job-z", "job-a"]
    assert [candidate.score for candidate in result] == [0.8, 0.8]
    assert [candidate.explicit_score for candidate in result] == [0.8, 0.8]
    assert [candidate.cross_score for candidate in result] == [0.5, 0.5]
    assert [candidate.cross_rank for candidate in result] == [None, None]
    assert [replace(candidate, cross_score=None) for candidate in result] == baseline


def test_equal_baseline_scores_use_cross_rank_without_changing_scores() -> None:
    baseline = [_candidate("job-a", 0.7), _candidate("job-z", 0.7)]

    result = hs._remap_cross_scores(baseline, [0.1, 0.9])

    assert [candidate.job_id for candidate in result] == ["job-z", "job-a"]
    assert [candidate.score for candidate in result] == [0.7, 0.7]
    assert [candidate.cross_rank for candidate in result] == [0, 1]


def test_single_candidate_keeps_score_and_has_no_cross_rank() -> None:
    baseline = [_candidate("job-a", 0.7)]

    result = hs._remap_cross_scores(baseline, [0.3])

    assert result[0].score == 0.7
    assert result[0].cross_score == 0.3
    assert result[0].cross_rank is None


def test_cross_score_zero_is_preserved() -> None:
    result = hs._remap_cross_scores(
        [_candidate("job-a", 0.8), _candidate("job-b", 0.7)],
        [0.0, 0.2],
    )

    assert result[1].job_id == "job-a"
    assert result[1].cross_score == 0.0


def test_prepare_rerank_inputs_applies_char_and_token_limits_without_dropping() -> None:
    query, documents, effective = hs._prepare_rerank_inputs(
        "中" * 3900,
        ["文" * 3900, "a" * 5000],
        query_max_chars=4000,
        document_max_chars=4000,
    )

    assert hs.est_tokens(query) == 3800
    assert [hs.est_tokens(document) for document in documents] == [3800, 1334]
    assert effective == 2


def test_prepare_rerank_inputs_uses_largest_total_budget_prefix() -> None:
    query, documents, effective = hs._prepare_rerank_inputs(
        "中" * 100,
        ["文" * 3800 for _ in range(8)],
        query_max_chars=4000,
        document_max_chars=4000,
    )

    assert len(query) == 100
    assert effective == 6
    assert len(documents) == 6
    assert hs.est_tokens(query) * effective + sum(
        hs.est_tokens(document) for document in documents
    ) <= 27_000


@pytest.mark.asyncio
async def test_effective_window_can_be_smaller_than_requested_and_tail_is_untouched(
    monkeypatch,
) -> None:
    calls = _install_pipeline(monkeypatch, count=8)
    monkeypatch.setattr(hs.settings, "rerank_query_max_chars", 4000)
    monkeypatch.setattr(hs.settings, "rerank_doc_max_chars", 4000)

    async def long_documents(_pool, candidate_ids):
        calls["document_ids"].append(list(candidate_ids))
        return {job_id: "文" * 3800 for job_id in candidate_ids}

    async def rerank(query, documents):
        calls["rerank_documents"].append((query, list(documents)))
        return [float(index) for index in range(len(documents))]

    monkeypatch.setattr(hs, "_fetch_rerank_documents", long_documents)
    monkeypatch.setattr(hs, "rerank_documents", rerank)

    result = await hs.hybrid_search(
        query="中" * 100,
        top_k=8,
        use_cross_encoder=True,
        rerank_top_n=8,
    )

    assert len(calls["document_ids"][0]) == 8
    assert len(calls["rerank_documents"][0][1]) == 6
    by_id = {candidate.job_id: candidate for candidate in result}
    assert by_id["job-006"].cross_score is None
    assert by_id["job-007"].cross_score is None
    assert by_id["job-006"].score == by_id["job-006"].explicit_score
    assert all(
        result[index].score >= result[index + 1].score
        for index in range(len(result) - 1)
    )


class _Acquire:
    def __init__(self, connection) -> None:
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *_args):
        return None


class _Pool:
    def __init__(self, connection) -> None:
        self.connection = connection

    def acquire(self):
        return _Acquire(self.connection)


@pytest.mark.asyncio
async def test_rerank_document_query_coalesces_partial_null_fields() -> None:
    class Connection:
        async def fetch(self, sql, job_ids):
            assert "COALESCE(title" in sql
            compact_sql = " ".join(sql.split())
            assert (
                "array_to_string(COALESCE(required_skills, ARRAY[]::TEXT[]), ', ')"
                in compact_sql
            )
            assert "COALESCE(raw_jd" in sql
            assert job_ids == ["job-a"]
            return [
                {
                    "job_id": "job-a",
                    "title": "Data Analyst",
                    "required_skills": None,
                    "raw_jd": "Build dashboards",
                }
            ]

    documents = await hs._fetch_rerank_documents(
        _Pool(Connection()),
        ["job-a"],
    )

    assert "Data Analyst" in documents["job-a"]
    assert "Build dashboards" in documents["job-a"]


@pytest.mark.parametrize("rows", [[], [{"job_id": "job-a", "title": "", "required_skills": "", "raw_jd": ""}]])
@pytest.mark.asyncio
async def test_missing_or_empty_rerank_document_is_unavailable(rows) -> None:
    class Connection:
        async def fetch(self, _sql, _job_ids):
            return rows

    with pytest.raises(hs.RerankUnavailable):
        await hs._fetch_rerank_documents(_Pool(Connection()), ["job-a"])


@pytest.mark.parametrize("failure_kind", ["api", "sql", "empty"])
@pytest.mark.asyncio
async def test_degradable_failure_lazily_replays_complete_disabled_path(
    monkeypatch,
    failure_kind,
) -> None:
    calls = _install_pipeline(monkeypatch, count=12)
    constraints = {"locations": ["London"]}
    soft_prefs = {"preferred_locations": ["London"]}

    baseline = await hs.hybrid_search(
        query="data analyst",
        hard_constraints=constraints,
        soft_prefs=soft_prefs,
        top_k=4,
        include_raptor=True,
        use_cross_encoder=False,
    )

    if failure_kind == "api":
        async def fail_rerank(_query, _documents):
            calls["rerank_documents"].append("failed")
            raise hs.RerankUnavailable("provider down")

        monkeypatch.setattr(hs, "rerank_documents", fail_rerank)
    elif failure_kind == "sql":
        async def fail_documents(_pool, _candidate_ids):
            raise RuntimeError("document SQL failed")

        monkeypatch.setattr(hs, "_fetch_rerank_documents", fail_documents)
    else:
        async def empty_documents(_pool, candidate_ids):
            return {job_id: "" for job_id in candidate_ids}

        monkeypatch.setattr(hs, "_fetch_rerank_documents", empty_documents)

    result = await hs.hybrid_search(
        query="data analyst",
        hard_constraints=constraints,
        soft_prefs=soft_prefs,
        top_k=4,
        include_raptor=True,
        use_cross_encoder=True,
        rerank_top_n=8,
    )

    assert result == baseline
    assert calls["hard_constraints"] == [constraints, constraints, constraints]
    assert len(calls["raptor_k"]) == 3
    assert len(calls["metadata_ids"]) == 3
    assert len(calls["rerank_documents"]) <= 1


@pytest.mark.asyncio
async def test_fallback_failure_propagates_without_second_catch(monkeypatch) -> None:
    _install_pipeline(monkeypatch, count=10)
    bm25_calls = 0

    async def bm25(_pool, _query, _allow_ids, k):
        nonlocal bm25_calls
        del k
        bm25_calls += 1
        if bm25_calls == 2:
            raise RuntimeError("fallback DB failure")
        return [
            hs.ChunkHit(job_id="job-000", chunk_id="chunk", score=1.0)
        ]

    async def fail_rerank(_query, _documents):
        raise hs.RerankUnavailable("provider down")

    monkeypatch.setattr(hs, "_bm25", bm25)
    monkeypatch.setattr(hs, "rerank_documents", fail_rerank)

    with pytest.raises(RuntimeError, match="fallback DB failure"):
        await hs.hybrid_search(
            query="data analyst",
            top_k=3,
            use_cross_encoder=True,
            rerank_top_n=5,
        )

    assert bm25_calls == 2


@pytest.mark.asyncio
async def test_misconfigured_and_cancelled_failures_never_degrade(
    monkeypatch,
) -> None:
    calls = _install_pipeline(monkeypatch, count=10)

    async def misconfigured(_query, _documents):
        raise hs.RerankMisconfigured("unauthorized")

    monkeypatch.setattr(hs, "rerank_documents", misconfigured)
    with pytest.raises(hs.RerankMisconfigured):
        await hs.hybrid_search(
            query="data analyst",
            top_k=3,
            use_cross_encoder=True,
            rerank_top_n=5,
        )
    assert len(calls["hard_constraints"]) == 1

    async def cancelled(_query, _documents):
        raise asyncio.CancelledError

    monkeypatch.setattr(hs, "rerank_documents", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await hs.hybrid_search(
            query="data analyst",
            top_k=3,
            use_cross_encoder=True,
            rerank_top_n=5,
        )
    assert len(calls["hard_constraints"]) == 2


@pytest.mark.asyncio
async def test_explicit_true_validates_endpoint_before_database(monkeypatch) -> None:
    async def forbidden_pool():
        raise AssertionError("invalid endpoint must fail before DB")

    def invalid_endpoint():
        raise hs.RerankMisconfigured("invalid endpoint")

    monkeypatch.setattr(hs, "get_pool", forbidden_pool)
    monkeypatch.setattr(
        hs,
        "_require_rerank_endpoint",
        invalid_endpoint,
        raising=False,
    )

    with pytest.raises(hs.RerankMisconfigured):
        await hs.hybrid_search(
            query="data analyst",
            use_cross_encoder=True,
        )


@pytest.mark.asyncio
async def test_cli_forwards_explicit_cross_encoder_flag(monkeypatch) -> None:
    received = {}

    async def search(**kwargs):
        received.update(kwargs)
        return []

    async def close():
        return None

    monkeypatch.setattr(hs, "hybrid_search", search)
    monkeypatch.setattr(hs, "close_pool", close)
    args = argparse.Namespace(
        query="data analyst",
        session_id=None,
        hard_constraints=None,
        soft_prefs=None,
        top_k=5,
        include_raptor=False,
        use_cross_encoder=True,
    )

    await hs._main_async(args)

    assert received["use_cross_encoder"] is True
