#!/bin/bash
# Backup PostgreSQL database to .local/db-checkpoints/
# Creates timestamped backup file: scan_YYYYMMDD_HHMMSS.dump

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="${PROJECT_ROOT}/.local/db-checkpoints"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/scan_${TIMESTAMP}.dump"

# Ensure backup directory exists
mkdir -p "$BACKUP_DIR"

echo "Backing up learning_scans database to: $BACKUP_FILE"

# Use custom format (-Fc) so restore can use pg_restore reliably.
cd "$PROJECT_ROOT"
podman-compose exec -T postgres pg_dump -U learning_user -d learning_scans -Fc > "$BACKUP_FILE"

if [ -f "$BACKUP_FILE" ]; then
    SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    echo "✓ Backup completed successfully ($SIZE): $BACKUP_FILE"
else
    echo "✗ Backup failed: file not created"
    exit 1
fi
