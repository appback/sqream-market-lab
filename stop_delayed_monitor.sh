#!/usr/bin/env bash
set -euo pipefail

cd /var/tmp/remoteagent/workspaces/cc6mog23

pkill -f "run_delayed_intraday_cycle.py" 2>/dev/null || true
echo "stopped_delayed_intraday_cycle_if_running"
