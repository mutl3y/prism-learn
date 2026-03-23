#!/bin/bash
# Restore PostgreSQL database from .local/db-checkpoints/
# Usage: ./restore_database.sh <backup_filename>
# Example: ./restore_database.sh scan_20260315_191411.dump

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="${PROJECT_ROOT}/.local/db-checkpoints"

# Validate input
if [ $# -eq 0 ]; then
    echo "Usage: $0 <backup_filename>"
    echo ""
    echo "Available backups:"
    ls -1 "$BACKUP_DIR"/scan_*.dump 2>/dev/null | xargs -I {} basename {} || echo "  (no backups found)"
    exit 1
fi

BACKUP_FILE="${BACKUP_DIR}/$1"

# Check if backup file exists
if [ ! -f "$BACKUP_FILE" ]; then
    echo "✗ Backup file not found: $BACKUP_FILE"
    echo ""
    echo "Available backups:"
    ls -1 "$BACKUP_DIR"/scan_*.dump 2>/dev/null | xargs -I {} basename {}
    exit 1
fi

SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "Restoring database from: $BACKUP_FILE ($SIZE)"
echo ""
echo "WARNING: This will overwrite the current learning_scans database."
echo "Press Ctrl+C to cancel, or press Enter to continue..."
read -r

cd "$PROJECT_ROOT"

# Get postgres container name
POSTGRES_CONTAINER=$(podman-compose ps --format "{{.Names}}" | grep postgres)
if [ -z "$POSTGRES_CONTAINER" ]; then
    echo "✗ PostgreSQL container not found (is podman-compose up running?)"
    exit 1
fi

# Backup current state before restore
CURRENT_TIMESTAMP=$(date +%Y%m%d_%H%M%S)
SAFETY_BACKUP="${BACKUP_DIR}/pre_restore_${CURRENT_TIMESTAMP}.dump"
echo "Creating safety backup: $SAFETY_BACKUP"
podman-compose exec -T postgres pg_dump -U learning_user -d learning_scans -Fc > "$SAFETY_BACKUP"

# Reset schema first to avoid dependency drop-order conflicts during restore.
echo "Clearing existing learning schema..."
podman-compose exec -T postgres psql -U learning_user -d learning_scans -c "DROP SCHEMA IF EXISTS learning CASCADE;"

# Restore from backup (custom-format preferred, plain SQL fallback).
echo "Restoring..."
CONTAINER_BACKUP_PATH="/tmp/$(basename "$BACKUP_FILE")"
podman cp "$BACKUP_FILE" "${POSTGRES_CONTAINER}:${CONTAINER_BACKUP_PATH}"
if podman exec "$POSTGRES_CONTAINER" pg_restore -l "$CONTAINER_BACKUP_PATH" >/dev/null 2>&1; then
    podman exec "$POSTGRES_CONTAINER" pg_restore -U learning_user -d learning_scans "$CONTAINER_BACKUP_PATH"
else
    podman exec -i "$POSTGRES_CONTAINER" psql -U learning_user -d learning_scans < "$BACKUP_FILE"
fi
podman exec "$POSTGRES_CONTAINER" rm "$CONTAINER_BACKUP_PATH"

echo "✓ Restore completed successfully"
echo "  Database: learning_scans"
echo "  Safety backup: $SAFETY_BACKUP"
