#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import statistics
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import requests
import yfinance as yf


HEADERS = {"User-Agent": "Mozilla/5.0"}
BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = BASE_DIR / "output"
OUT_DIR.mkdir(exist_ok=True)


@dataclass
class Trade:
    symbol: str
    signal_type: str
    signal_date: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    hold_days: int
    return_pct: float
    exit_reason: str


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


def fetch_active_symbols(limit: int | None = None) -> list[str]:
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

    result = sorted(out)
    if limit is not None:
        return result[:limit]
    return result


def batched(seq: list[str], size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def safe_float(x) -> float | None:
    try:
        if x is None or (isinstance(x, float) and math.isnan(x)):
            return None
        return float(x)
    except Exception:
        return None


def make_signal(history) -> tuple[bool, bool]:
    if len(history) < 90:
        return False, False

    close = history["Close"].astype(float)
    volume = history["Volume"].fillna(0).astype(float)
    ret = close.pct_change()
    last_close = float(close.iloc[-1])

    ret_1d = safe_float(ret.iloc[-1] * 100.0) if len(ret) >= 2 else None
    ret_5d = safe_float(((last_close / float(close.iloc[-6])) - 1.0) * 100.0) if len(close) >= 6 else None
    ret_20d = safe_float(((last_close / float(close.iloc[-21])) - 1.0) * 100.0) if len(close) >= 21 else None
    avg20v = statistics.mean(volume.iloc[-20:]) if len(volume) >= 20 else None
    avg50v = statistics.mean(volume.iloc[-50:]) if len(volume) >= 50 else None
    volume_ratio_20_50 = safe_float(avg20v / avg50v) if avg20v and avg50v and avg50v > 0 else None
    high90 = max(close.iloc[-90:]) if len(close) >= 90 else max(close)
    high252 = max(close.iloc[-252:]) if len(close) >= 252 else max(close)
    price_vs_90d_high = safe_float(last_close / high90) if high90 else None
    drawdown_from_252d_high = safe_float((last_close / high252) - 1.0) if high252 else None

    vol20 = None
    if len(ret.dropna()) >= 20:
        sample = [float(x) for x in ret.dropna().iloc[-20:]]
        vol20 = statistics.pstdev(sample) * 100.0

    one_day_100pct_flag = 1 if (ret.iloc[-1] if len(ret) else 0) >= 1.0 else 0
    crash_50pct_sub1_flag = 1 if (ret.iloc[-1] if len(ret) else 0) <= -0.5 and last_close < 1.0 else 0

    rebound_after_crash_flag = 0
    for i in range(1, len(close)):
        day_ret = float(ret.iloc[i]) if not math.isnan(float(ret.iloc[i])) else None
        if day_ret is None:
            continue
        if day_ret <= -0.5 and float(close.iloc[i]) < 1.0:
            crash_close = float(close.iloc[i])
            for j in range(i + 1, len(close)):
                if float(close.iloc[j]) >= 1.0 or float(close.iloc[j]) >= crash_close * 2.0:
                    rebound_after_crash_flag = 1
                    break
            if rebound_after_crash_flag:
                break

    precursor_breakout_score = 0.0
    if ret_20d is not None and 5.0 <= ret_20d <= 40.0:
        precursor_breakout_score += min(ret_20d / 40.0, 1.0) * 35.0
    if volume_ratio_20_50 is not None and 1.1 <= volume_ratio_20_50 <= 2.5:
        precursor_breakout_score += min((volume_ratio_20_50 - 1.0) / 1.5, 1.0) * 30.0
    if price_vs_90d_high is not None and 0.85 <= price_vs_90d_high < 1.0:
        precursor_breakout_score += min((price_vs_90d_high - 0.85) / 0.15, 1.0) * 25.0
    if vol20 is not None and vol20 <= 12.0:
        precursor_breakout_score += max((12.0 - vol20) / 12.0, 0.0) * 10.0
    if one_day_100pct_flag:
        precursor_breakout_score = 0.0
    precursor_breakout_flag = (
        precursor_breakout_score >= 55.0
        and one_day_100pct_flag == 0
        and (ret_1d is None or ret_1d < 30.0)
    )

    bottom_watch_score = 0.0
    if drawdown_from_252d_high is not None and drawdown_from_252d_high <= -0.7:
        bottom_watch_score += min(abs(drawdown_from_252d_high) / 0.9, 1.0) * 40.0
    if last_close < 3.0:
        bottom_watch_score += 20.0
    if ret_5d is not None and -20.0 <= ret_5d <= 10.0:
        bottom_watch_score += 15.0
    if ret_20d is not None and ret_20d <= -30.0:
        bottom_watch_score += 15.0
    if crash_50pct_sub1_flag:
        bottom_watch_score += 10.0
    if rebound_after_crash_flag:
        bottom_watch_score -= 25.0
    bottom_watch_flag = (
        bottom_watch_score >= 55.0
        and rebound_after_crash_flag == 0
        and (ret_5d is None or ret_5d <= 15.0)
    )

    return precursor_breakout_flag, bottom_watch_flag


def simulate_exit(
    df,
    entry_idx: int,
    signal_type: str,
    precursor_target: float,
    precursor_stop: float,
    precursor_hold: int,
    bottom_target: float,
    bottom_stop: float,
    bottom_hold: int,
) -> Trade | None:
    if entry_idx >= len(df):
        return None

    entry_row = df.iloc[entry_idx]
    entry_open = safe_float(entry_row["Open"])
    if entry_open is None or entry_open <= 0:
        return None

    if signal_type == "precursor_breakout":
        target_mult = precursor_target
        stop_mult = precursor_stop
        max_hold = precursor_hold
    else:
        target_mult = bottom_target
        stop_mult = bottom_stop
        max_hold = bottom_hold

    entry_price = entry_open
    exit_idx = entry_idx
    exit_price = entry_price
    exit_reason = "max_hold"

    for i in range(entry_idx, min(len(df), entry_idx + max_hold)):
        row = df.iloc[i]
        high = safe_float(row["High"])
        low = safe_float(row["Low"])
        close = safe_float(row["Close"])
        if high is None or low is None or close is None:
            continue

        if low <= entry_price * stop_mult:
            exit_idx = i
            exit_price = entry_price * stop_mult
            exit_reason = "stop_loss"
            break
        if high >= entry_price * target_mult:
            exit_idx = i
            exit_price = entry_price * target_mult
            exit_reason = "take_profit"
            break

        exit_idx = i
        exit_price = close

    entry_date = df.index[entry_idx].date()
    exit_date = df.index[exit_idx].date()
    return_pct = ((exit_price / entry_price) - 1.0) * 100.0

    return Trade(
        symbol="",
        signal_type=signal_type,
        signal_date="",
        entry_date=entry_date.isoformat(),
        exit_date=exit_date.isoformat(),
        entry_price=round(entry_price, 4),
        exit_price=round(exit_price, 4),
        hold_days=(exit_date - entry_date).days,
        return_pct=round(return_pct, 2),
        exit_reason=exit_reason,
    )


def run_backtest(
    symbols: list[str],
    period: str,
    batch_size: int,
    precursor_target: float,
    precursor_stop: float,
    precursor_hold: int,
    bottom_target: float,
    bottom_stop: float,
    bottom_hold: int,
) -> list[Trade]:
    trades: list[Trade] = []

    for batch_no, batch in enumerate(batched(symbols, batch_size), start=1):
        df = yf.download(
            batch,
            period=period,
            auto_adjust=False,
            progress=False,
            threads=False,
            group_by="ticker",
        )

        for symbol in batch:
            try:
                sdf = df[symbol].copy()
            except Exception:
                continue
            if "Close" not in sdf.columns:
                continue
            sdf = sdf.dropna(subset=["Open", "High", "Low", "Close"])
            if len(sdf) < 100:
                continue

            last_entry_idx: dict[str, int] = {"precursor_breakout": -9999, "bottom_watch": -9999}

            for i in range(89, len(sdf) - 1):
                hist = sdf.iloc[: i + 1]
                precursor_flag, bottom_flag = make_signal(hist)

                for signal_type, flag in [
                    ("precursor_breakout", precursor_flag),
                    ("bottom_watch", bottom_flag),
                ]:
                    if not flag:
                        continue
                    if i - last_entry_idx[signal_type] < 15:
                        continue
                    sim = simulate_exit(
                        sdf,
                        i + 1,
                        signal_type,
                        precursor_target,
                        precursor_stop,
                        precursor_hold,
                        bottom_target,
                        bottom_stop,
                        bottom_hold,
                    )
                    if sim is None:
                        continue
                    sim.symbol = symbol
                    sim.signal_date = sdf.index[i].date().isoformat()
                    trades.append(sim)
                    last_entry_idx[signal_type] = i

        print(f"batch {batch_no} processed: {len(batch)} symbols", flush=True)

    return trades


def summarize(trades: list[Trade]) -> dict:
    by_type: dict[str, list[Trade]] = {}
    for trade in trades:
        by_type.setdefault(trade.signal_type, []).append(trade)

    summary: dict[str, dict] = {}
    for signal_type, rows in by_type.items():
        wins = [t for t in rows if t.return_pct > 0]
        losses = [t for t in rows if t.return_pct <= 0]
        avg_return = sum(t.return_pct for t in rows) / len(rows)
        tp = sum(1 for t in rows if t.exit_reason == "take_profit")
        sl = sum(1 for t in rows if t.exit_reason == "stop_loss")
        mh = sum(1 for t in rows if t.exit_reason == "max_hold")
        summary[signal_type] = {
            "trades": len(rows),
            "win_rate": round(len(wins) / len(rows), 4),
            "avg_return_pct": round(avg_return, 2),
            "median_return_pct": round(statistics.median(t.return_pct for t in rows), 2),
            "take_profit_rate": round(tp / len(rows), 4),
            "stop_loss_rate": round(sl / len(rows), 4),
            "max_hold_rate": round(mh / len(rows), 4),
            "best_return_pct": round(max(t.return_pct for t in rows), 2),
            "worst_return_pct": round(min(t.return_pct for t in rows), 2),
            "profit_factor": round(
                (sum(t.return_pct for t in wins) / abs(sum(t.return_pct for t in losses))) if losses and sum(t.return_pct for t in losses) != 0 else 999.0,
                2,
            ),
        }

    overall = {
        "trades": len(trades),
        "win_rate": round(sum(1 for t in trades if t.return_pct > 0) / len(trades), 4) if trades else 0.0,
        "avg_return_pct": round(sum(t.return_pct for t in trades) / len(trades), 2) if trades else 0.0,
    }
    return {"overall": overall, "by_signal_type": summary}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=300)
    parser.add_argument("--period", default="1y")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--precursor-target", type=float, default=1.20)
    parser.add_argument("--precursor-stop", type=float, default=0.90)
    parser.add_argument("--precursor-hold", type=int, default=10)
    parser.add_argument("--bottom-target", type=float, default=1.30)
    parser.add_argument("--bottom-stop", type=float, default=0.88)
    parser.add_argument("--bottom-hold", type=int, default=20)
    args = parser.parse_args()

    symbols = fetch_active_symbols(limit=args.limit)
    trades = run_backtest(
        symbols=symbols,
        period=args.period,
        batch_size=args.batch_size,
        precursor_target=args.precursor_target,
        precursor_stop=args.precursor_stop,
        precursor_hold=args.precursor_hold,
        bottom_target=args.bottom_target,
        bottom_stop=args.bottom_stop,
        bottom_hold=args.bottom_hold,
    )
    summary = summarize(trades)

    ts = date.today().strftime("%Y%m%d")
    summary_path = OUT_DIR / f"backtest_summary_{ts}.json"
    trades_path = OUT_DIR / f"backtest_trades_{ts}.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    trades_path.write_text(json.dumps([asdict(t) for t in trades], indent=2), encoding="utf-8")

    print(json.dumps({"summary_path": str(summary_path), "trades_path": str(trades_path), **summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
