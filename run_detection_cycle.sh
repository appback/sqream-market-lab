#!/usr/bin/env bash
set -euo pipefail

cd /var/tmp/remoteagent/workspaces/cc6mog23
mkdir -p logs state

exec flock -n /tmp/sqream_detection_cycle.lock \
  /usr/local/bin/python3 sqream_runtime_events.py \
    --limit "${DETECTION_LIMIT:-50}" \
    >> logs/sqream_runtime_events.log 2>&1
