#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
from pathlib import Path


HOST = "192.168.0.26"
PORT = "3108"
DATABASE = "master"
USERNAME = "sqream"
PASSWORD = "sqream"
SERVICE = "sqream"
SQREAM_BIN = "/SQREAM/sqream-db-v4.4.0/bin/sqream"
OUTPUT_DIR = Path(__file__).resolve().parent / "output"
SQL_PATH = Path("/tmp/load_event_summary.sql")


def build_sql() -> str:
    rows = []
    for path in sorted(OUTPUT_DIR.glob("combined_*_summary.json")):
        payload = json.loads(path.read_text())
        rows.append((path.stem.replace("_summary", ""), payload))

    def num_or_null(value):
        return "null" if value is None else str(value)

    lines = [
        "create or replace table market_analysis.event_summary (",
        "  run_label text(64),",
        "  scanned int,",
        "  one_day_event_count int,",
        "  one_day_next_up_count int,",
        "  one_day_next_down_count int,",
        "  one_day_next_flat_count int,",
        "  one_day_next_up_probability float,",
        "  one_day_next_down_probability float,",
        "  one_day_next_flat_probability float,",
        "  crash_event_count int,",
        "  crash_rebound_count int,",
        "  crash_delisted_count int,",
        "  crash_unresolved_count int,",
        "  crash_rebound_probability float,",
        "  crash_delisted_probability float",
        ");",
    ]

    for label, d in rows:
        lines.append(
            "insert into market_analysis.event_summary values "
            f"('{label}', "
            f"{d['scanned']}, "
            f"{d['one_day_event_count']}, "
            f"{d['one_day_next_up_count']}, "
            f"{d['one_day_next_down_count']}, "
            f"{d.get('one_day_next_flat_count', 0)}, "
            f"{num_or_null(d.get('one_day_next_up_probability'))}, "
            f"{num_or_null(d.get('one_day_next_down_probability'))}, "
            f"{num_or_null(d.get('one_day_next_flat_probability'))}, "
            f"{d['crash_event_count']}, "
            f"{d['crash_rebound_count']}, "
            f"{d['crash_delisted_count']}, "
            f"{d['crash_unresolved_count']}, "
            f"{num_or_null(d.get('crash_rebound_probability'))}, "
            f"{num_or_null(d.get('crash_delisted_probability'))});"
        )

    lines.append(
        "select run_label, scanned, one_day_event_count, one_day_next_down_probability, "
        "crash_event_count from market_analysis.event_summary order by scanned;"
    )
    return "\n".join(lines)


def main() -> int:
    SQL_PATH.write_text(build_sql())
    cmd = [
        SQREAM_BIN,
        "sql",
        "--host",
        HOST,
        "--port",
        PORT,
        "--database",
        DATABASE,
        "--username",
        USERNAME,
        "--password",
        PASSWORD,
        "--clustered=true",
        "--service",
        SERVICE,
        "--file",
        str(SQL_PATH),
        "--results-only=true",
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    print(result.stdout.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
