#!/usr/bin/env bash
set -euo pipefail

cd /var/tmp/remoteagent/workspaces/cc6mog23
mkdir -p logs state

/usr/local/bin/python3 sqream_runtime_events.py --market-open >> logs/sqream_runtime_events.log 2>&1
