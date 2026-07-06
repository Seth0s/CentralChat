"""D2.3/D2.4 — Ops alerts (Slack + generic webhook)."""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

import httpx

from app.shared.secret_resolver import resolve_alert_webhook_urls

logger = logging.getLogger(__name__)


def _post(url: str, payload: dict[str, Any]) -> None:
    try:
        if "hooks.slack.com" in url:
            httpx.post(url, json={"text": payload.get("text", json.dumps(payload))}, timeout=5.0)
        else:
            httpx.post(url, json=payload, timeout=5.0)
    except Exception:
        logger.debug("alert webhook failed url=%s", url, exc_info=True)


def send_ops_alert(*, action: str, text: str, metadata: dict[str, Any] | None = None) -> None:
    payload = {
        "source": "centralchat",
        "action": action,
        "text": text,
        "metadata": metadata or {},
    }
    urls = resolve_alert_webhook_urls()
    if not urls:
        return

    def _run() -> None:
        for url in urls:
            _post(url, payload)

    threading.Thread(target=_run, daemon=True).start()
