-- Admin secrets metadata (Phase 2): references and provider status in Postgres.
-- Secret values remain on filesystem vault (encrypted when CENTRAL_VAULT_MASTER_KEY is set).

CREATE TABLE IF NOT EXISTS secret_refs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    secret_key TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'custom',
    label TEXT,
    storage_kind TEXT NOT NULL DEFAULT 'filesystem_vault',
    storage_ref TEXT,
    value_prefix TEXT,
    value_fingerprint TEXT,
    active_version_id UUID,
    configured BOOLEAN NOT NULL DEFAULT false,
    created_by TEXT,
    updated_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, secret_key)
);

CREATE INDEX IF NOT EXISTS secret_refs_tenant_category_idx
    ON secret_refs (tenant_id, category);

CREATE TABLE IF NOT EXISTS provider_configs (
    tenant_id TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT true,
    config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, provider_id)
);

CREATE TABLE IF NOT EXISTS provider_key_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    secret_ref_id UUID REFERENCES secret_refs(id) ON DELETE SET NULL,
    key_prefix TEXT NOT NULL,
    key_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'retired')),
    rotated_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    retired_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS provider_key_versions_tenant_provider_idx
    ON provider_key_versions (tenant_id, provider_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS inference_provider_status (
    tenant_id TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    configured BOOLEAN NOT NULL DEFAULT false,
    last_test_at TIMESTAMPTZ,
    last_test_ok BOOLEAN,
    last_test_message TEXT,
    last_error_at TIMESTAMPTZ,
    last_error_message TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, provider_id)
);

ALTER TABLE secret_refs ENABLE ROW LEVEL SECURITY;
ALTER TABLE provider_configs ENABLE ROW LEVEL SECURITY;
ALTER TABLE provider_key_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE inference_provider_status ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS secret_refs_tenant_rls ON secret_refs;
CREATE POLICY secret_refs_tenant_rls ON secret_refs
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

DROP POLICY IF EXISTS provider_configs_tenant_rls ON provider_configs;
CREATE POLICY provider_configs_tenant_rls ON provider_configs
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

DROP POLICY IF EXISTS provider_key_versions_tenant_rls ON provider_key_versions;
CREATE POLICY provider_key_versions_tenant_rls ON provider_key_versions
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

DROP POLICY IF EXISTS inference_provider_status_tenant_rls ON inference_provider_status;
CREATE POLICY inference_provider_status_tenant_rls ON inference_provider_status
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
