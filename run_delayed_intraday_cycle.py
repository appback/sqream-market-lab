#!/usr/bin/env python3

from __future__ import annotations

import argparse
import fcntl
import json
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import paramiko

from collect_delayed_intraday_bars import collect, load_symbols, write_parquet
from report_notifier import notify


BASE_DIR = Path(__file__).resolve().parent
STAGING_DIR = BASE_DIR / "staging"
LOG_DIR = BASE_DIR / "logs"
NY_TZ = ZoneInfo("America/New_York")

SQREAM_HOST = "192.168.0.26"
SQREAM_PORT = "3108"
SQREAM_DATABASE = "master"
SQREAM_USERNAME = "sqream"
SQREAM_PASSWORD = "sqream"
SQREAM_SERVICE = os.environ.get("SQREAM_SERVICE", "sqream")
SQREAM_BIN = "/SQREAM/sqream-db-v4.4.0/bin/sqream"
REMOTE_STAGE_DIR = "/data/cluster/sqream_stage"
SQREAM_DDL_LOCK = "/tmp/sqream_ddl_analysis.lock"


def sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def run_sqream_file(sql_path: Path) -> str:
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
        SQREAM_SERVICE,
        "--file",
        str(sql_path),
        "--results-only=true",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def run_sqream_sql(sql: str, *, check: bool = True) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".sql", prefix="run_delayed_intraday_cycle_", delete=False) as f:
        f.write(sql)
        sql_path = Path(f.name)
    try:
        return run_sqream_file(sql_path)
    except RuntimeError:
        if check:
            raise
        return ""
    finally:
        sql_path.unlink(missing_ok=True)


def record_report(event_type: str, text: str) -> None:
    def persist_report_event(created_at: str, persisted_event_type: str, persisted_text: str) -> None:
        run_sqream_sql("create schema market_rt;", check=False)
        exists = run_sqream_sql("select count(*) from market_rt.report_events;", check=False)
        if not exists.strip():
            run_sqream_sql(
                """
create table market_rt.report_events (
  created_at text(32),
  event_type text(32),
  message text(512)
);
"""
            )
        run_sqream_sql(
            "insert into market_rt.report_events values ("
            f"{sql_str(created_at)}, {sql_str(persisted_event_type)}, {sql_str(persisted_text)});",
            check=False,
        )

    notify(event_type, text, persist_report=persist_report_event, print_text=False)


def ensure_table_exists(table_name: str, ddl: str) -> None:
    exists = run_sqream_sql(f"select count(*) from {table_name};", check=False)
    if not exists.strip():
        run_sqream_sql(ddl)


def ensure_sqream_objects() -> None:
    run_sqream_sql("create schema market_rt;", check=False)
    raw_ddl = """
create table market_rt.delayed_intraday_bars_raw (
  symbol text(32),
  bar_time text(32),
  open_price float,
  high_price float,
  low_price float,
  close_price float,
  volume_count int,
  source text(32),
  collected_at text(32)
);
"""
    latest_ddl = """
create table {table_name} (
  symbol text(32),
  bar_time text(32),
  open_price float,
  high_price float,
  low_price float,
  close_price float,
  volume_count int,
  source text(32),
  collected_at text(32)
);
"""
    ensure_table_exists("market_rt.delayed_intraday_bars_raw", raw_ddl)
    for partition in ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"]:
        ensure_table_exists(
            f"market_rt.delayed_intraday_bars_latest_{partition}",
            latest_ddl.format(table_name=f"market_rt.delayed_intraday_bars_latest_{partition}"),
        )
    ensure_table_exists(
        "market_rt.delayed_intraday_bars_latest",
        latest_ddl.format(table_name="market_rt.delayed_intraday_bars_latest"),
    )


def run_analysis_cycle() -> int:
    started_at = time.monotonic()
    lock_wait_started_at = time.monotonic()
    with open(SQREAM_DDL_LOCK, "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        lock_acquired_at = time.monotonic()
        ensure_sqream_objects()
        ensured_at = time.monotonic()
        analysis_out = run_sqream_file(BASE_DIR / "sqream_intraday_analysis.sql")
        analyzed_at = time.monotonic()
        regime_out = run_sqream_file(BASE_DIR / "sqream_market_regime.sql")
        regime_at = time.monotonic()
        time_strategy_out = run_sqream_file(BASE_DIR / "sqream_time_strategy_profile.sql")
        time_strategy_at = time.monotonic()
        sideways_out = run_sqream_file(BASE_DIR / "sqream_sideways_vwap_reversion.sql")
        sideways_at = time.monotonic()
        strategy_out = run_sqream_file(BASE_DIR / "sqream_strategy_engine.sql")
        strategy_at = time.monotonic()

    result = {
        "mode": "analyze_only",
        "analysis_result": analysis_out.splitlines(),
        "regime_result": regime_out.splitlines(),
        "time_strategy_result": time_strategy_out.splitlines(),
        "sideways_result": sideways_out.splitlines(),
        "strategy_result": strategy_out.splitlines(),
        "timing_seconds": {
            "sqream_lock_wait": round(lock_acquired_at - lock_wait_started_at, 3),
            "sqream_ensure": round(ensured_at - lock_acquired_at, 3),
            "sqream_analysis": round(analyzed_at - ensured_at, 3),
            "sqream_regime": round(regime_at - analyzed_at, 3),
            "sqream_time_strategy": round(time_strategy_at - regime_at, 3),
            "sqream_sideways": round(sideways_at - time_strategy_at, 3),
            "sqream_strategy": round(strategy_at - sideways_at, 3),
            "total": round(strategy_at - started_at, 3),
        },
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0


def upload_file(local_path: Path, remote_path: str) -> None:
    transport = paramiko.Transport((SQREAM_HOST, 22))
    try:
        transport.connect(username=SQREAM_USERNAME, password=SQREAM_PASSWORD)
        sftp = paramiko.SFTPClient.from_transport(transport)
        try:
            sftp.mkdir(REMOTE_STAGE_DIR)
        except OSError:
            pass
        sftp.put(str(local_path), remote_path)
        sftp.close()
    finally:
        transport.close()


def render_load_sql(remote_parquet_path: str, partition: str) -> Path:
    template = (BASE_DIR / "sqream_intraday_bars_load_template.sql").read_text()
    rendered = (
        template.replace("{{INTRADAY_BARS_PARQUET_PATH}}", remote_parquet_path)
        .replace("{{PARTITION}}", partition)
    )
    with tempfile.NamedTemporaryFile("w", suffix=".sql", prefix=f"load_delayed_intraday_bars_{partition}_", delete=False) as f:
        f.write(rendered)
        return Path(f.name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols-file", type=Path, default=BASE_DIR / "monitor_symbols_all.txt")
    parser.add_argument("--exclude-file", type=Path, default=BASE_DIR / "monitor_excluded_symbols.txt")
    parser.add_argument("--limit", type=int, default=5068)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--partition-index", type=int, default=0)
    parser.add_argument("--partition-count", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--interval", default="1m")
    parser.add_argument("--partition", choices=["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"], default="a")
    parser.add_argument("--load-only", action="store_true")
    parser.add_argument("--analyze-only", action="store_true")
    args = parser.parse_args()

    if args.analyze_only:
        return run_analysis_cycle()

    STAGING_DIR.mkdir(exist_ok=True)
    LOG_DIR.mkdir(exist_ok=True)

    stamp = datetime.now(NY_TZ).strftime("%Y%m%d_%H%M%S")
    local_path = STAGING_DIR / f"delayed_intraday_bars_{args.partition}_{stamp}.parquet"
    remote_path = f"{REMOTE_STAGE_DIR}/{local_path.name}"

    symbols = load_symbols(
        args.symbols_file,
        args.limit,
        args.offset,
        args.exclude_file,
        args.partition_index,
        args.partition_count,
    )
    started_at = time.monotonic()
    rows = collect(symbols, args.interval, args.batch_size)
    collected_at = time.monotonic()
    if not symbols:
        result = {
            "mode": "load_only" if args.load_only else "collect",
            "symbols": 0,
            "exclude_file": str(args.exclude_file),
            "offset": args.offset,
            "partition": args.partition,
            "partition_index": args.partition_index,
            "partition_count": args.partition_count,
            "bars": 0,
            "skipped": "empty_partition",
            "timing_seconds": {
                "collect": round(collected_at - started_at, 3),
                "total": round(time.monotonic() - started_at, 3),
            },
        }
        print(json.dumps(result, ensure_ascii=False))
        return 0
    write_parquet(rows, local_path)
    written_at = time.monotonic()
    upload_file(local_path, remote_path)
    uploaded_at = time.monotonic()

    lock_wait_started_at = time.monotonic()
    with open(SQREAM_DDL_LOCK, "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        lock_acquired_at = time.monotonic()
        ensure_sqream_objects()
        load_out = run_sqream_file(render_load_sql(remote_path, args.partition))
        loaded_at = time.monotonic()
        if args.load_only:
            analysis_out = ""
            regime_out = ""
            time_strategy_out = ""
            sideways_out = ""
            strategy_out = ""
            analyzed_at = loaded_at
            regime_at = loaded_at
            time_strategy_at = loaded_at
            sideways_at = loaded_at
            strategy_at = loaded_at
        else:
            analysis_out = run_sqream_file(BASE_DIR / "sqream_intraday_analysis.sql")
            analyzed_at = time.monotonic()
            regime_out = run_sqream_file(BASE_DIR / "sqream_market_regime.sql")
            regime_at = time.monotonic()
            time_strategy_out = run_sqream_file(BASE_DIR / "sqream_time_strategy_profile.sql")
            time_strategy_at = time.monotonic()
            sideways_out = run_sqream_file(BASE_DIR / "sqream_sideways_vwap_reversion.sql")
            sideways_at = time.monotonic()
            strategy_out = run_sqream_file(BASE_DIR / "sqream_strategy_engine.sql")
            strategy_at = time.monotonic()

    result = {
        "mode": "load_only" if args.load_only else "load_and_analyze",
        "symbols": len(symbols),
        "exclude_file": str(args.exclude_file),
        "offset": args.offset,
        "partition": args.partition,
        "partition_index": args.partition_index,
        "partition_count": args.partition_count,
        "bars": len(rows),
        "local_parquet": str(local_path),
        "remote_parquet": remote_path,
        "load_result": load_out.splitlines(),
        "analysis_result": analysis_out.splitlines(),
        "regime_result": regime_out.splitlines(),
        "time_strategy_result": time_strategy_out.splitlines(),
        "sideways_result": sideways_out.splitlines(),
        "strategy_result": strategy_out.splitlines(),
        "timing_seconds": {
            "collect": round(collected_at - started_at, 3),
            "write_parquet": round(written_at - collected_at, 3),
            "upload": round(uploaded_at - written_at, 3),
            "sqream_lock_wait": round(lock_acquired_at - lock_wait_started_at, 3),
            "sqream_load": round(loaded_at - lock_acquired_at, 3),
            "sqream_analysis": round(analyzed_at - loaded_at, 3),
            "sqream_regime": round(regime_at - analyzed_at, 3),
            "sqream_time_strategy": round(time_strategy_at - regime_at, 3),
            "sqream_sideways": round(sideways_at - time_strategy_at, 3),
            "sqream_strategy": round(strategy_at - sideways_at, 3),
            "total": round(strategy_at - started_at, 3),
        },
    }
    timing = result["timing_seconds"]
    if timing["collect"] >= 120.0 or timing["total"] >= 240.0:
        record_report(
            "병목보고",
            (
                f"[병목보고] partition={args.partition} total={timing['total']:.1f}s "
                f"collect={timing['collect']:.1f}s sqream_load={timing['sqream_load']:.1f}s "
                "개선=5개 병렬 파티션 유지, 무응답/상폐성 심볼 제외목록 구축, "
                "다음 단계=유효심볼 캐시로 수집대상 축소"
            ),
        )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        record_report(
            "장중 에러",
            f"[장중 에러] context=run_delayed_intraday_cycle error={str(exc).strip().splitlines()[0] if str(exc).strip() else exc.__class__.__name__}",
        )
        raise
