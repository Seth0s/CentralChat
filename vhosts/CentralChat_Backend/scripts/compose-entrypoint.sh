#!/bin/sh
# Runs DB migrations (idempotent) before the main process. Used by Compose / VPS entrypoint.
# Advisory lock in run_migrations.py prevents races when multiple replicas start together.
set -eu

if [ "${MEMORY_ENABLED:-1}" != "0" ] && [ -n "${MEMORY_DB_URL:-}" ]; then
  # Some migrations (e.g. 007_user_scoped_config.sql) depend on auth_users/auth_clients.
  # The app creates those lazily; ensure them here so migrations don't fail mid-run.
  if [ "${AUTH_LOGIN_ENABLED:-1}" != "0" ]; then
    echo "compose-entrypoint: ensuring auth schema..."
    python -c "from app.auth import ensure_auth_schema; ensure_auth_schema(); print('auth schema ok')"
  fi

  echo "compose-entrypoint: applying migrations..."
  python scripts/run_migrations.py
fi

if [ "${CENTRAL_DEV_SEED:-0}" = "1" ]; then
  echo "compose-entrypoint: bootstrap admin (root@central.local if auth_users empty)..."
  python scripts/seed_bootstrap_admin.py || true
  echo "compose-entrypoint: dev seed (e2e users)..."
  python scripts/seed_e2e_users.py || true
fi

exec "$@"
