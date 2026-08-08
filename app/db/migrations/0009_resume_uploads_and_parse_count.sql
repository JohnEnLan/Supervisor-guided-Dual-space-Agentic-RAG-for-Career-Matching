-- v3 B2: 上传确认流 —— 待解析上传持久化（跨请求/刷新/多实例安全）
-- 与解析次数限额（防烧钱：额度按 parse 计，generation 回归纯 CAS token）。
CREATE TABLE IF NOT EXISTS resume_uploads (
    session_id  TEXT NOT NULL REFERENCES session_state(session_id) ON DELETE CASCADE,
    generation  BIGINT NOT NULL,
    filename    TEXT NOT NULL,
    suffix      TEXT NOT NULL,
    content     BYTEA,
    extracted_text TEXT,
    pages       INT NOT NULL DEFAULT 0 CHECK (pages >= 0),
    chars       INT NOT NULL DEFAULT 0 CHECK (chars >= 0),
    ocr_suggested BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, generation)
);

ALTER TABLE session_state
    ADD COLUMN IF NOT EXISTS resume_parse_count INT NOT NULL DEFAULT 0
        CHECK (resume_parse_count >= 0);
