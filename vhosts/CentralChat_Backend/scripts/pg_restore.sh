#!/usr/bin/env bash
# D1.8 — Postgres restore from pg_dump gzip backup
# Usage: ./scripts/pg_restore.sh <backup.sql.gz> [--db-url URL]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKUP_FILE="${1:-}"

if [ -z "$BACKUP_FILE" ] || [ ! -f "$BACKUP_FILE" ]; then
    echo "ERROR: Usage: $0 <backup.sql.gz> [--db-url URL]"
    exit 1
fi

shift || true
DB_URL="${MEMORY_DB_URL:-}"
while [ $# -gt 0 ]; do
    case "$1" in
        --db-url) DB_URL="$2"; shift 2 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

if [ -z "$DB_URL" ] && [ -f "${SCRIPT_DIR}/../.env" ]; then
    DB_URL=$(grep -E '^MEMORY_DB_URL=' "${SCRIPT_DIR}/../.env" | cut -d'=' -f2- | tr -d '"' | tr -d "'")
fi

if [ -z "$DB_URL" ]; then
    echo "ERROR: Set MEMORY_DB_URL or pass --db-url."
    exit 1
fi

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

echo "[$(date -Iseconds)] Restore: $BACKUP_FILE → $DBNAME@$HOST:$PORT"
echo "WARNING: this overwrites objects in the target database."
read -r -p "Type RESTORE to continue: " CONFIRM
if [ "$CONFIRM" != "RESTORE" ]; then
    echo "Aborted."
    exit 1
fi

PGPASSWORD="$PASS" gunzip -c "$BACKUP_FILE" | psql -h "$HOST" -p "$PORT" -U "$USER" -d "$DBNAME" -v ON_ERROR_STOP=1
echo "[$(date -Iseconds)] Restore complete."
