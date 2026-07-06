"""Central secret resolution — env > admin vault > legacy file."""

from __future__ import annotations

import logging

from app.config import (
    CENTRAL_ALERT_SLACK_WEBHOOK_URL,
    CENTRAL_ALERT_WEBHOOK_URL,
    CENTRAL_QUOTA_WEBHOOK_URL,
    CENTRAL_SIEM_HEC_TOKEN,
    CENTRAL_SIEM_WEBHOOK_URLS,
)
from app.shared.integration_secret_keys import KNOWN_INTEGRATION_SECRETS

logger = logging.getLogger(__name__)


def resolve_integration_secret(key: str, *, env_value: str = "") -> str:
    """Priority: explicit env > admin custom secret."""
    env = (env_value or "").strip()
    if env:
        return env
    from app.shared.secrets_admin import read_custom_secret

    return read_custom_secret(key)


def _split_urls(raw: str) -> tuple[str, ...]:
    return tuple(u.strip() for u in (raw or "").split(",") if u.strip())


def resolve_siem_webhook_urls() -> tuple[str, ...]:
    if CENTRAL_SIEM_WEBHOOK_URLS:
        return CENTRAL_SIEM_WEBHOOK_URLS
    vault_urls = _split_urls(resolve_integration_secret("siem.webhook"))
    if vault_urls:
        return vault_urls
    return ()


def resolve_siem_hec_token() -> str:
    return resolve_integration_secret("siem.hec_token", env_value=CENTRAL_SIEM_HEC_TOKEN)


def resolve_alert_webhook_urls() -> list[str]:
    urls: list[str] = []
    for candidate in (
        CENTRAL_ALERT_SLACK_WEBHOOK_URL,
        CENTRAL_ALERT_WEBHOOK_URL,
        resolve_integration_secret("alert.webhook"),
    ):
        url = (candidate or "").strip()
        if url and url not in urls:
            urls.append(url)
    return urls


def resolve_quota_webhook_url() -> str:
    return resolve_integration_secret("quota.webhook", env_value=CENTRAL_QUOTA_WEBHOOK_URL)


def integration_secrets_configured() -> dict[str, bool]:
    """Snapshot for admin/health without exposing values."""
    return {
        "siem_webhooks": bool(resolve_siem_webhook_urls()),
        "siem_hec_token": bool(resolve_siem_hec_token()),
        "alert_webhooks": bool(resolve_alert_webhook_urls()),
        "quota_webhook": bool(resolve_quota_webhook_url()),
    }
