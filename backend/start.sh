#!/bin/sh
# Production entrypoint (Railway): migrate → seed (idempotent) → serve.
set -e

if [ -n "$GCP_CREDENTIALS_JSON" ] && [ -z "$FIREBASE_CREDENTIALS" ]; then
  mkdir -p /tmp/secrets
  printf '%s' "$GCP_CREDENTIALS_JSON" > /tmp/secrets/firebase.json
  chmod 600 /tmp/secrets/firebase.json
  export FIREBASE_CREDENTIALS=/tmp/secrets/firebase.json
fi

alembic upgrade head
python -m app.seeds.seed || echo "seed skipped/failed (non-fatal)"

# First boot on an empty database: load the universe + history in the background so the API comes up immediately.
if [ "${BOOTSTRAP_DATA:-true}" = "true" ]; then
  python -m app.tasks.bootstrap &
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips "*"
