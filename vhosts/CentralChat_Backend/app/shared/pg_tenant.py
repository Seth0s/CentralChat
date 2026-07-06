"""Postgres tenant context for RLS (Phase 3)."""

from __future__ import annotations

from typing import Any

try:
    import psycopg  # type: ignore
except Exception:  # pragma: no cover
    psycopg = None  # type: ignore

from app.config import CENTRAL_DEFAULT_CLIENT_ID, MEMORY_DB_URL, MEMORY_ENABLED
from app.shared.tenant_context import get_current_client_id
from app.shared.tenant_paths import sanitize_client_id


def resolve_pg_tenant_id() -> str:
    """Tenant for pgvector rows and ``SET app.tenant_id`` (JWT claim or default)."""
    cid = get_current_client_id()
    if cid:
        try:
            return sanitize_client_id(cid)
        except ValueError:
            pass
    return CENTRAL_DEFAULT_CLIENT_ID


def memory_db_enabled() -> bool:
    return bool(MEMORY_ENABLED and (MEMORY_DB_URL or "").strip())


def connect_pg(*, tenant_id: str | None = None) -> Any:
    """
    Open a pooled connection and set ``app.tenant_id`` for RLS policies.
    Uses the T5 connection pool (shared/pg_pool.py).

    Raises ``RuntimeError`` when memory DB is disabled or psycopg is missing.
    """
    if not memory_db_enabled():
        raise RuntimeError("memory_db_disabled")
    if psycopg is None:
        raise RuntimeError("psycopg_not_installed")
    tid = (tenant_id or resolve_pg_tenant_id()).strip() or CENTRAL_DEFAULT_CLIENT_ID
    from app.shared.pg_pool import pool_connection

    # Use pool context manager — caller must use `with connect_pg() as conn:`
    # For backward compat, we wrap this: if called without context manager,
    # yield the connection directly via a contextlib wrapper.
    ctx = pool_connection()
    conn = ctx.__enter__()
    # Wrap in a custom context manager that sets tenant_id + returns to pool
    return _PgConnection(ctx, conn, tid)


class _PgConnection:
    """Wraps a pooled connection with tenant_id SET on enter and auto-return on exit."""

    def __init__(self, ctx: Any, conn: Any, tenant_id: str) -> None:
        self._ctx = ctx
        self.conn = conn
        self._tid = tenant_id

    def __enter__(self) -> Any:
        with self.conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, false)", (self._tid,))
        return self.conn

    def __exit__(self, *args: Any) -> None:
        try:
            self._ctx.__exit__(*args)
        except Exception:
            pass

    def cursor(self) -> Any:
        return self.conn.cursor()


def _is_undefined_table(exc: BaseException) -> bool:
    if getattr(exc, "sqlstate", None) == "42P01":
        return True
    try:
        from psycopg import errors as pg_errors  # type: ignore

        return isinstance(exc, pg_errors.UndefinedTable)
    except Exception:
        return False


def _exec_optional(cur: Any, sql: str) -> None:
    try:
        cur.execute(sql)
    except Exception as exc:
        if not _is_undefined_table(exc):
            raise


def _apply_pg_tenant_rls_inline(cur: Any) -> None:
    """RLS policies when deploy SQL is missing or optional tables are not created yet."""
    _exec_optional(cur, "ALTER TABLE IF EXISTS memory_items ADD COLUMN IF NOT EXISTS tenant_id TEXT;")
    _exec_optional(
        cur,
        """
        UPDATE memory_items SET tenant_id = COALESCE(NULLIF(trim(owner_id), ''), 'default')
        WHERE tenant_id IS NULL;
        """,
    )
    _exec_optional(cur, "ALTER TABLE memory_items ENABLE ROW LEVEL SECURITY;")
    _exec_optional(cur, "DROP POLICY IF EXISTS memory_items_tenant_rls ON memory_items;")
    _exec_optional(
        cur,
        """
        CREATE POLICY memory_items_tenant_rls ON memory_items
          USING (tenant_id = current_setting('app.tenant_id', true))
          WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
        """,
    )

    _exec_optional(cur, "ALTER TABLE IF EXISTS document_rag_chunks ADD COLUMN IF NOT EXISTS tenant_id TEXT;")
    _exec_optional(
        cur,
        """
        UPDATE document_rag_chunks SET tenant_id = COALESCE(NULLIF(trim(owner_id), ''), 'default')
        WHERE tenant_id IS NULL;
        """,
    )
    _exec_optional(cur, "ALTER TABLE document_rag_chunks ENABLE ROW LEVEL SECURITY;")
    _exec_optional(cur, "DROP POLICY IF EXISTS document_rag_chunks_tenant_rls ON document_rag_chunks;")
    _exec_optional(
        cur,
        """
        CREATE POLICY document_rag_chunks_tenant_rls ON document_rag_chunks
          USING (tenant_id = current_setting('app.tenant_id', true))
          WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
        """,
    )

    _exec_optional(cur, "ALTER TABLE IF EXISTS agent_tools_embeddings ADD COLUMN IF NOT EXISTS tenant_id TEXT;")
    _exec_optional(cur, "UPDATE agent_tools_embeddings SET tenant_id = 'default' WHERE tenant_id IS NULL;")
    _exec_optional(cur, "ALTER TABLE agent_tools_embeddings ENABLE ROW LEVEL SECURITY;")
    _exec_optional(cur, "DROP POLICY IF EXISTS agent_tools_embeddings_tenant_rls ON agent_tools_embeddings;")
    _exec_optional(
        cur,
        """
        CREATE POLICY agent_tools_embeddings_tenant_rls ON agent_tools_embeddings
          USING (tenant_id = current_setting('app.tenant_id', true))
          WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
        """,
    )

    _exec_optional(cur, "ALTER TABLE IF EXISTS product_rag_chunks ENABLE ROW LEVEL SECURITY;")
    _exec_optional(cur, "DROP POLICY IF EXISTS product_rag_chunks_tenant_rls ON product_rag_chunks;")
    _exec_optional(
        cur,
        """
        CREATE POLICY product_rag_chunks_tenant_rls ON product_rag_chunks
          USING (tenant_id = current_setting('app.tenant_id', true))
          WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
        """,
    )


def apply_pg_tenant_rls_schema(cur: Any) -> None:
    """Best-effort tenant_id + RLS for legacy callers. Prefer migrations/015_memory_rag_schema.sql."""
    from pathlib import Path

    sql_path = Path(__file__).resolve().parents[2] / "deploy" / "postgres" / "init" / "02-tenant-rls.sql"
    if sql_path.is_file():
        try:
            cur.execute(sql_path.read_text(encoding="utf-8"))
            return
        except Exception as exc:
            if not _is_undefined_table(exc):
                raise
    _apply_pg_tenant_rls_inline(cur)
