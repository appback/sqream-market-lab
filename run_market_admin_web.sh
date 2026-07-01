#!/usr/bin/env bash
set -euo pipefail

cd /var/tmp/remoteagent/workspaces/cc6mog23
mkdir -p logs state

HOST="${MARKET_ADMIN_HOST:-127.0.0.1}"
PORT="${MARKET_ADMIN_PORT:-18085}"

exec /usr/local/bin/python3 market_admin_web.py --host "${HOST}" --port "${PORT}"
