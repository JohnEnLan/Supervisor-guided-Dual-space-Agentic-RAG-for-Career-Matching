-- v3 B3: 小意解析叙事——进度事件表（追加写，与 state JSONB 零竞争）。
-- 非终态事件由解析任务经守卫 INSERT 写入（seq 1..99）；终态事件（done/error,
-- seq=100）由 save_normalized_resume/mark_resume_error 在其 CAS 事务内写入。
CREATE TABLE IF NOT EXISTS resume_intake_progress (
    session_id  TEXT NOT NULL REFERENCES session_state(session_id) ON DELETE CASCADE,
    generation  BIGINT NOT NULL,
    seq         SMALLINT NOT NULL,
    step        TEXT NOT NULL,
    text        TEXT NOT NULL,
    elapsed_ms  INT NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, generation, seq)
);
