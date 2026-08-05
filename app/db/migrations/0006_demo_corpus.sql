-- W5 synthetic CN/UK demo-corpus provenance and resumable import windows.
ALTER TABLE jobs
    ADD COLUMN IF NOT EXISTS demo_synthetic BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS country_code TEXT NULL,
    ADD COLUMN IF NOT EXISTS source_tag TEXT NULL,
    ADD COLUMN IF NOT EXISTS source_metadata JSONB NULL;

CREATE INDEX IF NOT EXISTS idx_jobs_source_tag_open
    ON jobs (source_tag, is_open);

CREATE TABLE IF NOT EXISTS job_import_windows (
    source_tag            TEXT NOT NULL,
    window_number         INTEGER NOT NULL CHECK (window_number >= 0),
    row_start             INTEGER NOT NULL CHECK (row_start >= 0),
    row_end               INTEGER NOT NULL CHECK (row_end >= row_start),
    status                TEXT NOT NULL DEFAULT 'pending'
                               CHECK (status IN ('pending', 'running', 'succeeded', 'failed')),
    embedding_fingerprint JSONB NOT NULL,
    job_count             INTEGER NOT NULL DEFAULT 0 CHECK (job_count >= 0),
    chunk_count           INTEGER NOT NULL DEFAULT 0 CHECK (chunk_count >= 0),
    attempts              INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    error_detail          TEXT,
    started_at            TIMESTAMPTZ,
    completed_at          TIMESTAMPTZ,
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source_tag, window_number)
);

CREATE INDEX IF NOT EXISTS idx_job_import_windows_status
    ON job_import_windows (source_tag, status, window_number);

COMMENT ON COLUMN jobs.visa_sponsor IS
    'For demo_synthetic rows this is a synthetic_scenario value, not source evidence.';
