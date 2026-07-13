from pathlib import Path

from app.domain.results import EvidenceItem, ProductResult, RecommendationResult
from app.state.schema import RetrievalState, SharedState


ROOT = Path(__file__).resolve().parents[1]


def _state() -> SharedState:
    return SharedState(
        session_id="session-1",
        user_id="private-user",
        retrieval_state=RetrievalState(
            ranking_scores=[
                {
                    "job_id": "job-a",
                    "explicit_rank": 2,
                    "implicit_evidence": [
                        {
                            "case_id": "case-1",
                            "highest_stage": "interview",
                            "private_resume": "must not escape",
                        }
                    ],
                },
                {
                    "job_id": "job-b",
                    "explicit_rank": 1,
                    "implicit_evidence": [],
                },
            ]
        ),
        supervisor_log=[
            {
                "stage": "public_stage_duration",
                "stage_name": "retrieval",
                "duration_ms": 120,
                "prompt": "must not escape",
            },
            {
                "stage": "public_stage_duration",
                "stage_name": "strategy",
                "duration_ms": 80,
            },
        ],
    )


def _result() -> ProductResult:
    return ProductResult(
        summary="Two recommendations",
        recommended_roles=[
            RecommendationResult(
                job_id="job-a",
                tier="now_fit",
                concise_explanation="Grounded",
                evidence=[
                    EvidenceItem(
                        evidence_span_id="JD-1",
                        content="Python required",
                    )
                ],
            ),
            RecommendationResult(
                job_id="job-b",
                tier="stretch_fit",
                concise_explanation="Grounded",
            ),
        ],
    )


def test_build_run_metrics_contains_only_allow_list_counts() -> None:
    from app.domain.monitoring import build_run_metrics

    metrics = build_run_metrics(_state(), _result())

    assert metrics.recommendation_count == 2
    assert metrics.recommendations_with_jd_evidence == 1
    assert metrics.implicit_case_count == 1
    assert metrics.reordered_job_count == 2
    assert metrics.stage_durations_ms == {"retrieval": 120, "strategy": 80}
    serialized = metrics.model_dump_json()
    for private_value in (
        "private-user",
        "private_resume",
        "must not escape",
        "prompt",
        "Python required",
    ):
        assert private_value not in serialized


def test_monitoring_migration_is_additive_and_has_no_identity_columns() -> None:
    migration = (
        ROOT / "app/db/migrations/0003_run_monitoring_read_model.sql"
    ).read_text(encoding="utf-8")
    schema = (ROOT / "app/db/schema.sql").read_text(encoding="utf-8")

    for sql in (migration, schema):
        section = sql[sql.index("CREATE TABLE IF NOT EXISTS run_metrics") :]
        assert "recommendation_count" in section
        assert "stage_durations_ms" in section
        assert "user_id" not in section.split(");", 1)[0]
        assert "resume" not in section.split(");", 1)[0].casefold()
