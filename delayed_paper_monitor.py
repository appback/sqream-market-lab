#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf


BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = BASE_DIR / "output"
STATE_DIR = BASE_DIR / "state"
NY_TZ = ZoneInfo("America/New_York")


@dataclass
class MonitorPosition:
    symbol: str
    event_time: str
    entry_time: str | None
    exit_time: str | None
    event_price: float
    event_high: float
    entry_price: float | None
    target_price: float | None
    stop_price: float | None
    exit_price: float | None
    status: str
    return_pct: float | None
    reason: str


def load_symbols(path: Path | None, limit: int) -> list[str]:
    if path and path.exists():
        symbols = [x.strip().upper() for x in path.read_text().splitlines() if x.strip()]
    else:
        symbols = ["AAPL", "TSLA", "NVDA", "AMD", "PLTR"]
    return symbols[:limit]


def pct(a: float, b: float) -> float:
    return ((a / b) - 1.0) * 100.0 if b > 0 else 0.0


def load_state(path: Path) -> dict[str, MonitorPosition]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {item["symbol"]: MonitorPosition(**item) for item in raw}


def save_state(path: Path, positions: dict[str, MonitorPosition]) -> None:
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps([asdict(x) for x in positions.values()], indent=2), encoding="utf-8")


def append_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def normalize_download(df, symbol: str):
    if df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        try:
            sdf = df[symbol].copy()
        except Exception:
            return None
    else:
        sdf = df.copy()
    required = ["Open", "High", "Low", "Close", "Volume"]
    if any(col not in sdf.columns for col in required):
        return None
    sdf = sdf.dropna(subset=["Open", "High", "Low", "Close"])
    if sdf.empty:
        return None
    return sdf


def update_symbol(symbol: str, sdf, positions: dict[str, MonitorPosition], alerts_path: Path) -> None:
    first_open = float(sdf["Open"].iloc[0])
    if first_open <= 0:
        return

    day_high = float(sdf["High"].max())
    latest = sdf.iloc[-1]
    latest_time = sdf.index[-1].tz_convert(NY_TZ).isoformat() if sdf.index[-1].tzinfo else str(sdf.index[-1])
    latest_price = float(latest["Close"])
    day_return = pct(latest_price, first_open)

    pos = positions.get(symbol)
    if pos is None and day_return >= 100.0 and 3.0 <= latest_price <= 10.0:
        pos = MonitorPosition(
            symbol=symbol,
            event_time=latest_time,
            entry_time=None,
            exit_time=None,
            event_price=round(latest_price, 4),
            event_high=round(day_high, 4),
            entry_price=None,
            target_price=None,
            stop_price=None,
            exit_price=None,
            status="watch_pullback_35",
            return_pct=None,
            reason=f"day_return={day_return:.2f}% price_band=3-10",
        )
        positions[symbol] = pos
        append_jsonl(alerts_path, {"type": "surge_detected", **asdict(pos)})

    if pos is None:
        return

    if pos.status == "watch_pullback_35":
        entry_price = pos.event_price * 0.65
        if float(latest["Low"]) <= entry_price:
            pos.entry_time = latest_time
            pos.entry_price = round(entry_price, 4)
            pos.target_price = round(entry_price * 1.25, 4)
            pos.stop_price = round(entry_price * 0.85, 4)
            pos.status = "open"
            pos.reason = "35pct_pullback_entry"
            append_jsonl(alerts_path, {"type": "paper_entry", **asdict(pos)})

    if pos.status == "open" and pos.entry_price and pos.target_price and pos.stop_price:
        latest_low = float(latest["Low"])
        latest_high = float(latest["High"])
        if latest_low <= pos.stop_price:
            pos.exit_time = latest_time
            pos.exit_price = pos.stop_price
            pos.status = "closed"
            pos.return_pct = round(pct(pos.exit_price, pos.entry_price), 2)
            pos.reason = "stop_loss"
            append_jsonl(alerts_path, {"type": "paper_exit", **asdict(pos)})
        elif latest_high >= pos.target_price:
            pos.exit_time = latest_time
            pos.exit_price = pos.target_price
            pos.status = "closed"
            pos.return_pct = round(pct(pos.exit_price, pos.entry_price), 2)
            pos.reason = "take_profit"
            append_jsonl(alerts_path, {"type": "paper_exit", **asdict(pos)})


def batched(seq: list[str], size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def run_once(symbols: list[str], interval: str, batch_size: int, positions: dict[str, MonitorPosition], alerts_path: Path) -> None:
    for batch in batched(symbols, batch_size):
        df = yf.download(batch, period="1d", interval=interval, auto_adjust=False, progress=False, threads=False, group_by="ticker")
        for symbol in batch:
            sdf = normalize_download(df, symbol)
            if sdf is not None:
                update_symbol(symbol, sdf, positions, alerts_path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols-file", type=Path)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--interval", default="1m")
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--state-path", type=Path, default=STATE_DIR / "delayed_paper_monitor.json")
    parser.add_argument("--alerts-path", type=Path, default=OUT_DIR / "delayed_paper_alerts.jsonl")
    args = parser.parse_args()

    symbols = load_symbols(args.symbols_file, args.limit)
    positions = load_state(args.state_path)
    while True:
        run_once(symbols, args.interval, args.batch_size, positions, args.alerts_path)
        save_state(args.state_path, positions)
        print(
            json.dumps(
                {
                    "time": datetime.now(NY_TZ).isoformat(),
                    "symbols": len(symbols),
                    "positions": len(positions),
                    "open": sum(1 for p in positions.values() if p.status == "open"),
                    "watch": sum(1 for p in positions.values() if p.status == "watch_pullback_35"),
                    "closed": sum(1 for p in positions.values() if p.status == "closed"),
                }
            ),
            flush=True,
        )
        if args.once:
            break
        time.sleep(args.poll_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
