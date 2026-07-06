"""H2/C3 — SIEM dispatch via durable outbox."""

from __future__ import annotations

import logging
import threading
from typing import Any

from app.config import CENTRAL_SIEM_WEBHOOK_URLS

logger = logging.getLogger(__name__)


def dispatch_siem_event(
    *,
    action: str,
    tenant_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Enqueue SIEM envelope v1 for async delivery with retry."""
    if not CENTRAL_SIEM_WEBHOOK_URLS:
        return

    def _enqueue() -> None:
        try:
            from app.shared.siem_outbox import enqueue_siem_event

            enqueue_siem_event(action=action, tenant_id=tenant_id, metadata=metadata)
        except Exception:
            logger.debug("siem enqueue failed action=%s", action, exc_info=True)

    threading.Thread(target=_enqueue, daemon=True).start()
