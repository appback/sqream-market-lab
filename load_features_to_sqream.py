#!/usr/bin/env python3

from __future__ import annotations

import argparse
import statistics
import subprocess
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

from analyze_events import fetch_active_symbols


HOST = "192.168.0.26"
PORT = "3108"
DATABASE = "master"
USERNAME = "sqream"
PASSWORD = "sqream"
SERVICE = "sqream"
SQREAM_BIN = "/SQREAM/sqream-db-v4.4.0/bin/sqream"
BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = BASE_DIR / "output"
STAGING_DIR = BASE_DIR / "staging"


@dataclass
class FeatureRow:
    symbol: str
    as_of_date: str
    close: float
    volume: int
    ret_1d: float | None
    ret_5d: float | None
    ret_20d: float | None
    ret_60d: float | None
    range_pct: float | None
    volume_ratio_20_50: float | None
    price_vs_20dma: float | None
    price_vs_50dma: float | None
    price_vs_90d_high: float | None
    drawdown_from_252d_high: float | None
    volatility_20d: float | None
    one_day_100pct_flag: int
    crash_50pct_sub1_flag: int
    rebound_after_crash_flag: int
    surge_setup_flag: int
    breakout_score: float | None
    distress_rebound_score: float | None
    precursor_breakout_score: float | None
    bottom_watch_score: float | None
    precursor_breakout_flag: int
    bottom_watch_flag: int


@dataclass
class EventRow:
    symbol: str
    event_date: str
    event_type: str
    magnitude_pct: float
    close_price: float
    next_day_direction: str
    next_day_change_pct: float | None


def batched(seq: list[str], size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def pct(a: float, b: float) -> float | None:
    if b == 0:
        return None
    return (a / b) - 1.0


def safe_float(x) -> float | None:
    try:
        if x is None or (isinstance(x, float) and math.isnan(x)):
            return None
        return float(x)
    except Exception:
        return None


def bool_int(flag: bool) -> int:
    return 1 if flag else 0


def sql_num(v):
    return "null" if v is None or (isinstance(v, float) and math.isnan(v)) else str(v)


def sql_str(v: str) -> str:
    return "'" + v.replace("'", "''") + "'"


def compute_rows_for_symbol(symbol: str, sdf) -> tuple[FeatureRow | None, list[EventRow]]:
    if sdf is None or len(sdf) < 30:
        return None, []

    sdf = sdf.dropna(subset=["Close"])
    if len(sdf) < 30:
        return None, []

    close = sdf["Close"].astype(float)
    high = sdf["High"].astype(float)
    low = sdf["Low"].astype(float)
    volume = sdf["Volume"].fillna(0).astype(float)
    ret = close.pct_change()

    last = sdf.iloc[-1]
    as_of_date = sdf.index[-1].date().isoformat()
    last_close = float(last["Close"])
    last_volume = int(last["Volume"]) if not math.isnan(float(last["Volume"])) else 0

    ret_1d = safe_float(ret.iloc[-1] * 100.0) if len(ret) >= 2 else None
    ret_5d = safe_float(pct(last_close, float(close.iloc[-6])) * 100.0) if len(close) >= 6 else None
    ret_20d = safe_float(pct(last_close, float(close.iloc[-21])) * 100.0) if len(close) >= 21 else None
    ret_60d = safe_float(pct(last_close, float(close.iloc[-61])) * 100.0) if len(close) >= 61 else None
    range_pct = safe_float(((float(last["High"]) / float(last["Low"])) - 1.0) * 100.0) if float(last["Low"]) > 0 else None

    avg20v = statistics.mean(volume.iloc[-20:]) if len(volume) >= 20 else None
    avg50v = statistics.mean(volume.iloc[-50:]) if len(volume) >= 50 else None
    volume_ratio_20_50 = safe_float(avg20v / avg50v) if avg20v and avg50v and avg50v > 0 else None

    ma20 = statistics.mean(close.iloc[-20:]) if len(close) >= 20 else None
    ma50 = statistics.mean(close.iloc[-50:]) if len(close) >= 50 else None
    high90 = max(close.iloc[-90:]) if len(close) >= 90 else max(close)
    high252 = max(close.iloc[-252:]) if len(close) >= 252 else max(close)

    price_vs_20dma = safe_float((last_close / ma20) - 1.0) if ma20 else None
    price_vs_50dma = safe_float((last_close / ma50) - 1.0) if ma50 else None
    price_vs_90d_high = safe_float(last_close / high90) if high90 else None
    drawdown_from_252d_high = safe_float((last_close / high252) - 1.0) if high252 else None

    vol20 = None
    if len(ret.dropna()) >= 20:
        sample = [float(x) for x in ret.dropna().iloc[-20:]]
        vol20 = statistics.pstdev(sample) * 100.0

    one_day_100pct_flag = bool_int((ret.iloc[-1] if len(ret) else 0) >= 1.0)
    crash_50pct_sub1_flag = bool_int((ret.iloc[-1] if len(ret) else 0) <= -0.5 and last_close < 1.0)

    rebound_after_crash_flag = 0
    surge_setup_flag = 0
    if len(close) >= 21 and len(close) >= 90 and avg20v and avg50v and avg50v > 0:
        if ret_20d is not None and ret_20d >= 25.0 and price_vs_90d_high is not None and price_vs_90d_high >= 0.97 and volume_ratio_20_50 is not None and volume_ratio_20_50 >= 1.8:
            surge_setup_flag = 1

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

    breakout_score = 0.0
    if ret_20d is not None:
        breakout_score += max(min(ret_20d / 40.0, 1.0), -1.0) * 40.0
    if volume_ratio_20_50 is not None:
        breakout_score += max(min((volume_ratio_20_50 - 1.0) / 1.5, 1.0), -1.0) * 30.0
    if price_vs_90d_high is not None:
        breakout_score += max(min((price_vs_90d_high - 0.85) / 0.15, 1.0), -1.0) * 30.0
    breakout_score = round(max(min(breakout_score, 100.0), -100.0), 2)

    distress_rebound_score = 0.0
    if drawdown_from_252d_high is not None:
        distress_rebound_score += max(min(abs(drawdown_from_252d_high) / 0.8, 1.0), 0.0) * 35.0
    if rebound_after_crash_flag:
        distress_rebound_score += 35.0
    if crash_50pct_sub1_flag:
        distress_rebound_score += 20.0
    if ret_5d is not None and ret_5d > 0:
        distress_rebound_score += max(min(ret_5d / 50.0, 1.0), 0.0) * 10.0
    distress_rebound_score = round(max(min(distress_rebound_score, 100.0), 0.0), 2)

    # Precursor breakout: strength without already printing a 1-day blowoff.
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
    precursor_breakout_score = round(max(min(precursor_breakout_score, 100.0), 0.0), 2)
    precursor_breakout_flag = bool_int(
        precursor_breakout_score >= 55.0
        and one_day_100pct_flag == 0
        and (ret_1d is None or ret_1d < 30.0)
    )

    # Bottom watch: deeply sold-off names that have not yet meaningfully rebounded.
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
    bottom_watch_score = round(max(min(bottom_watch_score, 100.0), 0.0), 2)
    bottom_watch_flag = bool_int(
        bottom_watch_score >= 55.0
        and rebound_after_crash_flag == 0
        and (ret_5d is None or ret_5d <= 15.0)
    )

    feature = FeatureRow(
        symbol=symbol,
        as_of_date=as_of_date,
        close=round(last_close, 4),
        volume=last_volume,
        ret_1d=safe_float(ret_1d),
        ret_5d=safe_float(ret_5d),
        ret_20d=safe_float(ret_20d),
        ret_60d=safe_float(ret_60d),
        range_pct=safe_float(range_pct),
        volume_ratio_20_50=safe_float(volume_ratio_20_50),
        price_vs_20dma=safe_float(price_vs_20dma),
        price_vs_50dma=safe_float(price_vs_50dma),
        price_vs_90d_high=safe_float(price_vs_90d_high),
        drawdown_from_252d_high=safe_float(drawdown_from_252d_high),
        volatility_20d=safe_float(vol20),
        one_day_100pct_flag=one_day_100pct_flag,
        crash_50pct_sub1_flag=crash_50pct_sub1_flag,
        rebound_after_crash_flag=rebound_after_crash_flag,
        surge_setup_flag=surge_setup_flag,
        breakout_score=breakout_score,
        distress_rebound_score=distress_rebound_score,
        precursor_breakout_score=precursor_breakout_score,
        bottom_watch_score=bottom_watch_score,
        precursor_breakout_flag=precursor_breakout_flag,
        bottom_watch_flag=bottom_watch_flag,
    )

    events: list[EventRow] = []
    for i in range(1, len(close)):
        day_ret = float(ret.iloc[i]) if not math.isnan(float(ret.iloc[i])) else None
        if day_ret is None:
            continue
        next_dir = "no_next_day"
        next_chg = None
        if i + 1 < len(close):
            c0 = float(close.iloc[i])
            c1 = float(close.iloc[i + 1])
            next_chg = ((c1 / c0) - 1.0) * 100.0
            if c1 > c0:
                next_dir = "up"
            elif c1 < c0:
                next_dir = "down"
            else:
                next_dir = "flat"
        if day_ret >= 1.0:
            events.append(
                EventRow(
                    symbol=symbol,
                    event_date=sdf.index[i].date().isoformat(),
                    event_type="one_day_100pct",
                    magnitude_pct=round(day_ret * 100.0, 2),
                    close_price=round(float(close.iloc[i]), 4),
                    next_day_direction=next_dir,
                    next_day_change_pct=round(next_chg, 2) if next_chg is not None else None,
                )
            )
        if day_ret <= -0.5 and float(close.iloc[i]) < 1.0:
            events.append(
                EventRow(
                    symbol=symbol,
                    event_date=sdf.index[i].date().isoformat(),
                    event_type="crash_50pct_sub1",
                    magnitude_pct=round(day_ret * 100.0, 2),
                    close_price=round(float(close.iloc[i]), 4),
                    next_day_direction=next_dir,
                    next_day_change_pct=round(next_chg, 2) if next_chg is not None else None,
                )
            )

    return feature, events


def build_sql(features: list[FeatureRow], events: list[EventRow]) -> str:
    lines = [
        "create or replace table market_analysis.symbol_features (",
        "  symbol text(32),",
        "  as_of_date text(10),",
        "  close_price float,",
        "  volume_count int,",
        "  ret_1d float,",
        "  ret_5d float,",
        "  ret_20d float,",
        "  ret_60d float,",
        "  range_pct float,",
        "  volume_ratio_20_50 float,",
        "  price_vs_20dma float,",
        "  price_vs_50dma float,",
        "  price_vs_90d_high float,",
        "  drawdown_from_252d_high float,",
        "  volatility_20d float,",
        "  one_day_100pct_flag int,",
        "  crash_50pct_sub1_flag int,",
        "  rebound_after_crash_flag int,",
        "  surge_setup_flag int,",
        "  breakout_score float,",
        "  distress_rebound_score float,",
        "  precursor_breakout_score float,",
        "  bottom_watch_score float,",
        "  precursor_breakout_flag int,",
        "  bottom_watch_flag int",
        ");",
        "create or replace table market_analysis.symbol_events (",
        "  symbol text(32),",
        "  event_date text(10),",
        "  event_type text(32),",
        "  magnitude_pct float,",
        "  close_price float,",
        "  next_day_direction text(16),",
        "  next_day_change_pct float",
        ");",
    ]

    for row in features:
        lines.append(
            "insert into market_analysis.symbol_features values ("
            f"{sql_str(row.symbol)}, {sql_str(row.as_of_date)}, {sql_num(row.close)}, {row.volume}, "
            f"{sql_num(row.ret_1d)}, {sql_num(row.ret_5d)}, {sql_num(row.ret_20d)}, {sql_num(row.ret_60d)}, "
            f"{sql_num(row.range_pct)}, {sql_num(row.volume_ratio_20_50)}, {sql_num(row.price_vs_20dma)}, "
            f"{sql_num(row.price_vs_50dma)}, {sql_num(row.price_vs_90d_high)}, {sql_num(row.drawdown_from_252d_high)}, "
            f"{sql_num(row.volatility_20d)}, {row.one_day_100pct_flag}, {row.crash_50pct_sub1_flag}, "
            f"{row.rebound_after_crash_flag}, {row.surge_setup_flag}, {sql_num(row.breakout_score)}, "
            f"{sql_num(row.distress_rebound_score)}, {sql_num(row.precursor_breakout_score)}, "
            f"{sql_num(row.bottom_watch_score)}, {row.precursor_breakout_flag}, {row.bottom_watch_flag});"
        )

    for row in events:
        lines.append(
            "insert into market_analysis.symbol_events values ("
            f"{sql_str(row.symbol)}, {sql_str(row.event_date)}, {sql_str(row.event_type)}, "
            f"{sql_num(row.magnitude_pct)}, {sql_num(row.close_price)}, {sql_str(row.next_day_direction)}, "
            f"{sql_num(row.next_day_change_pct)});"
        )

    lines.append("select count(*) from market_analysis.symbol_features;")
    lines.append("select count(*) from market_analysis.symbol_events;")
    return "\n".join(lines)


def build_schema_sql() -> str:
    return "\n".join(
        [
            "create or replace table market_analysis.symbol_features (",
            "  symbol text(32),",
            "  as_of_date text(10),",
            "  close_price float,",
            "  volume_count int,",
            "  ret_1d float,",
            "  ret_5d float,",
            "  ret_20d float,",
            "  ret_60d float,",
            "  range_pct float,",
            "  volume_ratio_20_50 float,",
            "  price_vs_20dma float,",
            "  price_vs_50dma float,",
            "  price_vs_90d_high float,",
            "  drawdown_from_252d_high float,",
            "  volatility_20d float,",
            "  one_day_100pct_flag int,",
            "  crash_50pct_sub1_flag int,",
            "  rebound_after_crash_flag int,",
            "  surge_setup_flag int,",
            "  breakout_score float,",
            "  distress_rebound_score float,",
            "  precursor_breakout_score float,",
            "  bottom_watch_score float,",
            "  precursor_breakout_flag int,",
            "  bottom_watch_flag int",
            ");",
            "create or replace table market_analysis.symbol_events (",
            "  symbol text(32),",
            "  event_date text(10),",
            "  event_type text(32),",
            "  magnitude_pct float,",
            "  close_price float,",
            "  next_day_direction text(16),",
            "  next_day_change_pct float",
            ");",
        ]
    )


def write_feature_parquet(path: Path, features: list[FeatureRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "symbol": row.symbol,
            "as_of_date": row.as_of_date,
            "close_price": row.close,
            "volume_count": row.volume,
            "ret_1d": row.ret_1d,
            "ret_5d": row.ret_5d,
            "ret_20d": row.ret_20d,
            "ret_60d": row.ret_60d,
            "range_pct": row.range_pct,
            "volume_ratio_20_50": row.volume_ratio_20_50,
            "price_vs_20dma": row.price_vs_20dma,
            "price_vs_50dma": row.price_vs_50dma,
            "price_vs_90d_high": row.price_vs_90d_high,
            "drawdown_from_252d_high": row.drawdown_from_252d_high,
            "volatility_20d": row.volatility_20d,
            "one_day_100pct_flag": row.one_day_100pct_flag,
            "crash_50pct_sub1_flag": row.crash_50pct_sub1_flag,
            "rebound_after_crash_flag": row.rebound_after_crash_flag,
            "surge_setup_flag": row.surge_setup_flag,
            "breakout_score": row.breakout_score,
            "distress_rebound_score": row.distress_rebound_score,
            "precursor_breakout_score": row.precursor_breakout_score,
            "bottom_watch_score": row.bottom_watch_score,
            "precursor_breakout_flag": row.precursor_breakout_flag,
            "bottom_watch_flag": row.bottom_watch_flag,
        }
        for row in features
    ]
    df = pd.DataFrame(rows)
    int_columns = [
        "volume_count",
        "one_day_100pct_flag",
        "crash_50pct_sub1_flag",
        "rebound_after_crash_flag",
        "surge_setup_flag",
        "precursor_breakout_flag",
        "bottom_watch_flag",
    ]
    for column in int_columns:
        df[column] = df[column].astype("int32")
    df.to_parquet(path, index=False)


def write_event_parquet(path: Path, events: list[EventRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "symbol",
        "event_date",
        "event_type",
        "magnitude_pct",
        "close_price",
        "next_day_direction",
        "next_day_change_pct",
    ]
    rows = [
        {
            "symbol": row.symbol,
            "event_date": row.event_date,
            "event_type": row.event_type,
            "magnitude_pct": row.magnitude_pct,
            "close_price": row.close_price,
            "next_day_direction": row.next_day_direction,
            "next_day_change_pct": row.next_day_change_pct,
        }
        for row in events
    ]
    df = pd.DataFrame(rows, columns=columns)
    for column in ["symbol", "event_date", "event_type", "next_day_direction"]:
        df[column] = df[column].astype("string")
    for column in ["magnitude_pct", "close_price", "next_day_change_pct"]:
        df[column] = df[column].astype("float64")
    df.to_parquet(path, index=False)


def build_copy_from_parquet_sql(feature_path: str, event_path: str) -> str:
    feature_file = feature_path.replace("'", "''")
    event_file = event_path.replace("'", "''")
    return "\n".join(
        [
            f"COPY market_analysis.symbol_features FROM WRAPPER parquet_fdw OPTIONS (LOCATION = '{feature_file}');",
            f"COPY market_analysis.symbol_events FROM WRAPPER parquet_fdw OPTIONS (LOCATION = '{event_file}');",
            "select count(*) from market_analysis.symbol_features;",
            "select count(*) from market_analysis.symbol_events;",
        ]
    )


def build_foreign_table_parquet_sql(feature_path: str, event_path: str) -> str:
    feature_file = feature_path.replace("'", "''")
    event_file = event_path.replace("'", "''")
    return "\n".join(
        [
            "create or replace foreign table market_analysis.symbol_features_stage (",
            "  symbol text(32),",
            "  as_of_date text(10),",
            "  close_price float,",
            "  volume_count int,",
            "  ret_1d float,",
            "  ret_5d float,",
            "  ret_20d float,",
            "  ret_60d float,",
            "  range_pct float,",
            "  volume_ratio_20_50 float,",
            "  price_vs_20dma float,",
            "  price_vs_50dma float,",
            "  price_vs_90d_high float,",
            "  drawdown_from_252d_high float,",
            "  volatility_20d float,",
            "  one_day_100pct_flag int,",
            "  crash_50pct_sub1_flag int,",
            "  rebound_after_crash_flag int,",
            "  surge_setup_flag int,",
            "  breakout_score float,",
            "  distress_rebound_score float,",
            "  precursor_breakout_score float,",
            "  bottom_watch_score float,",
            "  precursor_breakout_flag int,",
            "  bottom_watch_flag int",
            ")",
            "wrapper parquet_fdw",
            f"options (location = '{feature_file}');",
            "create or replace foreign table market_analysis.symbol_events_stage (",
            "  symbol text(32),",
            "  event_date text(10),",
            "  event_type text(32),",
            "  magnitude_pct float,",
            "  close_price float,",
            "  next_day_direction text(16),",
            "  next_day_change_pct float",
            ")",
            "wrapper parquet_fdw",
            f"options (location = '{event_file}');",
            "insert into market_analysis.symbol_features select * from market_analysis.symbol_features_stage;",
            "insert into market_analysis.symbol_events select * from market_analysis.symbol_events_stage;",
            "select count(*) from market_analysis.symbol_features;",
            "select count(*) from market_analysis.symbol_events;",
        ]
    )


def build_batch_insert_sql(features: list[FeatureRow], events: list[EventRow]) -> str:
    lines: list[str] = []
    for row in features:
        lines.append(
            "insert into market_analysis.symbol_features values ("
            f"{sql_str(row.symbol)}, {sql_str(row.as_of_date)}, {sql_num(row.close)}, {row.volume}, "
            f"{sql_num(row.ret_1d)}, {sql_num(row.ret_5d)}, {sql_num(row.ret_20d)}, {sql_num(row.ret_60d)}, "
            f"{sql_num(row.range_pct)}, {sql_num(row.volume_ratio_20_50)}, {sql_num(row.price_vs_20dma)}, "
            f"{sql_num(row.price_vs_50dma)}, {sql_num(row.price_vs_90d_high)}, {sql_num(row.drawdown_from_252d_high)}, "
            f"{sql_num(row.volatility_20d)}, {row.one_day_100pct_flag}, {row.crash_50pct_sub1_flag}, "
            f"{row.rebound_after_crash_flag}, {row.surge_setup_flag}, {sql_num(row.breakout_score)}, "
            f"{sql_num(row.distress_rebound_score)}, {sql_num(row.precursor_breakout_score)}, "
            f"{sql_num(row.bottom_watch_score)}, {row.precursor_breakout_flag}, {row.bottom_watch_flag});"
        )

    for row in events:
        lines.append(
            "insert into market_analysis.symbol_events values ("
            f"{sql_str(row.symbol)}, {sql_str(row.event_date)}, {sql_str(row.event_type)}, "
            f"{sql_num(row.magnitude_pct)}, {sql_num(row.close_price)}, {sql_str(row.next_day_direction)}, "
            f"{sql_num(row.next_day_change_pct)});"
        )

    lines.append("select count(*) from market_analysis.symbol_features;")
    lines.append("select count(*) from market_analysis.symbol_events;")
    return "\n".join(lines)


def run_sqream(sql_file: str) -> str:
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
        sql_file,
        "--results-only=true",
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument(
        "--load-mode",
        choices=["stage-only-parquet", "copy-from-parquet", "foreign-table-parquet"],
        default="foreign-table-parquet",
    )
    parser.add_argument("--staging-dir", default=str(STAGING_DIR))
    parser.add_argument("--sqream-load-path")
    args = parser.parse_args()

    symbols = fetch_active_symbols()[: args.limit]
    staging_dir = Path(args.staging_dir)
    schema_sql_path = "/tmp/load_symbol_features_schema.sql"
    Path(schema_sql_path).write_text(build_schema_sql())
    run_sqream(schema_sql_path)

    total_features = 0
    total_events = 0

    for batch_no, batch in enumerate(batched(symbols, args.batch_size), start=1):
        features: list[FeatureRow] = []
        events: list[EventRow] = []
        df = yf.download(batch, period="1y", auto_adjust=False, progress=False, threads=False, group_by="ticker")
        for symbol in batch:
            try:
                sdf = df[symbol].copy()
            except Exception:
                continue
            feature, symbol_events = compute_rows_for_symbol(symbol, sdf)
            if feature:
                features.append(feature)
            events.extend(symbol_events)
        feature_parquet_path = staging_dir / f"symbol_features_batch_{batch_no}.parquet"
        event_parquet_path = staging_dir / f"symbol_events_batch_{batch_no}.parquet"
        write_feature_parquet(feature_parquet_path, features)
        write_event_parquet(event_parquet_path, events)
        if args.load_mode == "copy-from-parquet":
            if not args.sqream_load_path:
                raise SystemExit("--sqream-load-path is required for --load-mode copy-from-parquet")
            feature_load_path = f"{args.sqream_load_path.rstrip('/')}/{feature_parquet_path.name}"
            event_load_path = f"{args.sqream_load_path.rstrip('/')}/{event_parquet_path.name}"
            sql = build_copy_from_parquet_sql(feature_load_path, event_load_path)
            sql_path = f"/tmp/load_symbol_features_copy_parquet_batch_{batch_no}.sql"
            Path(sql_path).write_text(sql)
            out = run_sqream(sql_path)
        elif args.load_mode == "foreign-table-parquet":
            if not args.sqream_load_path:
                raise SystemExit("--sqream-load-path is required for --load-mode foreign-table-parquet")
            feature_load_path = f"{args.sqream_load_path.rstrip('/')}/{feature_parquet_path.name}"
            event_load_path = f"{args.sqream_load_path.rstrip('/')}/{event_parquet_path.name}"
            sql = build_foreign_table_parquet_sql(feature_load_path, event_load_path)
            sql_path = f"/tmp/load_symbol_features_foreign_parquet_batch_{batch_no}.sql"
            Path(sql_path).write_text(sql)
            out = run_sqream(sql_path)
        elif args.load_mode == "stage-only-parquet":
            out = f"staged_only_parquet batch={batch_no} features_parquet={feature_parquet_path} events_parquet={event_parquet_path}"
        else:
            raise SystemExit(f"unsupported parquet load mode: {args.load_mode}")
        total_features += len(features)
        total_events += len(events)
        print(
            f"feature batch {batch_no} processed: {len(batch)} symbols, "
            f"batch_features={len(features)}, batch_events={len(events)}, "
            f"total_features={total_features}, total_events={total_events}",
            flush=True,
        )
        time.sleep(1.0)

    (OUT_DIR / "symbol_feature_load_result.txt").write_text(out)
    print(f"features={total_features} events={total_events}")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
