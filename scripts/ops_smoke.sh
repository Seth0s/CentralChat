#!/usr/bin/env bash
# Smoke: métricas + alert webhook no staging Compose.
set -euo pipefail
echo "[ops-smoke] /metrics sample..."
curl -sf http://127.0.0.1:8004/metrics | rg -m 3 "central_streams_active|central_approvals_total|central_policy" || true

echo "[ops-smoke] Trigger test alert inside orchestrator container..."
docker exec central-orchestrator python -c "from app.shared.alerting import send_ops_alert; import time; send_ops_alert(action='ops.smoke', text='staging ops smoke test', metadata={'source': 'ops_smoke.sh'}); time.sleep(2)"

echo "[ops-smoke] Last webhook sink lines (if container running):"
docker logs central-alert-webhook-sink 2>/dev/null | tail -3 || echo "(sink not running — run scripts/staging_up.sh)"
