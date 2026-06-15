#!/usr/bin/env bash
# Subir stack staging completa (Compose) — dev + e2e JWT + flags staging + ops.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
COMPOSE=(docker compose
  -f docker-compose.dev.yml
  -f docker-compose.e2e.override.yml
  -f docker-compose.staging.override.yml
  -f docker-compose.staging.ops.override.yml
)
echo "[staging] Building / starting..."
"${COMPOSE[@]}" up -d --build
echo "[staging] Waiting for /health/ready..."
for i in $(seq 1 60); do
  if curl -sf http://127.0.0.1:8004/health/ready >/dev/null 2>&1; then
    echo "[staging] Ready."
    curl -s http://127.0.0.1:8004/health/ready | head -c 400
    echo
    echo "[staging] Prometheus: http://127.0.0.1:9090"
    echo "[staging] Web UI:       http://127.0.0.1:5174"
    echo "[staging] Alert sink:   docker compose ... logs -f alert-webhook-sink"
    exit 0
  fi
  sleep 2
done
echo "[staging] TIMEOUT — check: ${COMPOSE[*]} logs orchestrator"
exit 1
