#!/usr/bin/env bash
set -euo pipefail

cd /var/tmp/remoteagent/workspaces/cc6mog23
mkdir -p logs state

/usr/local/bin/python3 market_preflight_check.py >> logs/market_preflight_check.log 2>&1
