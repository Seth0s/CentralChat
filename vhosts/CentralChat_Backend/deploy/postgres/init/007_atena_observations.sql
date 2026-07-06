-- T19.2: Atena observations table
-- Meta-agente Atena: observações de padrões de uso, correcções e sugestões.
--
-- CENTRAL_ATENA_ENABLED=0 por defeito (desligado até implementação completa).

CREATE TABLE IF NOT EXISTS atena_observations (
    observation_id   TEXT PRIMARY KEY,
    tenant_id        TEXT NOT NULL DEFAULT 'default',
    user_id          TEXT,
    kind             TEXT NOT NULL DEFAULT 'usage_pattern',
    category         TEXT NOT NULL DEFAULT 'general',
    summary          TEXT NOT NULL DEFAULT '',
    detail           JSONB NOT NULL DEFAULT '{}',
    confidence       REAL NOT NULL DEFAULT 0.0,
    applied          BOOLEAN NOT NULL DEFAULT FALSE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Índices para queries comuns
CREATE INDEX IF NOT EXISTS idx_atena_obs_tenant
    ON atena_observations (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_atena_obs_user
    ON atena_observations (tenant_id, user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_atena_obs_kind
    ON atena_observations (tenant_id, kind, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_atena_obs_applied
    ON atena_observations (tenant_id, applied, created_at DESC)
    WHERE applied = FALSE;
