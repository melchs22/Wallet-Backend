#!/usr/bin/env bash
set -euo pipefail

# Export application rows in a database-independent format before switching DATABASE_URL.
BACKUP_DIR="${1:-backups/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$BACKUP_DIR"
./.venv/bin/python manage.py dumpdata --natural-foreign --natural-primary --exclude auth.permission --exclude contenttypes --indent 2 > "$BACKUP_DIR/wallet-data.json"
cp db.sqlite3 "$BACKUP_DIR/db.sqlite3"
printf 'Exported Django data to %s/wallet-data.json\n' "$BACKUP_DIR"
