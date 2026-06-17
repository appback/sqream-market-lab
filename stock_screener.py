#!/usr/bin/env python3
"""
US stock event screener with optional Telegram alerts.

Signals:
1. Any stock that gained 100% or more in a single day during the last year.
2. Stocks showing a simple "surge setup" heuristic.
3. Stocks that traded below $1.00 in the last year and later rebounded.

The script avoids third-party dependencies so it can run in minimal environments.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Iterable


NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
STOOQ_DAILY_URL = "https://stooq.com/q/d/l/?s={symbol}.us&i=d"
DEFAULT_OUTPUT_DIR = Path("output")
DEFAULT_STATE_PATH = Path("state/alert_state.json")
DEFAULT_TIMEOUT = 20
USER_AGENT = "Mozilla/5.0 (compatible; stock-screener/1.0)"


@dataclass
class Candle:
    date: dt.date
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass
class Signal:
    category: str
    symbol: str
    event_date: str
    headline: str
    detail: str
    metrics: dict[str, float | int | str]


def http_get_text(url: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def http_post_form(url: str, data: dict[str, str], timeout: int = DEFAULT_TIMEOUT) -> str:
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=encoded,
        headers={"User-Agent": USER_AGENT},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def safe_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_int(value: str) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def rolling_mean(values: list[int | float], window: int) -> float | None:
    if len(values) < window:
        return None
    return mean(values[-window:])


def is_common_symbol(symbol: str) -> bool:
    if not symbol:
        return False
    if "$" in symbol or "^" in symbol:
        return False
    if any(ch in symbol for ch in (".", "/")):
        return False
    return symbol.isalnum()


def read_symbol_lines(lines: Iterable[str], column_name: str) -> set[str]:
    symbols: set[str] = set()
    rows = csv.DictReader(lines, delimiter="|")
    for row in rows:
        symbol = (row.get(column_name) or "").strip().upper()
        if row.get("Test Issue") == "Y":
            continue
        if row.get("ETF") == "Y":
            continue
        if is_common_symbol(symbol):
            symbols.add(symbol)
    return symbols


def fetch_symbol_universe(limit: int | None = None, symbols_file: Path | None = None) -> list[str]:
    if symbols_file is not None:
        raw_lines = [line.strip().upper() for line in symbols_file.read_text(encoding="utf-8").splitlines()]
        result = [line for line in raw_lines if line and is_common_symbol(line)]
        if limit is not None:
            return result[:limit]
        return result

    symbols: set[str] = set()
    symbols.update(read_symbol_lines(http_get_text(NASDAQ_LISTED_URL).splitlines(), "Symbol"))
    symbols.update(read_symbol_lines(http_get_text(OTHER_LISTED_URL).splitlines(), "ACT Symbol"))

    result = sorted(symbols)
    if limit is not None:
        return result[:limit]
    return result


def parse_candles_from_csv_text(csv_text: str) -> list[Candle]:
    rows = csv.DictReader(csv_text.splitlines())
    candles: list[Candle] = []
    cutoff = dt.date.today() - dt.timedelta(days=370)

    for row in rows:
        date_raw = row.get("Date")
        close = safe_float(row.get("Close"))
        low = safe_float(row.get("Low"))
        high = safe_float(row.get("High"))
        open_ = safe_float(row.get("Open"))
        if not date_raw or None in (close, low, high, open_):
            continue
        try:
            candle_date = dt.date.fromisoformat(date_raw)
        except ValueError:
            continue
        if candle_date < cutoff:
            continue
        candles.append(
            Candle(
                date=candle_date,
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=safe_int(row.get("Volume")),
            )
        )

    candles.sort(key=lambda x: x.date)
    return candles


def fetch_candles(symbol: str, price_dir: Path | None = None) -> list[Candle]:
    if price_dir is not None:
        csv_path = price_dir / f"{symbol.upper()}.csv"
        if not csv_path.exists():
            return []
        return parse_candles_from_csv_text(csv_path.read_text(encoding="utf-8"))
    return parse_candles_from_csv_text(http_get_text(STOOQ_DAILY_URL.format(symbol=symbol.lower())))


def scan_one_day_doublers(symbol: str, candles: list[Candle]) -> list[Signal]:
    signals: list[Signal] = []
    for prev_candle, candle in zip(candles, candles[1:]):
        if prev_candle.close <= 0:
            continue
        gain_pct = ((candle.close / prev_candle.close) - 1.0) * 100.0
        if gain_pct < 100.0:
            continue
        volume_ratio = None
        if prev_candle.volume > 0:
            volume_ratio = candle.volume / prev_candle.volume
        signals.append(
            Signal(
                category="one_day_100pct",
                symbol=symbol,
                event_date=candle.date.isoformat(),
                headline=f"{symbol}: single-day gain {gain_pct:.1f}%",
                detail=(
                    f"Closed at {candle.close:.2f} after prior close {prev_candle.close:.2f}. "
                    f"Intraday range {candle.low:.2f}-{candle.high:.2f}."
                ),
                metrics={
                    "gain_pct": round(gain_pct, 2),
                    "prev_close": round(prev_candle.close, 4),
                    "close": round(candle.close, 4),
                    "volume": candle.volume,
                    "volume_ratio_vs_prev_day": round(volume_ratio, 2) if volume_ratio is not None else "n/a",
                },
            )
        )
    return signals


def scan_surge_setup(symbol: str, candles: list[Candle]) -> list[Signal]:
    if len(candles) < 90:
        return []

    recent = candles[-1]
    prior_20 = candles[-21] if len(candles) >= 21 else None
    if prior_20 is None or prior_20.close <= 0:
        return []

    close_values = [c.close for c in candles]
    volume_values = [c.volume for c in candles]

    avg_20_volume = rolling_mean(volume_values, 20)
    avg_50_volume = rolling_mean(volume_values, 50)
    if avg_20_volume is None or avg_50_volume is None or avg_50_volume <= 0:
        return []

    return_20d = ((recent.close / prior_20.close) - 1.0) * 100.0
    high_90d = max(close_values[-90:])
    breakout_ratio = recent.close / high_90d if high_90d > 0 else 0
    volume_ratio = avg_20_volume / avg_50_volume if avg_50_volume > 0 else 0

    if return_20d < 25.0:
        return []
    if breakout_ratio < 0.97:
        return []
    if volume_ratio < 1.8:
        return []

    return [
        Signal(
            category="surge_setup",
            symbol=symbol,
            event_date=recent.date.isoformat(),
            headline=f"{symbol}: surge setup candidate",
            detail=(
                f"20-day return {return_20d:.1f}%, close {recent.close:.2f}, "
                f"20-day avg volume {avg_20_volume:.0f} vs 50-day {avg_50_volume:.0f}."
            ),
            metrics={
                "return_20d_pct": round(return_20d, 2),
                "close": round(recent.close, 4),
                "close_vs_90d_high": round(breakout_ratio, 4),
                "avg20_volume": round(avg_20_volume, 0),
                "avg50_volume": round(avg_50_volume, 0),
                "avg20_vs_avg50_volume": round(volume_ratio, 2),
            },
        )
    ]


def scan_sub_dollar_rebound(symbol: str, candles: list[Candle]) -> list[Signal]:
    if len(candles) < 3:
        return []

    for prev_candle, crash_candle in zip(candles, candles[1:]):
        if prev_candle.close <= 0:
            continue
        drop_pct = ((crash_candle.close / prev_candle.close) - 1.0) * 100.0
        if drop_pct > -50.0:
            continue
        if crash_candle.close >= 1.0:
            continue

        for rebound_candle in candles:
            if rebound_candle.date <= crash_candle.date:
                continue
            recovered_one_dollar = rebound_candle.close >= 1.0
            doubled_from_crash = rebound_candle.close >= (crash_candle.close * 2.0)
            if not recovered_one_dollar and not doubled_from_crash:
                continue
            rebound_pct = ((rebound_candle.close / crash_candle.close) - 1.0) * 100.0
            return [
                Signal(
                    category="sub_dollar_rebound",
                    symbol=symbol,
                    event_date=rebound_candle.date.isoformat(),
                    headline=f"{symbol}: crash-to-sub-$1 rebound",
                    detail=(
                        f"Closed down {abs(drop_pct):.1f}% to {crash_candle.close:.2f} on "
                        f"{crash_candle.date.isoformat()} after {prev_candle.close:.2f}, "
                        f"then rebounded to {rebound_candle.close:.2f}."
                    ),
                    metrics={
                        "crash_date": crash_candle.date.isoformat(),
                        "pre_crash_close": round(prev_candle.close, 4),
                        "crash_close": round(crash_candle.close, 4),
                        "crash_drop_pct": round(drop_pct, 2),
                        "rebound_date": rebound_candle.date.isoformat(),
                        "rebound_close": round(rebound_candle.close, 4),
                        "rebound_pct_from_crash_close": round(rebound_pct, 2),
                    },
                )
            ]
    return []


def load_state(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(path: Path, state: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=True), encoding="utf-8")


def signal_key(signal: Signal) -> str:
    return f"{signal.category}:{signal.symbol}:{signal.event_date}:{signal.headline}"


def format_signal(signal: Signal) -> str:
    return (
        f"[{signal.category}] {signal.headline}\n"
        f"- date: {signal.event_date}\n"
        f"- detail: {signal.detail}\n"
        f"- metrics: {json.dumps(signal.metrics, ensure_ascii=False)}"
    )


def write_reports(output_dir: Path, signals: list[Signal]) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"signals_{stamp}.json"
    csv_path = output_dir / f"signals_{stamp}.csv"

    json_payload = [
        {
            "category": signal.category,
            "symbol": signal.symbol,
            "event_date": signal.event_date,
            "headline": signal.headline,
            "detail": signal.detail,
            "metrics": signal.metrics,
        }
        for signal in signals
    ]
    json_path.write_text(json.dumps(json_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["category", "symbol", "event_date", "headline", "detail", "metrics_json"])
        for signal in signals:
            writer.writerow(
                [
                    signal.category,
                    signal.symbol,
                    signal.event_date,
                    signal.headline,
                    signal.detail,
                    json.dumps(signal.metrics, ensure_ascii=False),
                ]
            )
    return json_path, csv_path


def send_telegram_message(bot_token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    http_post_form(url, {"chat_id": chat_id, "text": text[:4000]})


def chunked(iterable: Iterable[Signal], size: int) -> Iterable[list[Signal]]:
    batch: list[Signal] = []
    for item in iterable:
        batch.append(item)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def run_scan(
    limit: int | None,
    pause_seconds: float,
    symbols_file: Path | None = None,
    price_dir: Path | None = None,
) -> list[Signal]:
    all_signals: list[Signal] = []
    symbols = fetch_symbol_universe(limit=limit, symbols_file=symbols_file)

    for index, symbol in enumerate(symbols, start=1):
        try:
            candles = fetch_candles(symbol, price_dir=price_dir)
        except urllib.error.HTTPError:
            continue
        except urllib.error.URLError:
            continue
        except TimeoutError:
            continue

        if len(candles) < 2:
            continue

        all_signals.extend(scan_one_day_doublers(symbol, candles))
        all_signals.extend(scan_surge_setup(symbol, candles))
        all_signals.extend(scan_sub_dollar_rebound(symbol, candles))

        if pause_seconds > 0:
            time.sleep(pause_seconds)

        if index % 100 == 0:
            print(f"processed {index} symbols", file=sys.stderr)

    category_order = {"one_day_100pct": 0, "surge_setup": 1, "sub_dollar_rebound": 2}
    all_signals.sort(key=lambda item: (category_order.get(item.category, 99), item.symbol, item.event_date))
    return all_signals


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan US stocks for explosive move patterns.")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of symbols for testing.")
    parser.add_argument("--pause-seconds", type=float, default=0.15, help="Delay between symbol fetches.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--state-path", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--symbols-file", type=Path, default=None, help="Optional local symbol list, one symbol per line.")
    parser.add_argument("--price-dir", type=Path, default=None, help="Optional local candle CSV directory named SYMBOL.csv.")
    parser.add_argument("--telegram-bot-token", default=os.getenv("TELEGRAM_BOT_TOKEN"))
    parser.add_argument("--telegram-chat-id", default=os.getenv("TELEGRAM_CHAT_ID"))
    parser.add_argument(
        "--telegram-only-new",
        action="store_true",
        help="Send only signals not seen in the local state file.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        signals = run_scan(
            limit=args.limit,
            pause_seconds=args.pause_seconds,
            symbols_file=args.symbols_file,
            price_dir=args.price_dir,
        )
    except urllib.error.URLError as exc:
        print(f"network error: {exc}", file=sys.stderr)
        print(
            "hint: this script needs outbound access to nasdaqtrader.com, stooq.com, and api.telegram.org",
            file=sys.stderr,
        )
        return 2
    except OSError as exc:
        print(f"file error: {exc}", file=sys.stderr)
        return 2

    json_path, csv_path = write_reports(args.output_dir, signals)

    print(f"signals found: {len(signals)}")
    print(f"json report: {json_path}")
    print(f"csv report: {csv_path}")

    state = load_state(args.state_path)
    new_signals = [signal for signal in signals if signal_key(signal) not in state]

    if args.telegram_bot_token and args.telegram_chat_id:
        send_list = new_signals if args.telegram_only_new else signals
        for batch in chunked(send_list, 8):
            lines = ["US stock screener alert", ""]
            lines.extend(format_signal(signal) for signal in batch)
            send_telegram_message(args.telegram_bot_token, args.telegram_chat_id, "\n\n".join(lines))
        print(f"telegram candidates: {len(send_list)}")
    else:
        print("telegram skipped: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing")

    for signal in new_signals:
        state[signal_key(signal)] = dt.datetime.now().isoformat()
    save_state(args.state_path, state)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
