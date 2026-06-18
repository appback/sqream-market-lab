#!/usr/bin/env python3

from __future__ import annotations

import py_compile
import socket
import subprocess
import tempfile
from pathlib import Path

from report_notifier import notify


BASE_DIR = Path(__file__).resolve().parent
SQREAM_BIN = "/SQREAM/sqream-db-v4.4.0/bin/sqream"
SQREAM_HOST = "192.168.0.26"
SQREAM_PORT = "3108"
SQREAM_DATABASE = "master"
SQREAM_USERNAME = "sqream"
SQREAM_PASSWORD = "sqream"
SQREAM_SERVICES = ("ingest", "analysis", "sqream")
SQREAM_PORTS = (3105, 3108, 5000, 5001, 5002, 5003, 5004)
CORE_PYTHON_FILES = (
    "report_notifier.py",
    "run_delayed_intraday_cycle.py",
    "sqream_runtime_events.py",
    "update_d1_vol5_absret10_candidates.py",
)


def check_port(port: int) -> None:
    with socket.create_connection((SQREAM_HOST, port), timeout=3):
        return


def run_sqream_select(service: str) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".sql", prefix="market_preflight_", delete=False) as f:
        f.write("select 1;\n")
        sql_path = Path(f.name)
    try:
        cmd = [
            SQREAM_BIN,
            "sql",
            "--host",
            SQREAM_HOST,
            "--port",
            SQREAM_PORT,
            "--database",
            SQREAM_DATABASE,
            "--username",
            SQREAM_USERNAME,
            "--password",
            SQREAM_PASSWORD,
            "--clustered=true",
            "--service",
            service,
            "--file",
            str(sql_path),
            "--results-only=true",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        return result.stdout.strip()
    finally:
        sql_path.unlink(missing_ok=True)


def main() -> int:
    failures: list[str] = []

    for rel_path in CORE_PYTHON_FILES:
        path = BASE_DIR / rel_path
        try:
            py_compile.compile(str(path), doraise=True)
        except Exception as exc:
            failures.append(f"py_compile {rel_path}: {exc}")

    for port in SQREAM_PORTS:
        try:
            check_port(port)
        except Exception as exc:
            failures.append(f"port {port}: {exc}")

    for service in SQREAM_SERVICES:
        try:
            result = run_sqream_select(service)
            if result.strip() != "1":
                failures.append(f"service {service}: unexpected result {result!r}")
        except Exception as exc:
            failures.append(f"service {service}: {exc}")

    if failures:
        notify(
            "장전 점검 실패",
            "[장전 점검 실패] " + " | ".join(failures[:6]),
            {"failures": failures},
        )
        return 1

    notify(
        "장전 점검",
        "[장전 점검] OK: python imports, SQream ports, ingest/analysis/sqream queries",
        {
            "python_files": list(CORE_PYTHON_FILES),
            "ports": list(SQREAM_PORTS),
            "services": list(SQREAM_SERVICES),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
