-- 建库后执行：psql $DATABASE_URL -f app/db/schema.sql
-- 注意：vector(1024) 的维度必须等于 .env 的 EMBED_DIM 与 Qwen embedding 实际维度。

CREATE EXTENSION IF NOT EXISTS vector;

-- ========== Explicit Job Space：显性岗位空间 ==========
CREATE TABLE IF NOT EXISTS jobs (
    job_id          TEXT PRIMARY KEY,
    title           TEXT,
    company         TEXT,
    location        TEXT,
    visa_sponsor    BOOLEAN,
    degree_required TEXT,
    min_years_exp   INT,
    role_cluster    TEXT,            -- 用于 role routing（如 ai_product / data / llm_app）
    is_open         BOOLEAN DEFAULT TRUE,
    deadline        DATE,
    responsibilities TEXT,
    required_skills  TEXT[],
    nice_to_have     TEXT[],
    raw_jd          TEXT
);

-- JD 分块 + 向量（field-aware / schema-based chunking 后的结果）
CREATE TABLE IF NOT EXISTS job_chunks (
    chunk_id    TEXT PRIMARY KEY,
    job_id      TEXT REFERENCES jobs(job_id),
    field       TEXT,                -- 该 chunk 来自哪个字段（responsibilities / skills ...）
    content     TEXT,
    embedding   vector(1024),
    tsv         tsvector             -- BM25/全文检索用
);

-- HNSW 向量索引（语义检索）
CREATE INDEX IF NOT EXISTS idx_job_chunks_hnsw
    ON job_chunks USING hnsw (embedding vector_cosine_ops);

-- 全文检索索引（BM25 近似，MVP 用 Postgres ts_rank 即可）
CREATE INDEX IF NOT EXISTS idx_job_chunks_tsv
    ON job_chunks USING gin (tsv);

-- 硬过滤常用字段建普通索引，加速 metadata filter
CREATE INDEX IF NOT EXISTS idx_jobs_filter
    ON jobs (location, visa_sponsor, role_cluster, is_open);

-- ========== Shared Structured State：按 session_id 隔离（无状态服务的关键） ==========
CREATE TABLE IF NOT EXISTS session_state (
    session_id  TEXT PRIMARY KEY,
    user_id     TEXT,
    state       JSONB NOT NULL,      -- 整个 SharedState 序列化存这里
    status      TEXT DEFAULT 'pending',  -- pending / running / done / error（前端轮询用）
    updated_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_session_user ON session_state (user_id);

-- ========== Latent Career Space：隐性职业空间 ==========
-- 5.2.1 用户私有记忆（不进公共库）
CREATE TABLE IF NOT EXISTS private_memory (
    user_id     TEXT,
    resume_version_id TEXT,
    payload     JSONB,               -- 原始/normalized/tailored 简历、偏好、历史
    updated_at  TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (user_id, resume_version_id)
);

-- 5.2.2 投递反馈记忆
CREATE TABLE IF NOT EXISTS feedback_memory (
    feedback_id SERIAL PRIMARY KEY,
    user_id     TEXT,
    job_id      TEXT,
    outcome     TEXT,                -- passed_screen / oa / interview_1 / offer / rejected ...
    reason      TEXT,
    user_rating INT,
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- 5.2.3 匿名职业案例库（已去标识化，可反哺）
CREATE TABLE IF NOT EXISTS career_cases (
    case_id     TEXT PRIMARY KEY,
    background_type TEXT,
    target_role TEXT,
    successful_resume_features TEXT[],
    missing_skills_before TEXT[],
    application_outcome TEXT,
    recommended_bridge_roles TEXT[],
    embedding   vector(1024)         -- 便于按背景相似度检索案例
);
CREATE INDEX IF NOT EXISTS idx_cases_hnsw
    ON career_cases USING hnsw (embedding vector_cosine_ops);
