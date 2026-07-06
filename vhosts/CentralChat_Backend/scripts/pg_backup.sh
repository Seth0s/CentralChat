#!/usr/bin/env bash
# T5.4 — Postgres backup script (pg_dump)
# Usage: ./scripts/pg_backup.sh [--db-url URL]
# Default: reads MEMORY_DB_URL from orchestrator/.env or env var.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKUP_DIR="${BACKUP_DIR:-${SCRIPT_DIR}/../backups}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"

# Resolve DB URL
DB_URL="${1:-${MEMORY_DB_URL:-}}"
if [ -z "$DB_URL" ] && [ -f "${SCRIPT_DIR}/../.env" ]; then
    DB_URL=$(grep -E '^MEMORY_DB_URL=' "${SCRIPT_DIR}/../.env" | cut -d'=' -f2- | tr -d '"' | tr -d "'")
fi

if [ -z "$DB_URL" ]; then
    echo "ERROR: No database URL. Set MEMORY_DB_URL env var or pass --db-url."
    exit 1
fi

# Extract connection parts
# Format: postgresql://user:pass@host:port/dbname
PROTO="${DB_URL%%://*}"
REST="${DB_URL#*://}"
USER_PASS="${REST%%@*}"
HOST_DB="${REST#*@}"

USER="${USER_PASS%%:*}"
PASS="${USER_PASS#*:}"
HOST_PORT="${HOST_DB%%/*}"
DBNAME="${HOST_DB#*/}"
DBNAME="${DBNAME%%\?*}"

HOST="${HOST_PORT%%:*}"
PORT="${HOST_PORT#*:}"
[ "$PORT" = "$HOST" ] && PORT="5432"

mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date -u +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/central_memory_${TIMESTAMP}.sql.gz"

echo "[$(date -Iseconds)] Backup: $DBNAME@$HOST:$PORT → $BACKUP_FILE"

PGPASSWORD="$PASS" pg_dump \
    -h "$HOST" \
    -p "$PORT" \
    -U "$USER" \
    -d "$DBNAME" \
    --no-owner \
    --no-acl \
    | gzip > "$BACKUP_FILE"

echo "[$(date -Iseconds)] Backup complete: $(du -h "$BACKUP_FILE" | cut -f1)"

# Cleanup old backups
find "$BACKUP_DIR" -name 'central_memory_*.sql.gz' -mtime "+${RETENTION_DAYS}" -delete 2>/dev/null || true
echo "[$(date -Iseconds)] Cleaned backups older than ${RETENTION_DAYS} days. Current: $(ls "$BACKUP_DIR"/*.sql.gz 2>/dev/null | wc -l) files."
