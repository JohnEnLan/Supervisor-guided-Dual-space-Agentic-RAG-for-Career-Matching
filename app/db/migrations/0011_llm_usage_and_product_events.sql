-- v3 B5: 计量双表（DDL 逐字对齐方案 §5 代码块）。
-- llm_usage: 每次真实 provider 请求一行（fail-open 写入，遥测不影响 P0）；
-- product_events: 产品事件计数（login/session_created/consult_turn/
-- run_started/resume_parse）。
CREATE TABLE IF NOT EXISTS llm_usage (
  id BIGSERIAL PRIMARY KEY,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  user_id TEXT, session_id TEXT,
  provider TEXT NOT NULL, model TEXT NOT NULL, purpose TEXT NOT NULL,
  prompt_tokens INT, completion_tokens INT,
  total_tokens INT NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_llm_usage_created ON llm_usage (created_at);
CREATE INDEX IF NOT EXISTS idx_llm_usage_user ON llm_usage (user_id, created_at);
CREATE TABLE IF NOT EXISTS product_events (
  id BIGSERIAL PRIMARY KEY,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  kind TEXT NOT NULL, user_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_product_events_kind ON product_events (kind, created_at);
