"""T5.2 — RLS cross-tenant isolation tests.

Validate that Row-Level Security prevents cross-tenant data access.
Requires Postgres with RLS enabled (MEMORY_DB_URL or TEST_MEMORY_DB_URL).
"""

import os
import uuid

import pytest

# Test constants
TENANT_A = f"test-tenant-a-{uuid.uuid4().hex[:8]}"
TENANT_B = f"test-tenant-b-{uuid.uuid4().hex[:8]}"

DB_URL = os.getenv("TEST_MEMORY_DB_URL", os.getenv("MEMORY_DB_URL", ""))


def _connect(tenant_id: str):
    """Open a connection with tenant_id set for RLS."""
    import psycopg

    conn = psycopg.connect(DB_URL, autocommit=True)
    conn.cursor().execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))
    return conn


def _ensure_tables(conn):
    """Ensure test tables exist."""
    cur = conn.cursor()
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")
    # tenant_config
    cur.execute(
        """CREATE TABLE IF NOT EXISTS tenant_config (
            tenant_id TEXT PRIMARY KEY, display_name TEXT DEFAULT '',
            max_concurrent_streams INT DEFAULT 3,
            rate_limit_per_window INT DEFAULT 60,
            rate_limit_window_seconds INT DEFAULT 60,
            features_json JSONB DEFAULT '{}',
            created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now());"""
    )
    cur.execute("ALTER TABLE tenant_config ENABLE ROW LEVEL SECURITY;")
    cur.execute("DROP POLICY IF EXISTS tenant_config_rls_test ON tenant_config;")
    cur.execute(
        """CREATE POLICY tenant_config_rls_test ON tenant_config
           USING (tenant_id = current_setting('app.tenant_id', true));"""
    )
    # Insert test data for both tenants
    cur.execute(
        "INSERT INTO tenant_config (tenant_id, display_name) VALUES (%s, %s) ON CONFLICT DO NOTHING;",
        (TENANT_A, "Tenant A"),
    )
    cur.execute(
        "INSERT INTO tenant_config (tenant_id, display_name) VALUES (%s, %s) ON CONFLICT DO NOTHING;",
        (TENANT_B, "Tenant B"),
    )
    conn.commit()


@pytest.fixture(scope="module")
def db_setup():
    if not DB_URL:
        pytest.skip("TEST_MEMORY_DB_URL or MEMORY_DB_URL not set")
    conn = _connect("default")
    try:
        _ensure_tables(conn)
        yield
    finally:
        # Cleanup test rows
        cur = conn.cursor()
        cur.execute("DELETE FROM tenant_config WHERE tenant_id = %s;", (TENANT_A,))
        cur.execute("DELETE FROM tenant_config WHERE tenant_id = %s;", (TENANT_B,))
        conn.commit()
        conn.close()


def test_tenant_a_sees_own_config(db_setup):
    """Tenant A can read its own config."""
    conn = _connect(TENANT_A)
    cur = conn.cursor()
    cur.execute("SELECT display_name FROM tenant_config WHERE tenant_id = %s;", (TENANT_A,))
    rows = cur.fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0][0] == "Tenant A"


def test_tenant_b_sees_own_config(db_setup):
    """Tenant B can read its own config."""
    conn = _connect(TENANT_B)
    cur = conn.cursor()
    cur.execute("SELECT display_name FROM tenant_config WHERE tenant_id = %s;", (TENANT_B,))
    rows = cur.fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0][0] == "Tenant B"


def test_tenant_a_cannot_see_tenant_b(db_setup):
    """Tenant A should NOT see Tenant B's config via SELECT without WHERE tenant_id."""
    conn = _connect(TENANT_A)
    cur = conn.cursor()
    # With RLS, SELECT * should only return rows matching current tenant
    cur.execute("SELECT tenant_id FROM tenant_config;")
    rows = cur.fetchall()
    conn.close()
    tenant_ids = {r[0] for r in rows}
    assert TENANT_A in tenant_ids
    assert TENANT_B not in tenant_ids, f"RLS leak! Tenant A saw: {tenant_ids}"


def test_tenant_b_cannot_see_tenant_a(db_setup):
    """Tenant B should NOT see Tenant A's config."""
    conn = _connect(TENANT_B)
    cur = conn.cursor()
    cur.execute("SELECT tenant_id FROM tenant_config;")
    rows = cur.fetchall()
    conn.close()
    tenant_ids = {r[0] for r in rows}
    assert TENANT_B in tenant_ids
    assert TENANT_A not in tenant_ids, f"RLS leak! Tenant B saw: {tenant_ids}"
