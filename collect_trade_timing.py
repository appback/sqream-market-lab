#!/usr/bin/env python3

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd
import yfinance as yf

from analyze_events import fetch_active_symbols


BASE_DIR = Path(__file__).resolve().parent
STAGING_DIR = BASE_DIR / "staging"


@dataclass
class EventPath:
    symbol: str
    event_type: str
    event_date: str
    prev_close: float
    event_open: float
    event_high: float
    event_low: float
    event_close: float
    event_volume: int
    event_return_pct: float
    intraday_range_pct: float
    close_from_high_pct: float
    close_from_low_pct: float
    next_1d_high_return_pct: float | None
    next_3d_high_return_pct: float | None
    next_5d_high_return_pct: float | None
    next_10d_high_return_pct: float | None
    next_3d_low_return_pct: float | None
    next_5d_low_return_pct: float | None
    next_10d_low_return_pct: float | None


@dataclass
class PaperTrade:
    symbol: str
    source_event_type: str
    strategy: str
    signal_date: str
    entry_date: str | None
    exit_date: str | None
    entry_price: float | None
    exit_price: float | None
    target_price: float | None
    stop_price: float | None
    max_hold_days: int
    return_pct: float | None
    exit_reason: str
    entry_delay_days: int | None
    hold_days: int | None
    event_return_pct: float
    event_close_from_high_pct: float


def batched(seq: list[str], size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def normalize_symbol_frame(df, symbol: str):
    try:
        sdf = df[symbol].copy()
    except Exception:
        return None
    required = ["Open", "High", "Low", "Close", "Volume"]
    if any(col not in sdf.columns for col in required):
        return None
    sdf = sdf.dropna(subset=["Open", "High", "Low", "Close"])
    if len(sdf) < 30:
        return None
    return sdf


def pct(a: float, b: float) -> float | None:
    if b <= 0:
        return None
    return ((a / b) - 1.0) * 100.0


def future_window(sdf, start_idx: int, days: int):
    return sdf.iloc[start_idx + 1 : min(len(sdf), start_idx + 1 + days)]


def max_high_return(sdf, idx: int, days: int, base: float) -> float | None:
    w = future_window(sdf, idx, days)
    if w.empty:
        return None
    return pct(float(w["High"].max()), base)


def min_low_return(sdf, idx: int, days: int, base: float) -> float | None:
    w = future_window(sdf, idx, days)
    if w.empty:
        return None
    return pct(float(w["Low"].min()), base)


def make_event_path(symbol: str, event_type: str, sdf, idx: int, event_return_pct: float) -> EventPath:
    prev_close = float(sdf["Close"].iloc[idx - 1])
    row = sdf.iloc[idx]
    event_open = float(row["Open"])
    event_high = float(row["High"])
    event_low = float(row["Low"])
    event_close = float(row["Close"])
    event_volume = int(float(row["Volume"])) if pd.notna(row["Volume"]) else 0
    intraday_range_pct = pct(event_high, event_low) or 0.0
    close_from_high_pct = pct(event_close, event_high) or 0.0
    close_from_low_pct = pct(event_close, event_low) or 0.0
    return EventPath(
        symbol=symbol,
        event_type=event_type,
        event_date=sdf.index[idx].date().isoformat(),
        prev_close=round(prev_close, 4),
        event_open=round(event_open, 4),
        event_high=round(event_high, 4),
        event_low=round(event_low, 4),
        event_close=round(event_close, 4),
        event_volume=event_volume,
        event_return_pct=round(event_return_pct, 2),
        intraday_range_pct=round(intraday_range_pct, 2),
        close_from_high_pct=round(close_from_high_pct, 2),
        close_from_low_pct=round(close_from_low_pct, 2),
        next_1d_high_return_pct=round(max_high_return(sdf, idx, 1, event_close), 2) if max_high_return(sdf, idx, 1, event_close) is not None else None,
        next_3d_high_return_pct=round(max_high_return(sdf, idx, 3, event_close), 2) if max_high_return(sdf, idx, 3, event_close) is not None else None,
        next_5d_high_return_pct=round(max_high_return(sdf, idx, 5, event_close), 2) if max_high_return(sdf, idx, 5, event_close) is not None else None,
        next_10d_high_return_pct=round(max_high_return(sdf, idx, 10, event_close), 2) if max_high_return(sdf, idx, 10, event_close) is not None else None,
        next_3d_low_return_pct=round(min_low_return(sdf, idx, 3, event_close), 2) if min_low_return(sdf, idx, 3, event_close) is not None else None,
        next_5d_low_return_pct=round(min_low_return(sdf, idx, 5, event_close), 2) if min_low_return(sdf, idx, 5, event_close) is not None else None,
        next_10d_low_return_pct=round(min_low_return(sdf, idx, 10, event_close), 2) if min_low_return(sdf, idx, 10, event_close) is not None else None,
    )


def simulate_exit(sdf, entry_idx: int, entry_price: float, target_mult: float, stop_mult: float, max_hold_days: int):
    target_price = entry_price * target_mult
    stop_price = entry_price * stop_mult
    exit_idx = entry_idx
    exit_price = entry_price
    exit_reason = "max_hold"
    for i in range(entry_idx, min(len(sdf), entry_idx + max_hold_days)):
        row = sdf.iloc[i]
        low = float(row["Low"])
        high = float(row["High"])
        close = float(row["Close"])
        if low <= stop_price:
            return i, stop_price, target_price, stop_price, "stop_loss"
        if high >= target_price:
            return i, target_price, target_price, stop_price, "take_profit"
        exit_idx = i
        exit_price = close
    return exit_idx, exit_price, target_price, stop_price, exit_reason


def build_trade(symbol: str, event: EventPath, sdf, event_idx: int, strategy: str) -> PaperTrade:
    event_close = event.event_close
    entry_idx: int | None = None
    entry_price: float | None = None
    target_mult = 1.15
    stop_mult = 0.9
    max_hold_days = 5

    if strategy == "surge_next_open":
        if event_idx + 1 < len(sdf):
            entry_idx = event_idx + 1
            entry_price = float(sdf["Open"].iloc[entry_idx])
        target_mult, stop_mult, max_hold_days = 1.15, 0.9, 5
    elif strategy == "surge_pullback_20":
        pullback_price = event_close * 0.8
        target_mult, stop_mult, max_hold_days = 1.2, 0.88, 10
        for i in range(event_idx + 1, min(len(sdf), event_idx + 11)):
            if float(sdf["Low"].iloc[i]) <= pullback_price:
                entry_idx = i
                entry_price = pullback_price
                break
    elif strategy == "surge_pullback_35":
        pullback_price = event_close * 0.65
        target_mult, stop_mult, max_hold_days = 1.25, 0.85, 15
        for i in range(event_idx + 1, min(len(sdf), event_idx + 16)):
            if float(sdf["Low"].iloc[i]) <= pullback_price:
                entry_idx = i
                entry_price = pullback_price
                break
    elif strategy == "crash_reversal_next_green":
        target_mult, stop_mult, max_hold_days = 1.25, 0.88, 15
        for i in range(event_idx + 1, min(len(sdf), event_idx + 11)):
            if float(sdf["Close"].iloc[i]) > float(sdf["Open"].iloc[i]):
                entry_idx = i + 1 if i + 1 < len(sdf) else None
                entry_price = float(sdf["Open"].iloc[entry_idx]) if entry_idx is not None else None
                break
    elif strategy == "crash_reclaim_event_close":
        target_mult, stop_mult, max_hold_days = 1.3, 0.86, 20
        for i in range(event_idx + 1, min(len(sdf), event_idx + 16)):
            if float(sdf["High"].iloc[i]) >= event_close:
                entry_idx = i
                entry_price = event_close
                break

    if entry_idx is None or entry_price is None or entry_price <= 0:
        return PaperTrade(
            symbol=symbol,
            source_event_type=event.event_type,
            strategy=strategy,
            signal_date=event.event_date,
            entry_date=None,
            exit_date=None,
            entry_price=None,
            exit_price=None,
            target_price=None,
            stop_price=None,
            max_hold_days=max_hold_days,
            return_pct=None,
            exit_reason="no_entry",
            entry_delay_days=None,
            hold_days=None,
            event_return_pct=event.event_return_pct,
            event_close_from_high_pct=event.close_from_high_pct,
        )

    exit_idx, exit_price, target_price, stop_price, exit_reason = simulate_exit(
        sdf, entry_idx, entry_price, target_mult, stop_mult, max_hold_days
    )
    entry_date = sdf.index[entry_idx].date()
    exit_date = sdf.index[exit_idx].date()
    return PaperTrade(
        symbol=symbol,
        source_event_type=event.event_type,
        strategy=strategy,
        signal_date=event.event_date,
        entry_date=entry_date.isoformat(),
        exit_date=exit_date.isoformat(),
        entry_price=round(entry_price, 4),
        exit_price=round(exit_price, 4),
        target_price=round(target_price, 4),
        stop_price=round(stop_price, 4),
        max_hold_days=max_hold_days,
        return_pct=round(pct(exit_price, entry_price) or 0.0, 2),
        exit_reason=exit_reason,
        entry_delay_days=(entry_date - pd.Timestamp(event.event_date).date()).days,
        hold_days=(exit_date - entry_date).days,
        event_return_pct=event.event_return_pct,
        event_close_from_high_pct=event.close_from_high_pct,
    )


def collect(symbols: list[str], batch_size: int, prefix: str | None = None):
    events: list[EventPath] = []
    trades: list[PaperTrade] = []
    for batch_no, batch in enumerate(batched(symbols, batch_size), start=1):
        df = yf.download(batch, period="1y", auto_adjust=False, progress=False, threads=False, group_by="ticker")
        for symbol in batch:
            sdf = normalize_symbol_frame(df, symbol)
            if sdf is None:
                continue
            close = sdf["Close"].astype(float)
            ret = close.pct_change()
            for i in range(1, len(sdf)):
                day_ret = float(ret.iloc[i]) if pd.notna(ret.iloc[i]) else None
                if day_ret is None:
                    continue
                event_type = None
                if day_ret >= 1.0:
                    event_type = "one_day_100pct"
                elif day_ret <= -0.5 and float(close.iloc[i]) < 1.0:
                    event_type = "crash_50pct_sub1"
                if event_type is None:
                    continue
                event = make_event_path(symbol, event_type, sdf, i, day_ret * 100.0)
                events.append(event)
                if event_type == "one_day_100pct":
                    for strategy in ["surge_next_open", "surge_pullback_20", "surge_pullback_35"]:
                        trades.append(build_trade(symbol, event, sdf, i, strategy))
                else:
                    for strategy in ["crash_reversal_next_green", "crash_reclaim_event_close"]:
                        trades.append(build_trade(symbol, event, sdf, i, strategy))
        if prefix is not None:
            write_outputs(events, trades, prefix)
        print(f"batch {batch_no} processed: symbols={len(batch)} events={len(events)} trades={len(trades)}", flush=True)
    return events, trades


def write_outputs(events: list[EventPath], trades: list[PaperTrade], prefix: str) -> None:
    STAGING_DIR.mkdir(exist_ok=True)
    event_rows = [asdict(row) for row in events]
    trade_rows = [asdict(row) for row in trades]
    event_df = pd.DataFrame(event_rows)
    trade_df = pd.DataFrame(trade_rows)
    if not event_df.empty:
        event_df["event_volume"] = event_df["event_volume"].astype("int32")
    if not trade_df.empty:
        trade_df["max_hold_days"] = trade_df["max_hold_days"].astype("int32")
    event_df.to_parquet(STAGING_DIR / f"{prefix}_event_paths.parquet", index=False)
    trade_df.to_parquet(STAGING_DIR / f"{prefix}_paper_trades.parquet", index=False)
    event_df.to_csv(STAGING_DIR / f"{prefix}_event_paths.csv", index=False)
    trade_df.to_csv(STAGING_DIR / f"{prefix}_paper_trades.csv", index=False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--prefix", default="trade_timing")
    args = parser.parse_args()
    symbols = fetch_active_symbols()[args.offset : args.offset + args.limit]
    events, trades = collect(symbols, args.batch_size, args.prefix)
    write_outputs(events, trades, args.prefix)
    entered = [t for t in trades if t.return_pct is not None]
    print(f"events={len(events)} trades={len(trades)} entered={len(entered)}")
    if entered:
        win_rate = sum(1 for t in entered if (t.return_pct or 0) > 0) / len(entered)
        avg_return = sum(t.return_pct or 0 for t in entered) / len(entered)
        print(f"win_rate={win_rate:.4f} avg_return_pct={avg_return:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
