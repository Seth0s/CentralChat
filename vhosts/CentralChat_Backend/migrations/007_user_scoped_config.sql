-- M1 — User-scoped configuration tables
-- 4 tabelas: user_cloud_models, user_agents, user_skills, user_preferences
-- Cada tabela tem version (optimistic concurrency) + source (web/desktop)
-- Executar: python scripts/run_migrations.py --db-url $MEMORY_DB_URL

-- 1. Cloud models allowlist (per-user, substitui JSON global)
CREATE TABLE IF NOT EXISTS user_cloud_models (
    user_id    UUID NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    model_id   TEXT NOT NULL,
    label      TEXT NOT NULL DEFAULT '',
    enabled    BOOLEAN NOT NULL DEFAULT true,
    version    INTEGER NOT NULL DEFAULT 1,
    source     TEXT NOT NULL DEFAULT 'web',      -- 'web' | 'desktop'
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, model_id)
);

-- 2. Agent personas (per-user)
CREATE TABLE IF NOT EXISTS user_agents (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    prompt     TEXT NOT NULL DEFAULT '',
    model_id   TEXT,
    icon       TEXT NOT NULL DEFAULT '',
    version    INTEGER NOT NULL DEFAULT 1,
    source     TEXT NOT NULL DEFAULT 'web',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS user_agents_user_id_idx ON user_agents (user_id);

-- 3. Skill blocks (per-user)
CREATE TABLE IF NOT EXISTS user_skills (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    prompt      TEXT NOT NULL DEFAULT '',
    enabled     BOOLEAN NOT NULL DEFAULT true,
    version     INTEGER NOT NULL DEFAULT 1,
    source      TEXT NOT NULL DEFAULT 'web',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS user_skills_user_id_idx ON user_skills (user_id);

-- 4. Key-value preferences (per-user, substitui state/clients/<id>/)
CREATE TABLE IF NOT EXISTS user_preferences (
    user_id    UUID NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    key        TEXT NOT NULL,
    value      JSONB NOT NULL DEFAULT '{}'::jsonb,
    version    INTEGER NOT NULL DEFAULT 1,
    source     TEXT NOT NULL DEFAULT 'web',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, key)
);
