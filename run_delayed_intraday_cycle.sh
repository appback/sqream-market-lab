#!/usr/bin/env bash
set -euo pipefail

cd /var/tmp/remoteagent/workspaces/cc6mog23
mkdir -p logs staging

extra_args=()
if [[ "${DELAYED_INTRADAY_LOAD_ONLY:-0}" == "1" ]]; then
  extra_args+=(--load-only)
fi

exec flock -n "/tmp/delayed_intraday_cycle_${DELAYED_INTRADAY_PARTITION:-a}.lock" \
  /usr/local/bin/python3 run_delayed_intraday_cycle.py \
    --symbols-file monitor_symbols_all.txt \
    --exclude-file "${DELAYED_INTRADAY_EXCLUDE_FILE:-monitor_excluded_symbols.txt}" \
    --limit "${DELAYED_INTRADAY_LIMIT:-5068}" \
    --offset "${DELAYED_INTRADAY_OFFSET:-0}" \
    --partition-index "${DELAYED_INTRADAY_PARTITION_INDEX:-0}" \
    --partition-count "${DELAYED_INTRADAY_PARTITION_COUNT:-1}" \
    --batch-size "${DELAYED_INTRADAY_BATCH_SIZE:-50}" \
    --partition "${DELAYED_INTRADAY_PARTITION:-a}" \
    "${extra_args[@]}" \
    >> logs/delayed_intraday_cycle.log 2>&1
