#!/usr/bin/env sh
set -eu

export NODE_ENV="${NODE_ENV:-production}"

echo "Starting ${BOT_NAME:-RANDY SYSTEMS} in ${NODE_ENV} mode"
echo "Session directory is controlled by SESSION_DIR (default handled by the app)."

node scripts/patch-app-pairing.js
exec node src/index.js
