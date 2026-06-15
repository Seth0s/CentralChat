#!/usr/bin/env bash
# C1.1 — smoke OIDC/Keycloak (stack com profile oidc + override)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

KC_URL="${KC_URL:-http://127.0.0.1:8180}"
API_URL="${API_URL:-http://127.0.0.1:8004}"
MAX_WAIT="${MAX_WAIT:-120}"

echo "==> Aguardar Keycloak ($KC_URL)…"
deadline=$((SECONDS + MAX_WAIT))
until curl -sf "$KC_URL/realms/central/.well-known/openid-configuration" >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    echo "Keycloak não respondeu em ${MAX_WAIT}s" >&2
    exit 1
  fi
  sleep 2
done
echo "    Keycloak OK"

echo "==> Aguardar orchestrator ($API_URL)…"
until curl -sf "$API_URL/health/ready" >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    echo "Orchestrator não respondeu em ${MAX_WAIT}s" >&2
    exit 1
  fi
  sleep 2
done
echo "    Orchestrator OK"

echo "==> public-config OIDC"
body="$(curl -sf "$API_URL/auth/public-config")"
echo "$body" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d.get('auth_oidc_enabled'), 'auth_oidc_enabled=false'
oidc = d.get('oidc') or {}
assert oidc.get('authorization_endpoint'), 'missing authorization_endpoint'
assert oidc.get('client_id'), 'missing client_id'
print('    auth_oidc_enabled=true, client_id=', oidc.get('client_id'))
"

echo "==> smoke OIDC concluído"
