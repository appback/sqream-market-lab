#!/usr/bin/env python3

from __future__ import annotations

import py_compile
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import paramiko

from report_notifier import notify


BASE_DIR = Path(__file__).resolve().parent
SQREAM_BIN = "/SQREAM/sqream-db-v4.4.0/bin/sqream"
SQREAM_HOST = "192.168.0.26"
SQREAM_PORT = "3108"
SQREAM_DATABASE = "master"
SQREAM_USERNAME = "sqream"
SQREAM_PASSWORD = "sqream"
SQREAM_OS_USERNAME = "sqream"
SQREAM_OS_PASSWORD = "sqream"
SQREAM_SERVICES = ("ingest", "analysis", "sqream")
SQREAM_PORTS = (3105, 3108, 5000, 5001, 5002, 5003, 5004)
SQREAM_WORKER_CONFIGS = {
    5000: "/SQREAM/sqream_config/sqream1_config.json",
    5001: "/SQREAM/sqream_config/sqream2_config.json",
    5002: "/SQREAM/sqream_config/sqream3_config.json",
    5003: "/SQREAM/sqream_config/sqream4_config.json",
    5004: "/SQREAM/sqream_config/sqream5_config.json",
}
SQREAM_START_LOG_DIR = "/SQREAM/sqream_logs"
CORE_PYTHON_FILES = (
    "report_notifier.py",
    "run_delayed_intraday_cycle.py",
    "sqream_runtime_events.py",
    "update_d1_vol5_absret10_candidates.py",
)


def check_port(port: int) -> None:
    with socket.create_connection((SQREAM_HOST, port), timeout=3):
        return


def is_port_open(port: int) -> bool:
    try:
        check_port(port)
        return True
    except Exception:
        return False


def start_missing_sqream_workers(ports: list[int]) -> None:
    worker_ports = [port for port in ports if port in SQREAM_WORKER_CONFIGS]
    if not worker_ports:
        return

    commands = []
    for port in worker_ports:
        config_path = SQREAM_WORKER_CONFIGS[port]
        log_name = Path(config_path).name.replace(".json", ".log")
        commands.append(
            f"nohup /SQREAM/sqream/bin/sqreamd -config {config_path} "
            f">> {SQREAM_START_LOG_DIR}/{log_name} 2>&1 &"
        )
    command = "mkdir -p /SQREAM/sqream_logs; " + " sleep 1; ".join(commands)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname="127.0.0.1",
        username=SQREAM_OS_USERNAME,
        password=SQREAM_OS_PASSWORD,
        timeout=10,
    )
    try:
        _stdin, stdout, stderr = client.exec_command(command, timeout=30)
        exit_code = stdout.channel.recv_exit_status()
        if exit_code != 0:
            err = stderr.read().decode(errors="replace").strip()
            out = stdout.read().decode(errors="replace").strip()
            raise RuntimeError(err or out or f"worker start exit={exit_code}")
    finally:
        client.close()


def wait_for_ports(ports: list[int], timeout_seconds: int = 30) -> list[int]:
    deadline = time.time() + timeout_seconds
    remaining = list(ports)
    while remaining and time.time() < deadline:
        remaining = [port for port in remaining if not is_port_open(port)]
        if remaining:
            time.sleep(1)
    return remaining


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

    missing_ports = [port for port in SQREAM_PORTS if not is_port_open(port)]
    if missing_ports:
        try:
            start_missing_sqream_workers(missing_ports)
            missing_ports = wait_for_ports(missing_ports)
        except Exception as exc:
            failures.append(f"sqream worker restart: {exc}")

    for port in SQREAM_PORTS:
        if not is_port_open(port):
            failures.append(f"port {port}: closed after restart attempt")

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
