-- Manual W5 rollback. Back up import-window audit rows before running.
DROP INDEX IF EXISTS idx_job_import_windows_status;
DROP TABLE IF EXISTS job_import_windows;
DROP INDEX IF EXISTS idx_jobs_source_tag_open;
ALTER TABLE jobs
    DROP COLUMN IF EXISTS source_metadata,
    DROP COLUMN IF EXISTS source_tag,
    DROP COLUMN IF EXISTS country_code,
    DROP COLUMN IF EXISTS demo_synthetic;
DELETE FROM schema_migrations
WHERE name = '0006_demo_corpus.sql';
