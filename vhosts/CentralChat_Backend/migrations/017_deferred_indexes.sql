-- Indexes for tables created after 003_additional_indexes (safe on fresh + existing DBs).

CREATE INDEX IF NOT EXISTS idx_memory_items_ns_created
    ON memory_items (tenant_id, namespace, created_at DESC)
    WHERE is_deleted = false;

CREATE INDEX IF NOT EXISTS idx_session_summaries_tenant_session
    ON session_summaries (tenant_id, session_id);

CREATE INDEX IF NOT EXISTS idx_workspace_sessions_expires
    ON workspace_sessions (expires_at)
    WHERE expires_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_agent_tools_embeddings_model
    ON agent_tools_embeddings (tenant_id, embedding_model_id);

CREATE INDEX IF NOT EXISTS idx_product_rag_source_key
    ON product_rag_chunks (tenant_id, source_key);

CREATE INDEX IF NOT EXISTS idx_document_rag_doc_meta
    ON document_rag_chunks (tenant_id, doc_id, chunk_index);
