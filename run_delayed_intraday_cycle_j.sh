#!/usr/bin/env bash
set -euo pipefail

cd /var/tmp/remoteagent/workspaces/cc6mog23
DELAYED_INTRADAY_LIMIT=550 \
DELAYED_INTRADAY_OFFSET=4950 \
DELAYED_INTRADAY_PARTITION=j \
./run_delayed_intraday_cycle.sh
