"""Phase 3 — pg tenant resolution, MEMORY_ENABLED degrade, optional Postgres RLS."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.context.embedding_service import LocalEmbeddingService, MEMORY_HASH_DIM
from app.memory_store_pgvector import embed_local_hash, search_memory, upsert_memory_item
from app.pg_tenant import memory_db_enabled, resolve_pg_tenant_id
from app.tenant_context import set_tenant_context


class TestResolvePgTenant(unittest.TestCase):
    def tearDown(self) -> None:
        set_tenant_context(client_id=None, sub=None)

    @patch("app.config.CENTRAL_DEFAULT_CLIENT_ID", "default")
    def test_default_without_jwt(self) -> None:
        set_tenant_context(client_id=None, sub=None)
        self.assertEqual(resolve_pg_tenant_id(), "default")

    def test_uses_jwt_client_id(self) -> None:
        set_tenant_context(client_id="acme-corp", sub="u1")
        self.assertEqual(resolve_pg_tenant_id(), "acme-corp")


class TestMemoryDisabled(unittest.TestCase):
    @patch("app.memory_store_pgvector.memory_db_enabled", return_value=False)
    def test_search_returns_empty(self, _mock: unittest.mock.MagicMock) -> None:
        out = search_memory(namespace="project", query_embedding=embed_local_hash("q"))
        self.assertEqual(out, [])

    @patch("app.memory_store_pgvector.memory_db_enabled", return_value=False)
    def test_upsert_returns_none(self, _mock: unittest.mock.MagicMock) -> None:
        out = upsert_memory_item(
            namespace="project",
            kind="note",
            content="x",
            tags=[],
            request_id="r1",
            embedding=embed_local_hash("x"),
            embedding_model_id="local_hash_v1",
        )
        self.assertIsNone(out)


class TestEmbeddingService(unittest.TestCase):
    def test_memory_hash_dim(self) -> None:
        svc = LocalEmbeddingService()
        vec, mid = svc.embed_memory("hello")
        self.assertEqual(len(vec), MEMORY_HASH_DIM)
        self.assertIn("hash", mid)


def _postgres_url() -> str:
    return os.getenv(
        "TEST_MEMORY_DB_URL",
        "postgresql://central:central@127.0.0.1:5433/central_memory",
    ).strip()


def _postgres_available() -> bool:
    if os.getenv("SKIP_PG_INTEGRATION", "").strip().lower() in ("1", "true", "yes"):
        return False
    try:
        import psycopg  # type: ignore

        with psycopg.connect(_postgres_url(), connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
        return True
    except Exception:
        return False


@unittest.skipUnless(_postgres_available(), "Postgres/pgvector not available on TEST_MEMORY_DB_URL")
class TestPgvectorRlsIntegration(unittest.TestCase):
    def setUp(self) -> None:
        import psycopg  # type: ignore

        self._url = _postgres_url()
        self._psycopg = psycopg
        set_tenant_context(client_id=None, sub=None)

    def tearDown(self) -> None:
        set_tenant_context(client_id=None, sub=None)

    def test_cross_tenant_search_isolated(self) -> None:
        with (
            patch("app.config.MEMORY_DB_URL", self._url),
            patch("app.config.MEMORY_ENABLED", True),
            patch("app.pg_tenant.MEMORY_DB_URL", self._url),
            patch("app.pg_tenant.MEMORY_ENABLED", True),
        ):
            from app.memory_store_pgvector import ensure_schema, search_memory, upsert_memory_item

            ensure_schema(embedding_dim=8)
            vec = embed_local_hash("secret-tenant-a-payload", dim=8)
            upsert_memory_item(
                namespace="rls_test",
                kind="probe",
                content="tenant-a-secret",
                tags=[],
                request_id="rls-a",
                embedding=vec,
                embedding_model_id="test_hash",
                tenant_id="tenant-a",
            )
            hits_b = search_memory(
                namespace="rls_test",
                query_embedding=vec,
                top_k=5,
                tenant_id="tenant-b",
            )
            hits_a = search_memory(
                namespace="rls_test",
                query_embedding=vec,
                top_k=5,
                tenant_id="tenant-a",
            )
        self.assertEqual(len(hits_b), 0)
        self.assertGreaterEqual(len(hits_a), 1)


if __name__ == "__main__":
    unittest.main()
