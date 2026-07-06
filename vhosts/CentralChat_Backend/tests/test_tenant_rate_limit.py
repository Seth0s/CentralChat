"""Fase 12 — rate limit por tenant."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import tenant_rate_limit as trl
from app.http.auth_context_middleware import install_auth_context_middleware
from app.http.middleware import install_orchestrator_middleware
from app.http.problem_details import register_exception_handlers
from app.server import router_assistant


def _mini_app() -> FastAPI:
    application = FastAPI()
    register_exception_handlers(application)
    install_orchestrator_middleware(application)
    install_auth_context_middleware(application)
    application.include_router(router_assistant)
    return application


class TestTenantRateLimit(unittest.TestCase):
    def tearDown(self) -> None:
        trl.reset_rate_limit_state_for_tests()

    def test_sliding_window_blocks(self) -> None:
        with patch.object(trl._cfg, "CENTRAL_RATE_LIMIT_ENABLED", True):
            with patch.object(trl._cfg, "CENTRAL_RATE_LIMIT_PER_WINDOW", 3):
                with patch.object(trl._cfg, "CENTRAL_RATE_LIMIT_WINDOW_SECONDS", 60):
                    self.assertTrue(trl.allow_tenant_request(tenant_key="t1")[0])
                    self.assertTrue(trl.allow_tenant_request(tenant_key="t1")[0])
                    self.assertTrue(trl.allow_tenant_request(tenant_key="t1")[0])
                    ok, ra = trl.allow_tenant_request(tenant_key="t1")
                    self.assertFalse(ok)
                    self.assertIsNotNone(ra)
                    self.assertTrue(trl.allow_tenant_request(tenant_key="t2")[0])

    def test_post_assistant_returns_429_when_enabled(self) -> None:
        with patch.object(trl._cfg, "CENTRAL_RATE_LIMIT_ENABLED", True):
            with patch.object(trl._cfg, "CENTRAL_RATE_LIMIT_PER_WINDOW", 2):
                with patch.object(trl._cfg, "CENTRAL_RATE_LIMIT_WINDOW_SECONDS", 60):
                    with patch.object(trl._cfg, "CENTRAL_JWT_MODE", "off"):
                        trl.reset_rate_limit_state_for_tests()
                        client = TestClient(_mini_app())
                        body = {
                            "text": "hello",
                            "history": [],
                            "use_saved_assistant_defaults": False,
                        }
                        self.assertEqual(client.post("/assistant/text", json=body).status_code, 502)
                        self.assertEqual(client.post("/assistant/text", json=body).status_code, 502)
                        self.assertEqual(client.post("/assistant/text", json=body).status_code, 429)


if __name__ == "__main__":
    unittest.main()
