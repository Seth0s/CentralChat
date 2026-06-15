#!/usr/bin/env bash
# Onda A — run e2e suite against docker-compose.dev.yml (+ optional e2e override)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="${ROOT}/vhosts/CentralChat_Backend"
CLI="${ROOT}/vhosts/CentralChat_CLI"
COMPOSE="docker compose -f ${ROOT}/docker-compose.dev.yml -f ${ROOT}/docker-compose.e2e.override.yml"

echo "==> Build CLI"
(cd "$CLI" && go build -o central ./cmd/central)
export E2E_CENTRAL_BIN="${CLI}/central"

echo "==> Stack (dev + e2e JWT required)"
cd "$ROOT"
$COMPOSE up -d postgres orchestrator
for i in $(seq 1 40); do
  if curl -sf http://127.0.0.1:8004/health >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
curl -sf http://127.0.0.1:8004/health/ready >/dev/null || true

echo "==> Seed e2e users"
docker exec central-orchestrator python scripts/seed_e2e_users.py

echo "==> Unit smoke (Onda A + B)"
cd "$BACKEND"
python -m pytest \
  tests/test_health_ready.py \
  tests/test_rbac_roles.py \
  tests/test_policy_engine.py \
  tests/test_policy_golden.py \
  tests/test_tenant_isolation_http.py \
  tests/test_auth_session_lifecycle.py \
  tests/test_config_failfast.py \
  tests/test_approval_idempotency.py \
  tests/test_repo_context_monorepo.py \
  tests/test_thinking_export_safety.py \
  tests/test_ast_context_frozen.py \
  -q

echo "==> E2E"
python -m pytest tests/e2e/ -m e2e -q --tb=short

echo "==> Done"
