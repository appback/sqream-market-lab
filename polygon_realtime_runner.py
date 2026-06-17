#!/usr/bin/env python3

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import websockets


HOST = "192.168.0.26"
PORT = "3108"
DATABASE = "master"
USERNAME = "sqream"
PASSWORD = "sqream"
SERVICE = "sqream"
SQREAM_BIN = "/SQREAM/sqream-db-v4.4.0/bin/sqream"
POLYGON_WS = "wss://socket.polygon.io/stocks"
BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = BASE_DIR / "output"
ALERT_LOG = OUT_DIR / "realtime_alerts.jsonl"


@dataclass
class WatchItem:
    symbol: str
    watch_type: str
    score: float
    prior_close: float
    daily_volume: int
    precursor_breakout_score: float | None
    bottom_watch_score: float | None
    price_vs_90d_high: float | None
    drawdown_from_252d_high: float | None


def sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def run_sqream_sql(sql: str, *, check: bool = True) -> str:
    sql_path = Path("/tmp/polygon_rt.sql")
    sql_path.write_text(sql)
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
        str(sql_path),
        "--results-only=true",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def ensure_realtime_tables() -> None:
    schema_sql = """
create or replace table market_rt.watchlist (
  symbol text(32),
  watch_type text(32),
  score float,
  inserted_at text(19)
);
create or replace table market_rt.intraday_bars (
  symbol text(32),
  bar_time text(19),
  open_price float,
  high_price float,
  low_price float,
  close_price float,
  volume_count int,
  vwap_price float,
  source text(32)
);
create or replace table market_rt.signal_events (
  symbol text(32),
  event_time text(19),
  signal_type text(32),
  signal_score float,
  price float,
  volume_count int,
  detail text(256)
);
"""
    run_sqream_sql(schema_sql)


def parse_watchlist(limit: int) -> list[WatchItem]:
    sql = f"""
select
  symbol,
  case
    when precursor_breakout_flag = 1 then 'precursor_breakout'
    when bottom_watch_flag = 1 then 'bottom_watch'
    else 'watch'
  end as watch_type,
  case
    when precursor_breakout_flag = 1 then precursor_breakout_score
    else bottom_watch_score
  end as score,
  close_price,
  volume_count,
  precursor_breakout_score,
  bottom_watch_score,
  price_vs_90d_high,
  drawdown_from_252d_high
from market_analysis.symbol_features
where precursor_breakout_flag = 1 or bottom_watch_flag = 1
order by score desc
limit {limit};
"""
    out = run_sqream_sql(sql, check=False)
    items: list[WatchItem] = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 9:
            continue
        def f(x: str):
            return None if x in {"", "\\N", "null"} else float(x)
        items.append(
            WatchItem(
                symbol=parts[0],
                watch_type=parts[1],
                score=float(parts[2]),
                prior_close=float(parts[3]),
                daily_volume=int(float(parts[4])),
                precursor_breakout_score=f(parts[5]),
                bottom_watch_score=f(parts[6]),
                price_vs_90d_high=f(parts[7]),
                drawdown_from_252d_high=f(parts[8]),
            )
        )
    return items


def refresh_watchlist_table(items: list[WatchItem]) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sql_lines = ["create or replace table market_rt.watchlist (symbol text(32), watch_type text(32), score float, inserted_at text(19));"]
    for item in items:
        sql_lines.append(
            "insert into market_rt.watchlist values ("
            f"{sql_str(item.symbol)}, {sql_str(item.watch_type)}, {item.score}, {sql_str(now)});"
        )
    run_sqream_sql("\n".join(sql_lines))


def bar_ts_to_text(ms: int | None) -> str:
    if ms is None:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def write_alert_file(payload: dict) -> None:
    ALERT_LOG.parent.mkdir(exist_ok=True)
    with ALERT_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def build_bar_insert_sql(event: dict) -> str:
    symbol = event.get("sym")
    bar_time = bar_ts_to_text(event.get("s"))
    open_price = event.get("o")
    high_price = event.get("h")
    low_price = event.get("l")
    close_price = event.get("c")
    volume_count = int(event.get("v", 0) or 0)
    vwap_price = event.get("vw")
    return (
        "insert into market_rt.intraday_bars values ("
        f"{sql_str(symbol)}, {sql_str(bar_time)}, {open_price}, {high_price}, {low_price}, "
        f"{close_price}, {volume_count}, {vwap_price if vwap_price is not None else 'null'}, 'polygon_am');"
    )


def evaluate_signal(item: WatchItem, event: dict) -> tuple[str, float, str] | None:
    close_price = float(event.get("c", 0.0) or 0.0)
    open_price = float(event.get("o", 0.0) or 0.0)
    volume_count = int(event.get("v", 0) or 0)
    if close_price <= 0 or open_price <= 0:
        return None

    intraday_from_prev_close = ((close_price / item.prior_close) - 1.0) * 100.0 if item.prior_close > 0 else 0.0
    bar_move = ((close_price / open_price) - 1.0) * 100.0
    volume_gate = volume_count >= max(20000, int(item.daily_volume * 0.015))

    if item.watch_type == "precursor_breakout":
        near_high = item.price_vs_90d_high is not None and item.price_vs_90d_high >= 0.9
        if volume_gate and intraday_from_prev_close >= 3.0 and intraday_from_prev_close < 25.0 and bar_move >= 1.5:
            score = float(item.precursor_breakout_score or item.score)
            detail = (
                f"precursor trigger: intraday={intraday_from_prev_close:.2f}% "
                f"bar_move={bar_move:.2f}% vol={volume_count} near_high={near_high}"
            )
            return ("precursor_trigger", score, detail)

    if item.watch_type == "bottom_watch":
        deep_drawdown = item.drawdown_from_252d_high is not None and item.drawdown_from_252d_high <= -0.7
        if volume_gate and bar_move >= 2.5 and intraday_from_prev_close <= 15.0 and deep_drawdown:
            score = float(item.bottom_watch_score or item.score)
            detail = (
                f"bottom trigger: intraday={intraday_from_prev_close:.2f}% "
                f"bar_move={bar_move:.2f}% vol={volume_count} deep_drawdown={item.drawdown_from_252d_high}"
            )
            return ("bottom_trigger", score, detail)
    return None


def build_signal_insert_sql(symbol: str, signal_type: str, score: float, price: float, volume_count: int, detail: str, event_time: str) -> str:
    return (
        "insert into market_rt.signal_events values ("
        f"{sql_str(symbol)}, {sql_str(event_time)}, {sql_str(signal_type)}, {score}, {price}, {volume_count}, {sql_str(detail[:250])});"
    )


async def run_realtime(api_key: str, watch_limit: int) -> None:
    ensure_realtime_tables()
    items = parse_watchlist(watch_limit)
    if not items:
        raise RuntimeError("watchlist is empty. build symbol_features with precursor/bottom flags first.")
    refresh_watchlist_table(items)
    item_map = {item.symbol: item for item in items}

    channels = ",".join(f"AM.{item.symbol}" for item in items)
    seen_signal_keys: set[tuple[str, str, str]] = set()

    async with websockets.connect(POLYGON_WS, ping_interval=20, ping_timeout=20) as ws:
        await ws.send(json.dumps({"action": "auth", "params": api_key}))
        auth_reply = await ws.recv()
        print(auth_reply)
        await ws.send(json.dumps({"action": "subscribe", "params": channels}))
        sub_reply = await ws.recv()
        print(sub_reply)

        while True:
            raw = await ws.recv()
            payload = json.loads(raw)
            if not isinstance(payload, list):
                continue

            bar_sql: list[str] = []
            signal_sql: list[str] = []
            for event in payload:
                if event.get("ev") != "AM":
                    continue
                symbol = event.get("sym")
                item = item_map.get(symbol)
                if item is None:
                    continue
                event_time = bar_ts_to_text(event.get("s"))
                bar_sql.append(build_bar_insert_sql(event))
                signal = evaluate_signal(item, event)
                if signal is None:
                    continue
                signal_type, score, detail = signal
                signal_key = (symbol, signal_type, event_time[:16])
                if signal_key in seen_signal_keys:
                    continue
                seen_signal_keys.add(signal_key)
                signal_sql.append(
                    build_signal_insert_sql(
                        symbol=symbol,
                        signal_type=signal_type,
                        score=score,
                        price=float(event.get("c", 0.0) or 0.0),
                        volume_count=int(event.get("v", 0) or 0),
                        detail=detail,
                        event_time=event_time,
                    )
                )
                write_alert_file(
                    {
                        "symbol": symbol,
                        "event_time": event_time,
                        "signal_type": signal_type,
                        "signal_score": score,
                        "price": event.get("c"),
                        "volume_count": event.get("v"),
                        "detail": detail,
                    }
                )
                print(json.dumps({"symbol": symbol, "signal_type": signal_type, "event_time": event_time, "detail": detail}, ensure_ascii=False))

            if bar_sql:
                try:
                    run_sqream_sql("\n".join(bar_sql), check=False)
                except Exception:
                    pass
            if signal_sql:
                try:
                    run_sqream_sql("\n".join(signal_sql), check=False)
                except Exception:
                    pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--watch-limit", type=int, default=100)
    parser.add_argument("--api-key", default=os.getenv("POLYGON_API_KEY"))
    args = parser.parse_args()

    if not args.api_key:
        raise SystemExit("POLYGON_API_KEY is required")

    asyncio.run(run_realtime(args.api_key, args.watch_limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
