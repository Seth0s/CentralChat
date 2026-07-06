-- T3 — tenant_quotas: rastreamento de uso por tenant
-- Executar: psql $MEMORY_DB_URL -f migrations/002_tenant_quotas.sql

CREATE TABLE IF NOT EXISTS tenant_quotas (
    id            SERIAL PRIMARY KEY,
    tenant_id     TEXT NOT NULL,
    period_start  TIMESTAMPTZ NOT NULL,
    period_end    TIMESTAMPTZ NOT NULL,
    tokens_input  BIGINT NOT NULL DEFAULT 0,
    tokens_output BIGINT NOT NULL DEFAULT 0,
    cost_input    DOUBLE PRECISION NOT NULL DEFAULT 0,
    cost_output   DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tenant_quotas_tenant_period
    ON tenant_quotas (tenant_id, period_start DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_tenant_quotas_period_unique
    ON tenant_quotas (tenant_id, period_start, period_end);
