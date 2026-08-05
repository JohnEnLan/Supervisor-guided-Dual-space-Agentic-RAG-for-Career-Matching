-- W3 account identities, OTP lifecycle, long-term profile, and session owner.
CREATE TABLE IF NOT EXISTS users (
    user_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    display_name  TEXT,
    avatar_url    TEXT,
    status        TEXT NOT NULL DEFAULT 'active'
                      CHECK (status IN ('active', 'banned', 'deleted')),
    token_version INTEGER NOT NULL DEFAULT 0,
    is_admin      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS user_identities (
    identity_id  BIGSERIAL PRIMARY KEY,
    user_id      UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    provider     TEXT NOT NULL CHECK (provider IN ('email', 'phone')),
    provider_uid TEXT NOT NULL,
    raw_profile  JSONB,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ,
    UNIQUE (provider, provider_uid)
);

CREATE INDEX IF NOT EXISTS idx_user_identities_user
    ON user_identities (user_id);

CREATE TABLE IF NOT EXISTS otp_challenges (
    id                BIGSERIAL PRIMARY KEY,
    channel           TEXT NOT NULL CHECK (channel IN ('email', 'phone')),
    normalized_target TEXT NOT NULL,
    purpose           TEXT NOT NULL DEFAULT 'login'
                              CHECK (purpose IN ('login', 'bind')),
    code_hash         TEXT NOT NULL,
    attempts          INTEGER NOT NULL DEFAULT 0
                              CHECK (attempts >= 0 AND attempts <= 5),
    expires_at        TIMESTAMPTZ NOT NULL,
    consumed_at       TIMESTAMPTZ,
    client_ip         INET,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_otp_challenge_target_created
    ON otp_challenges (channel, normalized_target, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_otp_challenge_ip_created
    ON otp_challenges (client_ip, created_at DESC);

CREATE TABLE IF NOT EXISTS otp_verify_attempts (
    channel           TEXT NOT NULL CHECK (channel IN ('email', 'phone')),
    normalized_target TEXT NOT NULL,
    bucket_start      TIMESTAMPTZ NOT NULL,
    attempts          INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    PRIMARY KEY (channel, normalized_target, bucket_start)
);

CREATE TABLE IF NOT EXISTS user_profiles (
    user_id    UUID PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    profile    JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE session_state
    ADD COLUMN IF NOT EXISTS owner_user_id UUID REFERENCES users(user_id);

CREATE INDEX IF NOT EXISTS idx_session_owner_updated
    ON session_state (owner_user_id, updated_at DESC, session_id DESC);
