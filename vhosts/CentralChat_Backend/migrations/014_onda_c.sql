-- Onda C — CLI auth, SIEM outbox, audit indexes

CREATE TABLE IF NOT EXISTS device_auth_codes (
    device_code TEXT PRIMARY KEY,
    user_code TEXT NOT NULL UNIQUE,
    client_label TEXT NOT NULL DEFAULT 'cli',
    status TEXT NOT NULL DEFAULT 'pending',
    sub TEXT,
    tenant_id TEXT,
    email TEXT,
    role TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    approved_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS device_auth_user_code_idx ON device_auth_codes (user_code);
CREATE INDEX IF NOT EXISTS device_auth_expires_idx ON device_auth_codes (expires_at);

CREATE TABLE IF NOT EXISTS api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT 'cli',
    role TEXT NOT NULL DEFAULT 'developer',
    key_prefix TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS api_keys_tenant_user_idx ON api_keys (tenant_id, user_id);
CREATE INDEX IF NOT EXISTS api_keys_prefix_idx ON api_keys (key_prefix);

CREATE TABLE IF NOT EXISTS siem_outbox (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT,
    envelope JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INT NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    delivered_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS siem_outbox_status_next_idx ON siem_outbox (status, next_attempt_at);
CREATE INDEX IF NOT EXISTS siem_outbox_tenant_created_idx ON siem_outbox (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS audit_events_tenant_user_created_idx
    ON audit_events (tenant_id, user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS audit_events_action_idx
    ON audit_events (action, created_at DESC);
