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


BASE_DIR = Path(__file__).resolve().parent
STAGING_DIR = BASE_DIR / "staging"
NY_TZ = ZoneInfo("America/New_York")


@dataclass
class IntradayBar:
    symbol: str
    bar_time: str
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume_count: int
    source: str
    collected_at: str


def batched(seq: list[str], size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def load_symbols(
    path: Path,
    limit: int,
    offset: int = 0,
    exclude_file: Path | None = None,
    partition_index: int = 0,
    partition_count: int = 1,
) -> list[str]:
    symbols = [x.strip().upper() for x in path.read_text().splitlines() if x.strip()]
    if exclude_file and exclude_file.exists():
        excluded = {x.strip().upper() for x in exclude_file.read_text().splitlines() if x.strip()}
        symbols = [symbol for symbol in symbols if symbol not in excluded]
    if partition_count > 1:
        symbols = symbols[partition_index::partition_count]
    if offset:
        symbols = symbols[offset:]
    if limit and limit > 0:
        symbols = symbols[:limit]
    return symbols


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
    return sdf if not sdf.empty else None


def collect(symbols: list[str], interval: str, batch_size: int) -> list[IntradayBar]:
    rows: list[IntradayBar] = []
    collected_at = datetime.now(NY_TZ).isoformat()
    for batch in batched(symbols, batch_size):
        df = yf.download(
            batch,
            period="1d",
            interval=interval,
            auto_adjust=False,
            progress=False,
            threads=False,
            group_by="ticker",
        )
        for symbol in batch:
            sdf = normalize_download(df, symbol)
            if sdf is None:
                continue
            for ts, row in sdf.iterrows():
                bar_time = ts.tz_convert(NY_TZ).isoformat() if getattr(ts, "tzinfo", None) else str(ts)
                rows.append(
                    IntradayBar(
                        symbol=symbol,
                        bar_time=bar_time,
                        open_price=round(float(row["Open"]), 6),
                        high_price=round(float(row["High"]), 6),
                        low_price=round(float(row["Low"]), 6),
                        close_price=round(float(row["Close"]), 6),
                        volume_count=int(float(row["Volume"])) if pd.notna(row["Volume"]) else 0,
                        source=f"yfinance_{interval}",
                        collected_at=collected_at,
                    )
                )
    return rows


def write_parquet(rows: list[IntradayBar], output: Path) -> None:
    output.parent.mkdir(exist_ok=True)
    df = pd.DataFrame([asdict(row) for row in rows])
    if df.empty:
        df = pd.DataFrame(
            columns=[
                "symbol",
                "bar_time",
                "open_price",
                "high_price",
                "low_price",
                "close_price",
                "volume_count",
                "source",
                "collected_at",
            ]
    )
    df["volume_count"] = df["volume_count"].fillna(0).astype("int32")
    df.to_parquet(output, index=False)


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
    parser.add_argument("--output", type=Path, default=STAGING_DIR / "delayed_intraday_bars_latest.parquet")
    args = parser.parse_args()

    symbols = load_symbols(
        args.symbols_file,
        args.limit,
        args.offset,
        args.exclude_file,
        args.partition_index,
        args.partition_count,
    )
    rows = collect(symbols, args.interval, args.batch_size)
    write_parquet(rows, args.output)
    print(json.dumps({"symbols": len(symbols), "bars": len(rows), "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
