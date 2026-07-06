-- Session summaries + connector registry (parity with legacy postgres/init scripts).

CREATE TABLE IF NOT EXISTS session_summaries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL DEFAULT 'default',
    session_id TEXT NOT NULL,
    version INT NOT NULL,
    summary_text TEXT NOT NULL,
    covers_event_id_until TEXT,
    request_id TEXT,
    provenance TEXT NOT NULL DEFAULT 'eco_summarizer',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, session_id, version)
);

CREATE INDEX IF NOT EXISTS session_summaries_tenant_session_version
    ON session_summaries (tenant_id, session_id, version DESC);

ALTER TABLE session_summaries ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS session_summaries_tenant_rls ON session_summaries;
CREATE POLICY session_summaries_tenant_rls ON session_summaries
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE IF NOT EXISTS connectors (
    connector_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    capabilities JSONB NOT NULL DEFAULT '[]'::jsonb,
    protocol_version TEXT NOT NULL DEFAULT '1',
    device_label TEXT,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    registered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, connector_id)
);

CREATE INDEX IF NOT EXISTS connectors_tenant_last_seen
    ON connectors (tenant_id, last_seen_at DESC);

CREATE TABLE IF NOT EXISTS client_jobs (
    job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    connector_id TEXT,
    action_id TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'queued',
    lease_until TIMESTAMPTZ,
    approval_id TEXT,
    session_id TEXT,
    tool_call_id TEXT,
    result JSONB,
    error_code TEXT,
    retry_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS client_jobs_tenant_status_created
    ON client_jobs (tenant_id, status, created_at ASC);

CREATE UNIQUE INDEX IF NOT EXISTS client_jobs_tenant_tool_call_id
    ON client_jobs (tenant_id, tool_call_id)
    WHERE tool_call_id IS NOT NULL;

ALTER TABLE connectors ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS connectors_tenant_rls ON connectors;
CREATE POLICY connectors_tenant_rls ON connectors
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

ALTER TABLE client_jobs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS client_jobs_tenant_rls ON client_jobs;
CREATE POLICY client_jobs_tenant_rls ON client_jobs
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE IF NOT EXISTS workspace_sessions (
    store_key TEXT PRIMARY KEY,
    payload JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_workspace_sessions_expires_at
    ON workspace_sessions (expires_at);
