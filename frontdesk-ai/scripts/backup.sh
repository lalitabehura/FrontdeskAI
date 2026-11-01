#!/usr/bin/env bash
# Nightly encrypted database backup. Add to crontab:  0 3 * * * /opt/frontdesk-ai/scripts/backup.sh
# Requires BACKUP_PASSPHRASE in the environment (store it in your password manager, NOT on the server only).
set -euo pipefail
cd "$(dirname "$0")/.."
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p backups
docker compose exec -T db pg_dump -U frontdesk -Fc frontdesk \
  | gpg --batch --yes --symmetric --cipher-algo AES256 --passphrase "${BACKUP_PASSPHRASE:?set BACKUP_PASSPHRASE}" \
  > "backups/frontdesk-$STAMP.dump.gpg"
find backups -name 'frontdesk-*.dump.gpg' -mtime +14 -delete
echo "Backup written: backups/frontdesk-$STAMP.dump.gpg  (copy it off-server, e.g. rclone to S3/Backblaze)"
