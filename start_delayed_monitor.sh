#!/usr/bin/env bash
set -euo pipefail

cd /var/tmp/remoteagent/workspaces/cc6mog23
mkdir -p logs state output

exec ./run_delayed_intraday_cycle.sh
