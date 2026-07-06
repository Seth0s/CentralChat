-- Fase 3 — Team catalog (tenant-wide agents, skills, governed rules)
-- Executar: python scripts/run_migrations.py --db-url $MEMORY_DB_URL

CREATE EXTENSION IF NOT EXISTS vector;

-- Team agents (tenant-wide, versioned)
CREATE TABLE IF NOT EXISTS team_agents (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   TEXT NOT NULL,
    name        TEXT NOT NULL,
    prompt      TEXT NOT NULL DEFAULT '',
    model_id    TEXT,
    icon        TEXT NOT NULL DEFAULT '',
    published   BOOLEAN NOT NULL DEFAULT true,
    version     INTEGER NOT NULL DEFAULT 1,
    created_by  UUID REFERENCES auth_users(id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);
CREATE INDEX IF NOT EXISTS team_agents_tenant_idx ON team_agents (tenant_id, name);

-- Team skills (published by admin)
CREATE TABLE IF NOT EXISTS team_skills (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   TEXT NOT NULL,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    prompt      TEXT NOT NULL DEFAULT '',
    enabled     BOOLEAN NOT NULL DEFAULT true,
    published   BOOLEAN NOT NULL DEFAULT true,
    version     INTEGER NOT NULL DEFAULT 1,
    created_by  UUID REFERENCES auth_users(id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);
CREATE INDEX IF NOT EXISTS team_skills_tenant_idx ON team_skills (tenant_id, name);

-- Team rules — only approved rows enter ContextPipeline L4
CREATE TABLE IF NOT EXISTS team_rules (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          TEXT NOT NULL,
    pattern            TEXT NOT NULL,
    source             TEXT NOT NULL DEFAULT 'manual',
    proposed_by        UUID REFERENCES auth_users(id) ON DELETE SET NULL,
    approved_by        UUID REFERENCES auth_users(id) ON DELETE SET NULL,
    approved           BOOLEAN NOT NULL DEFAULT false,
    rejection_context  JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding          vector(384),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS team_rules_tenant_approved_idx
    ON team_rules (tenant_id, approved, created_at DESC);

-- Default agent for dev tenants
INSERT INTO team_agents (tenant_id, name, prompt, published)
VALUES (
    'default',
    'default',
    'You are Central, an engineering assistant. Be concise, prefer safe changes, and ask before destructive actions.',
    true
)
ON CONFLICT (tenant_id, name) DO NOTHING;
