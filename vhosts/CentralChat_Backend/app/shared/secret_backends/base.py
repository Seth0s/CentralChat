"""Secret backend protocol (Phase 3)."""

from __future__ import annotations

from typing import Protocol


class SecretBackendReadOnlyError(RuntimeError):
    """Raised when a read-only backend receives a write/delete."""


class SecretBackend(Protocol):
    backend_id: str

    def is_available(self) -> bool:
        """Whether the backend is configured and reachable (best-effort)."""

    def read(self, logical_key: str) -> str:
        """Return secret value or empty string when missing."""

    def write(self, logical_key: str, value: str) -> None:
        ...

    def delete(self, logical_key: str) -> None:
        ...

    def describe(self) -> dict[str, str]:
        """Non-sensitive snapshot for admin/ops."""
