CREATE TABLE IF NOT EXISTS anonymous_resume_cases (
    case_id        TEXT PRIMARY KEY,
    resume_payload JSONB NOT NULL,
    embedding_text TEXT NOT NULL,
    embedding      vector(1024),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_anonymous_resume_cases_hnsw
    ON anonymous_resume_cases USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS case_job_outcomes (
    outcome_id          TEXT PRIMARY KEY,
    case_id             TEXT NOT NULL REFERENCES anonymous_resume_cases(case_id),
    job_id              TEXT REFERENCES jobs(job_id),
    company             TEXT NOT NULL,
    role_family         TEXT NOT NULL,
    explicit_match_score DOUBLE PRECISION NOT NULL
        CHECK (explicit_match_score >= 0.0 AND explicit_match_score <= 1.0),
    highest_stage       TEXT NOT NULL,
    final_status        TEXT NOT NULL,
    source_confidence   DOUBLE PRECISION NOT NULL DEFAULT 1.0
        CHECK (source_confidence >= 0.0 AND source_confidence <= 1.0),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_case_job_outcomes_job
    ON case_job_outcomes (job_id);

CREATE INDEX IF NOT EXISTS idx_case_job_outcomes_company_role
    ON case_job_outcomes (company, role_family);
