#!/usr/bin/env python3

from __future__ import annotations

import csv
import io
import json
import math
import re
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
import argparse

import requests
import yfinance as yf


HEADERS = {"User-Agent": "Mozilla/5.0"}
BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = BASE_DIR / "output"
OUT_DIR.mkdir(exist_ok=True)


@dataclass
class OneDayEvent:
    symbol: str
    event_date: str
    gain_pct: float
    event_close: float
    next_close: float | None
    next_day_change_pct: float | None
    next_day_direction: str


@dataclass
class CrashEvent:
    symbol: str
    event_date: str
    drop_pct: float
    event_close: float
    outcome: str
    outcome_date: str | None
    outcome_close: float | None
    days_to_outcome: int | None
    delist_date: str | None


def fetch_text(url: str) -> str:
    return requests.get(url, headers=HEADERS, timeout=30).text


def looks_like_common_equity(symbol: str, security_name: str) -> bool:
    blocked_terms = [
        "warrant",
        "right",
        "unit",
        "preferred",
        "depositary",
        "debenture",
        "notes",
        "bond",
        "etf",
        "etn",
        "trust",
        "fund",
        "income shares",
        "rate reset",
        "perp cap sec",
        "adr",
    ]
    name = security_name.lower()
    if any(term in name for term in blocked_terms):
        return False
    if symbol.endswith(("W", "R", "U", "V")) and len(symbol) >= 5:
        return False
    return True


def fetch_active_symbols() -> list[str]:
    out: set[str] = set()
    text = fetch_text("https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt")
    for row in csv.DictReader(io.StringIO(text), delimiter="|"):
        symbol = (row.get("Symbol") or "").strip().upper()
        name = (row.get("Security Name") or "").strip()
        if row.get("Test Issue") == "Y":
            continue
        if symbol and symbol.isalnum() and looks_like_common_equity(symbol, name):
            out.add(symbol)

    text = fetch_text("https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt")
    for row in csv.DictReader(io.StringIO(text), delimiter="|"):
        symbol = (row.get("ACT Symbol") or "").strip().upper()
        name = (row.get("Security Name") or "").strip()
        if row.get("Test Issue") == "Y" or row.get("ETF") == "Y":
            continue
        if symbol and symbol.isalnum() and looks_like_common_equity(symbol, name):
            out.add(symbol)
    return sorted(out)


def fetch_delisted_symbols() -> dict[str, date]:
    result: dict[str, date] = {}
    cutoff = date.today() - timedelta(days=366)
    # Alpha Vantage listing-status works without auth for this endpoint often enough.
    urls = [
        "https://www.alphavantage.co/query?function=LISTING_STATUS&state=delisted&apikey=demo",
        "https://www.alphavantage.co/query?function=LISTING_STATUS&state=delisted",
    ]
    csv_text = None
    for url in urls:
        try:
            txt = fetch_text(url)
        except Exception:
            continue
        if "symbol,name,exchange,assetType,ipoDate,delistingDate,status" in txt:
            csv_text = txt
            break
    if csv_text:
        for row in csv.DictReader(io.StringIO(csv_text)):
            symbol = (row.get("symbol") or "").strip().upper()
            ds = (row.get("delistingDate") or "").strip()
            if not symbol or not ds:
                continue
            try:
                d = date.fromisoformat(ds)
            except ValueError:
                continue
            if d >= cutoff:
                result[symbol] = d
        return result

    # Fallback: scrape first-page embedded rows from StockAnalysis for 2025/2026.
    for year in [2025, 2026]:
        html = fetch_text(f"https://stockanalysis.com/actions/delisted/{year}/")
        m = re.search(r"data:\[(.*?)\],fullCount:(\d+)", html, re.S)
        if not m:
            continue
        rows = re.findall(r'\{date:"([^"]+)",symbol:"([^"]+)",name:"([^"]+)"\}', m.group(1))
        for ds, raw_symbol, _name in rows:
            symbol = raw_symbol.replace("$", "")
            if symbol.startswith("!otc/"):
                symbol = symbol.split("/", 1)[1]
            try:
                d = datetime.strptime(ds, "%b %d, %Y").date()
            except ValueError:
                continue
            if d >= cutoff and symbol:
                result[symbol.upper()] = d
    return result


def batched(seq: list[str], size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def normalize_symbol_frame(df, symbol: str):
    try:
        sdf = df[symbol].copy()
    except Exception:
        return None
    if "Close" not in sdf.columns:
        return None
    sdf = sdf.dropna(subset=["Close"])
    if len(sdf) < 2:
        return None
    return sdf


def first_outcome_after_crash(sdf, crash_idx: int, delist_date: date | None):
    event_close = float(sdf["Close"].iloc[crash_idx])
    event_date = sdf.index[crash_idx].date()
    future = sdf.iloc[crash_idx + 1 :]
    if delist_date is not None:
        future = future[future.index.date <= delist_date]
    for idx, row in future.iterrows():
        close = float(row["Close"])
        if close >= 1.0 or close >= event_close * 2.0:
            return "rebound", idx.date(), close
    if delist_date is not None and delist_date > event_date:
        return "delisted", delist_date, None
    return "unresolved", None, None


def analyze(symbols: list[str], delisted: dict[str, date], batch_size: int = 200):
    one_day_events: list[OneDayEvent] = []
    crash_events: list[CrashEvent] = []
    bad_symbols: list[str] = []

    for batch_no, batch in enumerate(batched(symbols, batch_size), start=1):
        df = yf.download(
            batch,
            period="1y",
            auto_adjust=False,
            progress=False,
            threads=False,
            group_by="ticker",
        )
        for symbol in batch:
            sdf = normalize_symbol_frame(df, symbol)
            if sdf is None:
                bad_symbols.append(symbol)
                continue

            close = sdf["Close"].astype(float)
            ret = close.pct_change()
            one_day_mask = ret >= 1.0
            for ts in ret[one_day_mask].index:
                idx = sdf.index.get_loc(ts)
                next_close = None
                next_day_change_pct = None
                next_dir = "no_next_day"
                event_close = float(close.iloc[idx])
                if idx + 1 < len(sdf):
                    next_close = float(close.iloc[idx + 1])
                    next_day_change_pct = ((next_close / event_close) - 1.0) * 100.0
                    if next_close > event_close:
                        next_dir = "up"
                    elif next_close < event_close:
                        next_dir = "down"
                    else:
                        next_dir = "flat"
                one_day_events.append(
                    OneDayEvent(
                        symbol=symbol,
                        event_date=ts.date().isoformat(),
                        gain_pct=round(float(ret.loc[ts] * 100.0), 2),
                        event_close=round(event_close, 4),
                        next_close=round(next_close, 4) if next_close is not None else None,
                        next_day_change_pct=round(next_day_change_pct, 2) if next_day_change_pct is not None else None,
                        next_day_direction=next_dir,
                    )
                )

            crash_mask = (ret <= -0.5) & (close < 1.0)
            for ts in ret[crash_mask].index:
                idx = sdf.index.get_loc(ts)
                outcome, outcome_date, outcome_close = first_outcome_after_crash(sdf, idx, delisted.get(symbol))
                crash_events.append(
                    CrashEvent(
                        symbol=symbol,
                        event_date=ts.date().isoformat(),
                        drop_pct=round(float(ret.loc[ts] * 100.0), 2),
                        event_close=round(float(close.iloc[idx]), 4),
                        outcome=outcome,
                        outcome_date=outcome_date.isoformat() if outcome_date else None,
                        outcome_close=round(float(outcome_close), 4) if outcome_close is not None else None,
                        days_to_outcome=(outcome_date - ts.date()).days if outcome_date else None,
                        delist_date=delisted.get(symbol).isoformat() if delisted.get(symbol) else None,
                    )
                )
        print(f"batch {batch_no} processed: {len(batch)} symbols", flush=True)
        time.sleep(1.0)

    return one_day_events, crash_events, bad_symbols


def analyze_incremental(symbols: list[str], delisted: dict[str, date], batch_size: int, prefix: str):
    one_day_events: list[OneDayEvent] = []
    crash_events: list[CrashEvent] = []
    bad_symbols: list[str] = []

    for batch_no, batch in enumerate(batched(symbols, batch_size), start=1):
        df = yf.download(
            batch,
            period="1y",
            auto_adjust=False,
            progress=False,
            threads=False,
            group_by="ticker",
        )
        for symbol in batch:
            sdf = normalize_symbol_frame(df, symbol)
            if sdf is None:
                bad_symbols.append(symbol)
                continue

            close = sdf["Close"].astype(float)
            ret = close.pct_change()
            one_day_mask = ret >= 1.0
            for ts in ret[one_day_mask].index:
                idx = sdf.index.get_loc(ts)
                next_close = None
                next_day_change_pct = None
                next_dir = "no_next_day"
                event_close = float(close.iloc[idx])
                if idx + 1 < len(sdf):
                    next_close = float(close.iloc[idx + 1])
                    next_day_change_pct = ((next_close / event_close) - 1.0) * 100.0
                    if next_close > event_close:
                        next_dir = "up"
                    elif next_close < event_close:
                        next_dir = "down"
                    else:
                        next_dir = "flat"
                one_day_events.append(
                    OneDayEvent(
                        symbol=symbol,
                        event_date=ts.date().isoformat(),
                        gain_pct=round(float(ret.loc[ts] * 100.0), 2),
                        event_close=round(event_close, 4),
                        next_close=round(next_close, 4) if next_close is not None else None,
                        next_day_change_pct=round(next_day_change_pct, 2) if next_day_change_pct is not None else None,
                        next_day_direction=next_dir,
                    )
                )

            crash_mask = (ret <= -0.5) & (close < 1.0)
            for ts in ret[crash_mask].index:
                idx = sdf.index.get_loc(ts)
                outcome, outcome_date, outcome_close = first_outcome_after_crash(sdf, idx, delisted.get(symbol))
                crash_events.append(
                    CrashEvent(
                        symbol=symbol,
                        event_date=ts.date().isoformat(),
                        drop_pct=round(float(ret.loc[ts] * 100.0), 2),
                        event_close=round(float(close.iloc[idx]), 4),
                        outcome=outcome,
                        outcome_date=outcome_date.isoformat() if outcome_date else None,
                        outcome_close=round(float(outcome_close), 4) if outcome_close is not None else None,
                        days_to_outcome=(outcome_date - ts.date()).days if outcome_date else None,
                        delist_date=delisted.get(symbol).isoformat() if delisted.get(symbol) else None,
                    )
                )

        summary = summarize(one_day_events, crash_events, len(symbols), len(delisted), len(bad_symbols))
        state = {
            "processed_symbols": min(batch_no * batch_size, len(symbols)),
            "total_symbols": len(symbols),
            "summary": summary,
        }
        (OUT_DIR / f"{prefix}_state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
        (OUT_DIR / f"{prefix}_one_day_events.json").write_text(json.dumps([asdict(x) for x in one_day_events], indent=2), encoding="utf-8")
        (OUT_DIR / f"{prefix}_crash_events.json").write_text(json.dumps([asdict(x) for x in crash_events], indent=2), encoding="utf-8")
        print(f"batch {batch_no} processed: {len(batch)} symbols", flush=True)
        time.sleep(1.0)

    return one_day_events, crash_events, bad_symbols


def summarize(one_day_events: list[OneDayEvent], crash_events: list[CrashEvent], symbols_count: int, delisted_count: int, bad_symbols_count: int):
    one_day_with_next = [e for e in one_day_events if e.next_day_direction in {"up", "down", "flat"}]
    up = sum(e.next_day_direction == "up" for e in one_day_with_next)
    down = sum(e.next_day_direction == "down" for e in one_day_with_next)
    flat = sum(e.next_day_direction == "flat" for e in one_day_with_next)

    crash_rebound = sum(e.outcome == "rebound" for e in crash_events)
    crash_delisted = sum(e.outcome == "delisted" for e in crash_events)
    crash_unresolved = sum(e.outcome == "unresolved" for e in crash_events)

    return {
        "analysis_date": date.today().isoformat(),
        "active_symbols_scanned": symbols_count,
        "delisted_symbols_reference_count": delisted_count,
        "symbols_without_price_data": bad_symbols_count,
        "one_day_100pct": {
            "event_count": len(one_day_events),
            "unique_symbol_count": len({e.symbol for e in one_day_events}),
            "events_with_next_day": len(one_day_with_next),
            "next_day_up_count": up,
            "next_day_down_count": down,
            "next_day_flat_count": flat,
            "next_day_up_probability": round(up / len(one_day_with_next), 4) if one_day_with_next else None,
            "next_day_down_probability": round(down / len(one_day_with_next), 4) if one_day_with_next else None,
        },
        "crash_to_subdollar": {
            "event_count": len(crash_events),
            "unique_symbol_count": len({e.symbol for e in crash_events}),
            "rebound_count": crash_rebound,
            "delisted_count": crash_delisted,
            "unresolved_count": crash_unresolved,
            "rebound_probability": round(crash_rebound / len(crash_events), 4) if crash_events else None,
            "delisted_probability": round(crash_delisted / len(crash_events), 4) if crash_events else None,
        },
    }


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--incremental-prefix", default=None)
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--limit", type=int, default=None)
    return parser.parse_args()


def main():
    args = parse_args()
    symbols = fetch_active_symbols()
    delisted = fetch_delisted_symbols()
    selected_symbols = symbols[args.start :] if args.limit is None else symbols[args.start : args.start + args.limit]
    if args.incremental_prefix:
        one_day_events, crash_events, bad_symbols = analyze_incremental(
            selected_symbols, delisted, batch_size=args.batch_size, prefix=args.incremental_prefix
        )
    else:
        one_day_events, crash_events, bad_symbols = analyze(selected_symbols, delisted, batch_size=args.batch_size)
    summary = summarize(one_day_events, crash_events, len(selected_symbols), len(delisted), len(bad_symbols))
    summary["start_index"] = args.start
    summary["limit"] = args.limit

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (OUT_DIR / f"analysis_summary_{stamp}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (OUT_DIR / f"one_day_events_{stamp}.json").write_text(json.dumps([asdict(x) for x in one_day_events], indent=2), encoding="utf-8")
    (OUT_DIR / f"crash_events_{stamp}.json").write_text(json.dumps([asdict(x) for x in crash_events], indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
