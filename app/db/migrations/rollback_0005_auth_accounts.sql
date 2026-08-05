-- Manual W3 rollback. Run only after backing up account/profile data.
DROP INDEX IF EXISTS idx_session_owner_updated;
ALTER TABLE session_state DROP COLUMN IF EXISTS owner_user_id;
DROP TABLE IF EXISTS user_profiles;
DROP TABLE IF EXISTS otp_verify_attempts;
DROP TABLE IF EXISTS otp_challenges;
DROP TABLE IF EXISTS user_identities;
DROP TABLE IF EXISTS users;
DELETE FROM schema_migrations
WHERE name = '0005_auth_accounts.sql';
