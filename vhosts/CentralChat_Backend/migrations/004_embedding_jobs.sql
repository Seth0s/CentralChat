-- T7 — Embedding jobs table for async worker processing
-- The worker polls this table and processes pending jobs.
-- NOTIFY is sent on INSERT to wake the worker immediately.

CREATE TABLE IF NOT EXISTS embedding_jobs (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     TEXT NOT NULL DEFAULT 'default',
    kind          TEXT NOT NULL DEFAULT 'query',   -- 'query' | 'ingest' | 'index'
    source_key    TEXT,                             -- doc_id, tool name, session_id
    input_text    TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',  -- 'pending' | 'processing' | 'done' | 'failed'
    embedding     vector(384),                      -- result (stored for cache reuse)
    embedding_model_id TEXT,
    error_message TEXT,
    priority      INT NOT NULL DEFAULT 0,           -- higher = processed first
    attempts      INT NOT NULL DEFAULT 0,
    max_attempts  INT NOT NULL DEFAULT 3,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at    TIMESTAMPTZ,
    completed_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_embedding_jobs_pending
    ON embedding_jobs (status, priority DESC, created_at)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_embedding_jobs_source
    ON embedding_jobs (tenant_id, kind, source_key);

-- Trigger to NOTIFY on new jobs
CREATE OR REPLACE FUNCTION notify_embedding_job()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_notify('embedding_jobs', NEW.id::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_embedding_jobs_notify ON embedding_jobs;
CREATE TRIGGER trg_embedding_jobs_notify
    AFTER INSERT ON embedding_jobs
    FOR EACH ROW EXECUTE FUNCTION notify_embedding_job();
