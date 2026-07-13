-- Privacy-safe aggregate metrics for read-only monitoring.
CREATE TABLE IF NOT EXISTS run_metrics (
    run_id                            TEXT PRIMARY KEY
                                      REFERENCES match_runs(run_id)
                                      ON DELETE CASCADE,
    recommendation_count              INTEGER NOT NULL DEFAULT 0,
    recommendations_with_jd_evidence  INTEGER NOT NULL DEFAULT 0,
    implicit_case_count                INTEGER NOT NULL DEFAULT 0,
    reordered_job_count                INTEGER NOT NULL DEFAULT 0,
    stage_durations_ms                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_run_metrics_created
    ON run_metrics (created_at DESC);
