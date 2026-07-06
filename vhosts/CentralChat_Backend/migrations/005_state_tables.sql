-- T9 — State tables migration: session_events, chat_sessions, assistant_preferences
-- Dual-write support: these tables mirror the disk-based stores.

-- Session events (append-only JSONL on disk → relational in PG)
CREATE TABLE IF NOT EXISTS session_events (
    id          BIGSERIAL PRIMARY KEY,
    tenant_id   TEXT NOT NULL DEFAULT 'default',
    session_id  TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_session_events_session
    ON session_events (tenant_id, session_id, created_at);

CREATE INDEX IF NOT EXISTS idx_session_events_type
    ON session_events (tenant_id, event_type, created_at);

-- Chat sessions (JSON file → relational)
CREATE TABLE IF NOT EXISTS chat_sessions (
    id          TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL DEFAULT 'default',
    title       TEXT NOT NULL DEFAULT 'Conversa',
    pinned      BOOLEAN NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_tenant
    ON chat_sessions (tenant_id, updated_at DESC);

-- Chat session messages (normalized out of the JSON)
CREATE TABLE IF NOT EXISTS chat_messages (
    id          BIGSERIAL PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    slot        INT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session
    ON chat_messages (session_id, created_at);

-- Assistant preferences (JSON file → relational key-value)
CREATE TABLE IF NOT EXISTS assistant_preferences (
    tenant_id   TEXT PRIMARY KEY,
    prefs_json  JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
