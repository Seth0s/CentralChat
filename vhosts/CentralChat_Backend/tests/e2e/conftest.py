"""Onda A — e2e fixtures."""

from __future__ import annotations

import pytest

from tests.e2e.helpers import stack_reachable


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "e2e: live stack e2e")
    config.addinivalue_line("markers", "e2e_llm: e2e with real LLM")


@pytest.fixture(scope="session")
def require_stack() -> None:
    if not stack_reachable():
        pytest.skip("E2E stack not reachable — run: ./startup-testing.sh (SKIP_E2E=1 to skip)")
