-- T17 — Multi-Agent Tree: Migration (agent_trees, agent_nodes)

CREATE TABLE IF NOT EXISTS agent_trees (
    id          TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL DEFAULT 'default',
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    root_node_id TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agent_trees_tenant
    ON agent_trees (tenant_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS agent_nodes (
    id          TEXT PRIMARY KEY,
    tree_id     TEXT NOT NULL REFERENCES agent_trees(id) ON DELETE CASCADE,
    parent_id   TEXT REFERENCES agent_nodes(id) ON DELETE CASCADE,
    agent_name  TEXT NOT NULL DEFAULT 'default',
    position    INTEGER NOT NULL DEFAULT 0,
    label       TEXT NOT NULL DEFAULT '',
    config      JSONB NOT NULL DEFAULT '{}'::jsonb,
    inherit_mode TEXT NOT NULL DEFAULT 'full'
        CHECK (inherit_mode IN ('none', 'summary', 'full')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agent_nodes_tree
    ON agent_nodes (tree_id, position);

CREATE INDEX IF NOT EXISTS idx_agent_nodes_parent
    ON agent_nodes (parent_id);
