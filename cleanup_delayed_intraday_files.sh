#!/usr/bin/env bash
set -euo pipefail

cd /var/tmp/remoteagent/workspaces/cc6mog23
mkdir -p logs

before_count="$(find staging -type f \( -name '*.csv' -o -name 'delayed_intraday_bars_*.parquet' \) | wc -l)"
before_size="$(find staging -type f \( -name '*.csv' -o -name 'delayed_intraday_bars_*.parquet' \) -printf '%s\n' | awk '{s+=$1} END {printf "%.2f MB", s/1024/1024}')"

# CSV is not allowed in the ingestion staging path. Parquet is kept for 24h as a recovery buffer after DB load.
find staging -type f -name '*.csv' -delete
find staging -type f -name 'delayed_intraday_bars_*.parquet' -mtime +1 -delete

after_count="$(find staging -type f \( -name '*.csv' -o -name 'delayed_intraday_bars_*.parquet' \) | wc -l)"
after_size="$(find staging -type f \( -name '*.csv' -o -name 'delayed_intraday_bars_*.parquet' \) -printf '%s\n' | awk '{s+=$1} END {printf "%.2f MB", s/1024/1024}')"

echo "$(date -Is) before_count=${before_count} before_size=${before_size} after_count=${after_count} after_size=${after_size}" >> logs/cleanup_delayed_intraday_files.log
