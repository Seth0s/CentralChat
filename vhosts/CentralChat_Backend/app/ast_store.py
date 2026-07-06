"""AST Store — PostgreSQL + pgvector storage for AST nodes.

Supports:
- upsert_nodes: insert/update AST nodes with embeddings
- query_nodes: semantic search via pgvector cosine distance
- Graph expansion: follow imports/references for context

Design doc: docs/CONTEXT_AND_AGENT_PLATFORM_PLAN.md §10
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

AST_VECTOR_DIM = 256  # Matches embed_local_hash dimension


def ensure_ast_schema() -> None:
    """Create ast_nodes table if not exists."""
    try:
        from app.shared.pg_tenant import connect_pg, memory_db_enabled

        if not memory_db_enabled():
            return

        with connect_pg() as conn, conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            cur.execute(
                f"""CREATE TABLE IF NOT EXISTS ast_nodes (
                    id SERIAL PRIMARY KEY,
                    tenant_id TEXT NOT NULL DEFAULT 'default',
                    node_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    qualified_name TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    line_start INT,
                    line_end INT,
                    docstring TEXT,
                    signature TEXT,
                    parent_name TEXT,
                    body TEXT,
                    source_hash TEXT NOT NULL,
                    metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    embedding vector({AST_VECTOR_DIM}),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );"""
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS ast_nodes_tenant_file_idx "
                "ON ast_nodes (tenant_id, file_path);"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS ast_nodes_qualified_name_idx "
                "ON ast_nodes (tenant_id, qualified_name);"
            )
    except Exception:
        logger.debug("AST schema creation failed", exc_info=True)


def upsert_ast_nodes(
    nodes: list[Any],  # list[AstNode]
    *,
    tenant_id: str = "default",
    replace_file: bool = True,
) -> int:
    """Upsert AST nodes into pgvector.

    Args:
        nodes: Parsed AstNode objects
        tenant_id: Tenant scope
        replace_file: If True, delete existing nodes for the same file before insert

    Returns:
        Number of nodes upserted
    """
    try:
        from app.shared.pg_tenant import connect_pg, memory_db_enabled

        if not memory_db_enabled() or not nodes:
            return 0

        ensure_ast_schema()

        with connect_pg() as conn, conn.cursor() as cur:
            file_path = nodes[0].file_path

            if replace_file:
                cur.execute(
                    "DELETE FROM ast_nodes WHERE tenant_id = %s AND file_path = %s",
                    (tenant_id, file_path),
                )

            count = 0
            for node in nodes:
                # Generate embedding from docstring + signature + body
                embed_text = " ".join(filter(None, [
                    node.docstring or "",
                    node.signature or "",
                    node.body or "",
                ]))
                embedding = _embed_text(embed_text)

                cur.execute(
                    """INSERT INTO ast_nodes (
                        tenant_id, node_type, name, qualified_name,
                        file_path, line_start, line_end,
                        docstring, signature, parent_name, body,
                        source_hash, metadata, embedding
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING""",
                    (
                        tenant_id,
                        node.node_type,
                        node.name,
                        node.qualified_name,
                        node.file_path,
                        node.line_start,
                        node.line_end,
                        node.docstring,
                        node.signature,
                        node.parent_name,
                        node.body,
                        node.source_hash,
                        json.dumps(node.metadata, default=str),
                        embedding,
                    ),
                )
                count += 1

            return count
    except Exception:
        logger.debug("AST upsert failed", exc_info=True)
        return 0


def query_ast_nodes(
    query: str,
    *,
    tenant_id: str = "default",
    file_path: str | None = None,
    node_types: list[str] | None = None,
    top_k: int = 10,
    expand_imports: bool = False,
) -> list[dict[str, Any]]:
    """Query AST nodes by semantic similarity.

    Args:
        query: Natural language query
        tenant_id: Tenant scope
        file_path: Optional file path filter
        node_types: Optional node type filter
        top_k: Max results
        expand_imports: If True, follow internal imports for context

    Returns:
        List of matching nodes with similarity scores
    """
    try:
        from app.shared.pg_tenant import connect_pg, memory_db_enabled

        if not memory_db_enabled():
            return []

        ensure_ast_schema()
        embedding = _embed_text(query)

        conditions = ["tenant_id = %s"]
        params: list = [tenant_id]

        if file_path:
            conditions.append("file_path = %s")
            params.append(file_path)
        if node_types:
            placeholders = ", ".join(["%s"] * len(node_types))
            conditions.append(f"node_type IN ({placeholders})")
            params.extend(node_types)

        where = " AND ".join(conditions)

        with connect_pg() as conn, conn.cursor() as cur:
            cur.execute(
                f"""SELECT id, node_type, name, qualified_name, file_path,
                    line_start, line_end, docstring, signature,
                    parent_name, body, metadata,
                    1 - (embedding <=> %s) AS similarity
                FROM ast_nodes
                WHERE {where}
                ORDER BY embedding <=> %s
                LIMIT %s""",
                [embedding] + params + [embedding, top_k],
            )
            rows = cur.fetchall()

        results = []
        for row in rows:
            node = {
                "id": row[0], "node_type": row[1], "name": row[2],
                "qualified_name": row[3], "file_path": row[4],
                "line_start": row[5], "line_end": row[6],
                "docstring": row[7], "signature": row[8],
                "parent_name": row[9], "body": row[10],
                "metadata": row[11] if isinstance(row[11], dict) else {},
                "similarity": round(float(row[12]), 4),
            }
            results.append(node)

        # Graph expansion: follow internal imports
        if expand_imports and results:
            results = _expand_imports(results, tenant_id)

        return results
    except Exception:
        logger.debug("AST query failed", exc_info=True)
        return []


def _expand_imports(
    nodes: list[dict[str, Any]], tenant_id: str
) -> list[dict[str, Any]]:
    """Follow internal module imports to add context.

    For each import node referencing an internal module,
    fetch that module's top-level structure.
    """
    try:
        from app.shared.pg_tenant import connect_pg

        imported_modules: set[str] = set()
        for node in nodes:
            if node["node_type"] == "import":
                mod = node["metadata"].get("module", "") if isinstance(node.get("metadata"), dict) else ""
                if mod and not mod.startswith("."):  # Only internal imports
                    imported_modules.add(mod)

        if not imported_modules:
            return nodes

        with connect_pg() as conn, conn.cursor() as cur:
            for mod in list(imported_modules)[:3]:  # Limit expansion
                mod_name = mod.split(".")[-1]  # Last segment
                cur.execute(
                    """SELECT name, qualified_name, node_type, file_path,
                        docstring, signature
                    FROM ast_nodes
                    WHERE tenant_id = %s AND (name = %s OR qualified_name LIKE %s)
                    AND node_type IN ('module', 'class', 'function')
                    LIMIT 5""",
                    (tenant_id, mod_name, f"%{mod_name}%"),
                )
                for row in cur.fetchall():
                    nodes.append({
                        "node_type": f"import_ref:{row[2]}",
                        "name": row[0], "qualified_name": row[1],
                        "file_path": row[3], "docstring": row[4],
                        "signature": row[5],
                        "similarity": 0.0,
                        "imported_from": mod,
                    })

    except Exception:
        logger.debug("AST import expansion failed", exc_info=True)

    return nodes


def _embed_text(text: str) -> list[float]:
    """Generate embedding for a text string (local hash, no API call)."""
    from app.rag import embed_local_hash

    return embed_local_hash(text, dim=AST_VECTOR_DIM)
