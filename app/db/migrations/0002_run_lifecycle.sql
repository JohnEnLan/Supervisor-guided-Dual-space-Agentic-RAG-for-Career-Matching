-- Additive run lifecycle schema. SharedState remains in session_state.
ALTER TABLE session_state
    ADD COLUMN IF NOT EXISTS version BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS resume_version INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS confirmed_resume_version INTEGER,
    ADD COLUMN IF NOT EXISTS resume_content_hash TEXT,
    ADD COLUMN IF NOT EXISTS resume_confirmed_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS match_runs (
    run_id                   TEXT PRIMARY KEY,
    session_id               TEXT NOT NULL REFERENCES session_state(session_id),
    confirmed_resume_version INTEGER NOT NULL,
    status                   TEXT NOT NULL DEFAULT 'draft',
    stage                    TEXT,
    plan_version             INTEGER NOT NULL DEFAULT 0,
    approved_plan            JSONB NOT NULL DEFAULT '{}'::jsonb,
    plan_hash                TEXT,
    state_snapshot           JSONB,
    result_snapshot          JSONB,
    warning_codes            TEXT[] NOT NULL DEFAULT '{}',
    error_code               TEXT,
    execution_durability     TEXT NOT NULL DEFAULT 'process_local',
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at               TIMESTAMPTZ,
    finished_at              TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_match_runs_session_created
    ON match_runs (session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_match_runs_status_updated
    ON match_runs (status, updated_at);

CREATE TABLE IF NOT EXISTS run_events (
    event_id       BIGSERIAL PRIMARY KEY,
    run_id         TEXT NOT NULL REFERENCES match_runs(run_id) ON DELETE CASCADE,
    event_type     TEXT NOT NULL,
    stage          TEXT,
    status         TEXT,
    public_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_run_events_run_event
    ON run_events (run_id, event_id);
