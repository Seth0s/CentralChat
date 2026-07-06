"""Known custom integration secret keys (admin /admin/secrets)."""

from __future__ import annotations

from typing import Any

KNOWN_INTEGRATION_SECRETS: dict[str, dict[str, Any]] = {
    "siem.webhook": {
        "label": "SIEM webhook URLs",
        "category": "integration",
        "description": "URLs CSV para entrega SIEM (fallback de CENTRAL_SIEM_WEBHOOK_URLS).",
    },
    "siem.hec_token": {
        "label": "SIEM HEC token",
        "category": "integration",
        "description": "Token Splunk HEC (fallback de CENTRAL_SIEM_HEC_TOKEN).",
    },
    "alert.webhook": {
        "label": "Ops alert webhook",
        "category": "integration",
        "description": "Webhook genérico de alertas (fallback de CENTRAL_ALERT_WEBHOOK_URL).",
    },
    "quota.webhook": {
        "label": "Quota alert webhook",
        "category": "integration",
        "description": "Webhook de quota (fallback de CENTRAL_QUOTA_WEBHOOK_URL).",
    },
}
