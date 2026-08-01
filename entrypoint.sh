#!/bin/bash
# Restore DB from litestream on cold start (if S3 creds are set + a backup exists),
# then launch litestream replication + uvicorn together.
set -e

mkdir -p /data

if [ -n "$LITESTREAM_ACCESS_KEY_ID" ] && [ ! -f "$DB_PATH" ]; then
  echo "No local DB found. Attempting restore from litestream…"
  litestream restore -if-replica-exists -v "$DB_PATH" || echo "No backup to restore."
fi

if [ -n "$LITESTREAM_ACCESS_KEY_ID" ]; then
  echo "Starting litestream + uvicorn together…"
  exec litestream replicate -exec "uvicorn backend.main:app --host 0.0.0.0 --port 8001"
else
  echo "LITESTREAM_ACCESS_KEY_ID not set — running uvicorn without backups."
  exec uvicorn backend.main:app --host 0.0.0.0 --port 8001
fi
