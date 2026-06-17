#!/usr/bin/env bash
set -euo pipefail

cd /var/tmp/remoteagent/workspaces/cc6mog23
mkdir -p logs

exec flock -n "/tmp/sqream_analysis_cycle.lock" \
  env SQREAM_SERVICE=analysis /usr/local/bin/python3 run_delayed_intraday_cycle.py \
    --analyze-only \
    >> logs/sqream_analysis_cycle.log 2>&1
