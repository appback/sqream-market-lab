#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests


HOST = "192.168.0.26"
PORT = "3108"
DATABASE = "master"
USERNAME = "sqream"
PASSWORD = "sqream"
SERVICE = "sqream"
SQREAM_BIN = "/SQREAM/sqream-db-v4.4.0/bin/sqream"


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
    sql_path = Path("/tmp/polygon_poll.sql")
    sql_path.write_text(sql)
    cmd = [
        SQREAM_BIN, "sql",
        "--host", HOST, "--port", PORT, "--database", DATABASE,
        "--username", USERNAME, "--password", PASSWORD,
        "--clustered=true", "--service", SERVICE,
        "--file", str(sql_path), "--results-only=true",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def parse_watchlist(limit: int) -> list[WatchItem]:
    sql = f"""
select
  symbol,
  case when precursor_breakout_flag = 1 then 'precursor_breakout' else 'bottom_watch' end as watch_type,
  case when precursor_breakout_flag = 1 then precursor_breakout_score else bottom_watch_score end as score,
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


def ensure_rt_tables() -> None:
    sql = """
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
    run_sqream_sql(sql)


def refresh_watchlist_table(items: list[WatchItem]) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = ["create or replace table market_rt.watchlist (symbol text(32), watch_type text(32), score float, inserted_at text(19));"]
    for item in items:
        lines.append(
            f"insert into market_rt.watchlist values ({sql_str(item.symbol)}, {sql_str(item.watch_type)}, {item.score}, {sql_str(now)});"
        )
    run_sqream_sql("\n".join(lines))


def evaluate_signal(item: WatchItem, price: float, day_change_pct: float, volume: int) -> tuple[str, float, str] | None:
    if item.watch_type == "precursor_breakout":
        if day_change_pct >= 3.0 and day_change_pct < 25.0 and volume >= max(20000, int(item.daily_volume * 0.015)):
            score = float(item.precursor_breakout_score or item.score)
            return ("precursor_trigger", score, f"poll trigger day_change={day_change_pct:.2f}% vol={volume}")
    if item.watch_type == "bottom_watch":
        deep_drawdown = item.drawdown_from_252d_high is not None and item.drawdown_from_252d_high <= -0.7
        if deep_drawdown and day_change_pct >= 2.5 and day_change_pct < 15.0 and volume >= max(10000, int(item.daily_volume * 0.01)):
            score = float(item.bottom_watch_score or item.score)
            return ("bottom_trigger", score, f"poll trigger day_change={day_change_pct:.2f}% vol={volume}")
    return None


def insert_bar_and_signal(symbol: str, price: float, volume: int, signal: tuple[str, float, str] | None) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "insert into market_rt.intraday_bars values ("
        f"{sql_str(symbol)}, {sql_str(now)}, {price}, {price}, {price}, {price}, {volume}, null, 'polygon_rest');"
    ]
    if signal is not None:
        signal_type, score, detail = signal
        lines.append(
            "insert into market_rt.signal_events values ("
            f"{sql_str(symbol)}, {sql_str(now)}, {sql_str(signal_type)}, {score}, {price}, {volume}, {sql_str(detail)});"
        )
    run_sqream_sql("\n".join(lines), check=False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-key", default=os.getenv("POLYGON_API_KEY"))
    parser.add_argument("--watch-limit", type=int, default=100)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if not args.api_key:
        raise SystemExit("POLYGON_API_KEY is required")

    ensure_rt_tables()
    items = parse_watchlist(args.watch_limit)
    if not items:
        raise SystemExit("watchlist is empty")
    refresh_watchlist_table(items)

    symbols = ",".join(item.symbol for item in items)
    url = f"https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers?tickers={symbols}&apiKey={args.api_key}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    tickers = data.get("tickers", [])
    item_map = {item.symbol: item for item in items}

    triggered = 0
    for entry in tickers:
        symbol = entry.get("ticker")
        item = item_map.get(symbol)
        if item is None:
            continue
        last_trade = entry.get("lastTrade") or {}
        day = entry.get("day") or {}
        prev_day = entry.get("prevDay") or {}
        price = float(last_trade.get("p") or day.get("c") or 0.0)
        volume = int(day.get("v") or 0)
        prev_close = float(prev_day.get("c") or item.prior_close or 0.0)
        if price <= 0 or prev_close <= 0:
            continue
        day_change_pct = ((price / prev_close) - 1.0) * 100.0
        signal = evaluate_signal(item, price, day_change_pct, volume)
        if signal:
            triggered += 1
        insert_bar_and_signal(symbol, price, volume, signal)

    print(json.dumps({"watchlist": len(items), "snapshots": len(tickers), "triggered": triggered}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
