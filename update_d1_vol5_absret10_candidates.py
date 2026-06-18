#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from collect_delayed_intraday_bars import batched, load_symbols
from report_notifier import notify_error
from sqream_runtime_events import report, run_sqream_sql, sql_str


BASE_DIR = Path(__file__).resolve().parent
STATE_DIR = BASE_DIR / "state"
STAGING_DIR = BASE_DIR / "staging"
NY_TZ = ZoneInfo("America/New_York")


@dataclass
class Candidate:
    symbol: str
    signal_date: str
    close_price: float
    volume_count: int
    avg20_volume: float
    volume_x20: float
    ret_pct: float


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
    required = ["Close", "Volume"]
    if any(col not in sdf.columns for col in required):
        return None
    sdf = sdf.dropna(subset=["Close", "Volume"]).copy()
    return sdf if len(sdf) >= 25 else None


def collect_candidates(symbols: list[str], batch_size: int) -> list[Candidate]:
    candidates: list[Candidate] = []
    for batch in batched(symbols, batch_size):
        df = yf.download(
            batch,
            period="45d",
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False,
            group_by="ticker",
        )
        for symbol in batch:
            sdf = normalize_download(df, symbol)
            if sdf is None:
                continue
            sdf["ret_pct"] = sdf["Close"].astype(float).pct_change() * 100.0
            sdf["avg20_volume"] = sdf["Volume"].astype(float).rolling(20).mean().shift(1)
            row = sdf.iloc[-1]
            avg20 = float(row["avg20_volume"]) if pd.notna(row["avg20_volume"]) else 0.0
            volume = int(float(row["Volume"]))
            ret_pct = float(row["ret_pct"]) if pd.notna(row["ret_pct"]) else 0.0
            if avg20 <= 0:
                continue
            volume_x20 = volume / avg20
            if volume_x20 >= 5.0 and abs(ret_pct) <= 10.0:
                candidates.append(
                    Candidate(
                        symbol=symbol,
                        signal_date=sdf.index[-1].date().isoformat(),
                        close_price=round(float(row["Close"]), 6),
                        volume_count=volume,
                        avg20_volume=round(avg20, 2),
                        volume_x20=round(volume_x20, 4),
                        ret_pct=round(ret_pct, 4),
                    )
                )
    return sorted(candidates, key=lambda item: item.volume_x20, reverse=True)


def persist_candidates(candidates: list[Candidate]) -> tuple[Path, Path]:
    STATE_DIR.mkdir(exist_ok=True)
    STAGING_DIR.mkdir(exist_ok=True)
    payload = {
        "created_at": datetime.now(NY_TZ).isoformat(),
        "strategy": "d1_vol5_absret10",
        "candidates": [asdict(candidate) for candidate in candidates],
    }
    state_path = STATE_DIR / "d1_vol5_absret10_candidates.json"
    state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    return state_path


def sync_sqream(candidates: list[Candidate]) -> None:
    run_sqream_sql("drop table market_rt.d1_vol5_absret10_candidates;", check=False)
    run_sqream_sql(
        """
create table market_rt.d1_vol5_absret10_candidates (
  created_at text(32),
  symbol text(32),
  signal_date text(10),
  close_price double,
  volume_count bigint,
  avg20_volume double,
  volume_x20 double,
  ret_pct double
);
"""
    )
    created_at = datetime.now(NY_TZ).isoformat()
    for candidate in candidates:
        run_sqream_sql(
            "insert into market_rt.d1_vol5_absret10_candidates values ("
            f"{sql_str(created_at)}, "
            f"{sql_str(candidate.symbol)}, "
            f"{sql_str(candidate.signal_date)}, "
            f"{candidate.close_price}, "
            f"{candidate.volume_count}, "
            f"{candidate.avg20_volume}, "
            f"{candidate.volume_x20}, "
            f"{candidate.ret_pct});"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols-file", type=Path, default=BASE_DIR / "monitor_symbols_all.txt")
    parser.add_argument("--exclude-file", type=Path, default=BASE_DIR / "monitor_excluded_symbols.txt")
    parser.add_argument("--limit", type=int, default=5068)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()

    symbols = load_symbols(args.symbols_file, args.limit, args.offset, args.exclude_file)
    candidates = collect_candidates(symbols, args.batch_size)
    state_path = persist_candidates(candidates)
    sync_sqream(candidates)

    top = ", ".join(f"{item.symbol}({item.volume_x20:.1f}x,{item.ret_pct:+.1f}%)" for item in candidates[:10])
    message = (
        f"[대상 감지] strategy=d1_vol5_absret10 candidates={len(candidates)} "
        f"top={top or 'none'}"
    )
    if args.report:
        report("대상 감지", message, {"strategy": "d1_vol5_absret10", "candidates": [asdict(c) for c in candidates[:20]]})
    print(json.dumps({"candidates": len(candidates), "state": str(state_path), "top": top}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        notify_error("update_d1_vol5_absret10_candidates", exc)
        raise
