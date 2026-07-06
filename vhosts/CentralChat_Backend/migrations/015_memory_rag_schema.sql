-- Memory + RAG pgvector tables and tenant RLS (canonical schema; was lazy DDL in app/rag.py).

CREATE TABLE IF NOT EXISTS memory_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL DEFAULT 'default',
    owner_id TEXT NOT NULL DEFAULT 'default',
    namespace TEXT NOT NULL,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    tags TEXT[] NOT NULL DEFAULT '{}',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    score_boost DOUBLE PRECISION NOT NULL DEFAULT 0,
    embedding vector(256),
    embedding_model_id TEXT NOT NULL DEFAULT 'local_hash_v1',
    embedding_dim INT NOT NULL DEFAULT 256,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NULL,
    last_accessed_at TIMESTAMPTZ NULL,
    is_deleted BOOLEAN NOT NULL DEFAULT false
);

CREATE UNIQUE INDEX IF NOT EXISTS memory_items_tenant_dedupe
    ON memory_items (tenant_id, namespace, kind, content_hash);
CREATE INDEX IF NOT EXISTS memory_items_tenant_ns_created
    ON memory_items (tenant_id, namespace, created_at DESC)
    WHERE is_deleted = false;

CREATE TABLE IF NOT EXISTS document_rag_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL DEFAULT 'default',
    owner_id TEXT NOT NULL DEFAULT 'default',
    doc_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    chunk_index INT NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding vector(384),
    embedding_model_id TEXT NOT NULL,
    embedding_dim INT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, doc_id, chunk_index)
);
CREATE INDEX IF NOT EXISTS document_rag_chunks_tenant_doc_idx
    ON document_rag_chunks (tenant_id, doc_id);

CREATE TABLE IF NOT EXISTS product_rag_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL DEFAULT 'default',
    source_key TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'doc',
    title TEXT NOT NULL DEFAULT '',
    chunk_index INT NOT NULL DEFAULT 0,
    content TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding vector(384),
    embedding_model_id TEXT NOT NULL,
    embedding_dim INT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, source_key, chunk_index)
);
CREATE INDEX IF NOT EXISTS product_rag_chunks_tenant_kind
    ON product_rag_chunks (tenant_id, kind);

CREATE TABLE IF NOT EXISTS agent_tools_embeddings (
    tenant_id TEXT NOT NULL DEFAULT 'default',
    name TEXT NOT NULL,
    description_doc TEXT NOT NULL,
    schema_json JSONB NOT NULL,
    embedding vector(384),
    embedding_model_id TEXT NOT NULL,
    embedding_dim INT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, name)
);

-- memory_items RLS
ALTER TABLE memory_items ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS memory_items_tenant_rls ON memory_items;
CREATE POLICY memory_items_tenant_rls ON memory_items
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

-- document_rag_chunks RLS
ALTER TABLE document_rag_chunks ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS document_rag_chunks_tenant_rls ON document_rag_chunks;
CREATE POLICY document_rag_chunks_tenant_rls ON document_rag_chunks
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

-- product_rag_chunks RLS
ALTER TABLE product_rag_chunks ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS product_rag_chunks_tenant_rls ON product_rag_chunks;
CREATE POLICY product_rag_chunks_tenant_rls ON product_rag_chunks
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

-- agent_tools_embeddings RLS
ALTER TABLE agent_tools_embeddings ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS agent_tools_embeddings_tenant_rls ON agent_tools_embeddings;
CREATE POLICY agent_tools_embeddings_tenant_rls ON agent_tools_embeddings
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
