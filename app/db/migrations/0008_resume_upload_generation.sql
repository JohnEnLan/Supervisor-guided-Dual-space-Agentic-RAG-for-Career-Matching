-- W-B Feature A: invalidate stale resume-normalization work as soon as an
-- upload is accepted, before the background task can advance resume_version.
ALTER TABLE session_state
    ADD COLUMN IF NOT EXISTS resume_upload_generation BIGINT NOT NULL DEFAULT 0;
