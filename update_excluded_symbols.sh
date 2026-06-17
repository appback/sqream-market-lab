#!/usr/bin/env bash
set -euo pipefail

cd /var/tmp/remoteagent/workspaces/cc6mog23
/usr/local/bin/python3 update_excluded_symbols.py >> logs/update_excluded_symbols.log 2>&1
