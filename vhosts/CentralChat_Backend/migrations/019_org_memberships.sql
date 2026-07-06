-- Organization scope model: groups, projects, and scoped memberships.

CREATE TABLE IF NOT EXISTS groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at TIMESTAMPTZ,
    UNIQUE (tenant_id, slug)
);

CREATE INDEX IF NOT EXISTS groups_tenant_name_idx
    ON groups (tenant_id, name);

CREATE TABLE IF NOT EXISTS projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    group_id UUID NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    repository_url TEXT,
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at TIMESTAMPTZ,
    UNIQUE (tenant_id, group_id, slug)
);

CREATE INDEX IF NOT EXISTS projects_tenant_group_name_idx
    ON projects (tenant_id, group_id, name);

CREATE TABLE IF NOT EXISTS memberships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    user_id UUID NOT NULL,
    scope_type TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    role TEXT NOT NULL,
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, user_id, scope_type, scope_id),
    CHECK (scope_type IN ('organization', 'group', 'project')),
    CHECK (role IN ('admin', 'lead', 'developer', 'auditor'))
);

CREATE INDEX IF NOT EXISTS memberships_tenant_user_idx
    ON memberships (tenant_id, user_id);

CREATE INDEX IF NOT EXISTS memberships_tenant_scope_role_idx
    ON memberships (tenant_id, scope_type, scope_id, role);

CREATE INDEX IF NOT EXISTS memberships_tenant_scope_user_idx
    ON memberships (tenant_id, scope_type, scope_id, user_id);

ALTER TABLE groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE memberships ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS groups_tenant_rls ON groups;
CREATE POLICY groups_tenant_rls ON groups
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

DROP POLICY IF EXISTS projects_tenant_rls ON projects;
CREATE POLICY projects_tenant_rls ON projects
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

DROP POLICY IF EXISTS memberships_tenant_rls ON memberships;
CREATE POLICY memberships_tenant_rls ON memberships
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
