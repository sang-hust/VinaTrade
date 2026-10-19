#!/bin/sh
# Build the Flutter web app and deploy it to the Railway service "vinatrade-web".
# Usage: app/deploy/deploy_web.sh [API_BASE_URL]
set -e
API="${1:-https://vinatrade-api-production.up.railway.app/api/v1}"
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
STAGE="$(mktemp -d)"
cd "$APP_DIR"
flutter build web --release --dart-define=API_BASE_URL="$API" --no-tree-shake-icons
cp deploy/web/Dockerfile deploy/web/nginx.conf.template "$STAGE"/
cp -R build/web "$STAGE/site"
# Run from backend/ (linked to the Railway project), upload only the staged folder.
cd "$APP_DIR/../backend"
railway up "$STAGE" --path-as-root --service vinatrade-web --detach
rm -rf "$STAGE"
