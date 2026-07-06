-- Collaboration hardening: tenant-safe work queue, session sharing, team membership.

-- Work item ids are sequential per tenant (WI-1, WI-2...), so the relational
-- identity must include tenant_id.
DO $$
DECLARE
    pk_name TEXT;
BEGIN
    SELECT conname INTO pk_name
    FROM pg_constraint
    WHERE conrelid = 'work_items'::regclass
      AND contype = 'p';

    IF pk_name IS NOT NULL AND pk_name <> 'work_items_tenant_id_id_pkey' THEN
        EXECUTE format('ALTER TABLE work_items DROP CONSTRAINT %I', pk_name);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'work_items'::regclass
          AND conname = 'work_items_tenant_id_id_pkey'
    ) THEN
        ALTER TABLE work_items
            ADD CONSTRAINT work_items_tenant_id_id_pkey PRIMARY KEY (tenant_id, id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS work_items_tenant_assignee_status_idx
    ON work_items (tenant_id, assignee_id, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS work_items_tenant_session_idx
    ON work_items (tenant_id, session_id)
    WHERE session_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS work_items_approval_ids_gin_idx
    ON work_items USING GIN (approval_ids);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'work_items'::regclass
          AND conname = 'work_items_status_check'
    ) THEN
        ALTER TABLE work_items
            ADD CONSTRAINT work_items_status_check
            CHECK (status IN ('open', 'in_progress', 'review', 'done', 'cancelled'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'work_items'::regclass
          AND conname = 'work_items_priority_check'
    ) THEN
        ALTER TABLE work_items
            ADD CONSTRAINT work_items_priority_check
            CHECK (priority IN ('low', 'normal', 'high', 'urgent'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'work_items'::regclass
          AND conname = 'work_items_source_check'
    ) THEN
        ALTER TABLE work_items
            ADD CONSTRAINT work_items_source_check
            CHECK (source IN ('manual', 'rejection', 'ci', 'policy', 'tool_failure'));
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS work_item_events (
    event_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    TEXT NOT NULL,
    work_item_id TEXT NOT NULL,
    actor_id     UUID,
    event_type   TEXT NOT NULL,
    from_status  TEXT,
    to_status    TEXT,
    metadata     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, work_item_id)
        REFERENCES work_items (tenant_id, id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS work_item_events_tenant_item_created_idx
    ON work_item_events (tenant_id, work_item_id, created_at DESC);

CREATE INDEX IF NOT EXISTS work_item_events_tenant_type_created_idx
    ON work_item_events (tenant_id, event_type, created_at DESC);

CREATE TABLE IF NOT EXISTS tenant_members (
    tenant_id    TEXT NOT NULL,
    user_id      UUID NOT NULL,
    role         TEXT NOT NULL,
    display_name TEXT,
    email        TEXT,
    active       BOOLEAN NOT NULL DEFAULT true,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, user_id),
    CHECK (role IN ('viewer', 'developer', 'reviewer', 'lead', 'approver', 'auditor', 'admin'))
);

CREATE INDEX IF NOT EXISTS tenant_members_tenant_role_idx
    ON tenant_members (tenant_id, role, active);

CREATE TABLE IF NOT EXISTS chat_session_acl (
    tenant_id      TEXT NOT NULL,
    session_id     TEXT NOT NULL,
    principal_type TEXT NOT NULL,
    principal_id   TEXT NOT NULL,
    access_level   TEXT NOT NULL DEFAULT 'read',
    granted_by     UUID,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, session_id, principal_type, principal_id),
    CHECK (principal_type IN ('user', 'role')),
    CHECK (access_level IN ('read', 'write', 'admin'))
);

CREATE INDEX IF NOT EXISTS chat_session_acl_tenant_principal_idx
    ON chat_session_acl (tenant_id, principal_type, principal_id, access_level);

ALTER TABLE IF EXISTS chat_messages
    ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';

CREATE INDEX IF NOT EXISTS idx_chat_messages_tenant_session
    ON chat_messages (tenant_id, session_id, created_at);

ALTER TABLE work_item_counters ENABLE ROW LEVEL SECURITY;
ALTER TABLE work_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE work_item_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_session_acl ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS chat_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS session_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS chat_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS team_agents ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS team_skills ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS team_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS policy_bundles ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS tenant_active_policy ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS work_item_counters_tenant_rls ON work_item_counters;
CREATE POLICY work_item_counters_tenant_rls ON work_item_counters
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

DROP POLICY IF EXISTS work_items_tenant_rls ON work_items;
CREATE POLICY work_items_tenant_rls ON work_items
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

DROP POLICY IF EXISTS work_item_events_tenant_rls ON work_item_events;
CREATE POLICY work_item_events_tenant_rls ON work_item_events
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

DROP POLICY IF EXISTS tenant_members_tenant_rls ON tenant_members;
CREATE POLICY tenant_members_tenant_rls ON tenant_members
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

DROP POLICY IF EXISTS chat_session_acl_tenant_rls ON chat_session_acl;
CREATE POLICY chat_session_acl_tenant_rls ON chat_session_acl
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

DROP POLICY IF EXISTS chat_sessions_tenant_rls ON chat_sessions;
CREATE POLICY chat_sessions_tenant_rls ON chat_sessions
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

DROP POLICY IF EXISTS session_events_tenant_rls ON session_events;
CREATE POLICY session_events_tenant_rls ON session_events
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

DROP POLICY IF EXISTS chat_messages_tenant_rls ON chat_messages;
CREATE POLICY chat_messages_tenant_rls ON chat_messages
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

DROP POLICY IF EXISTS team_agents_tenant_rls ON team_agents;
CREATE POLICY team_agents_tenant_rls ON team_agents
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

DROP POLICY IF EXISTS team_skills_tenant_rls ON team_skills;
CREATE POLICY team_skills_tenant_rls ON team_skills
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

DROP POLICY IF EXISTS team_rules_tenant_rls ON team_rules;
CREATE POLICY team_rules_tenant_rls ON team_rules
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

DROP POLICY IF EXISTS audit_events_tenant_rls ON audit_events;
CREATE POLICY audit_events_tenant_rls ON audit_events
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

DROP POLICY IF EXISTS policy_bundles_tenant_rls ON policy_bundles;
CREATE POLICY policy_bundles_tenant_rls ON policy_bundles
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

DROP POLICY IF EXISTS tenant_active_policy_tenant_rls ON tenant_active_policy;
CREATE POLICY tenant_active_policy_tenant_rls ON tenant_active_policy
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
