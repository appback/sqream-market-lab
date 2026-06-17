#!/usr/bin/env bash
set -euo pipefail

cd /var/tmp/remoteagent/workspaces/cc6mog23
mkdir -p logs state staging

exec flock -n /tmp/d1_vol5_absret10_candidates.lock \
  /usr/local/bin/python3 update_d1_vol5_absret10_candidates.py \
    --symbols-file monitor_symbols_all.txt \
    --exclude-file monitor_excluded_symbols.txt \
    --limit 5068 \
    --batch-size 100 \
    --report \
    >> logs/d1_vol5_absret10_candidates.log 2>&1
