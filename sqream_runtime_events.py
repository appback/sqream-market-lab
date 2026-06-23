#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from report_notifier import notify, notify_error
from market_calendar import market_closed_reason


BASE_DIR = Path(__file__).resolve().parent
STATE_DIR = BASE_DIR / "state"
LOG_DIR = BASE_DIR / "logs"
STATE_PATH = STATE_DIR / "runtime_state.json"
TRADE_LEDGER_PATH = STATE_DIR / "paper_trade_ledger.jsonl"
NY_TZ = ZoneInfo("America/New_York")
ALGORITHM_NAME = "surge_pullback_35_target25_stop15_eod"
D1_ALGORITHM_NAME = "d1_vol5_absret10_breakout_2_target10_stop5_eod"
SIDEWAYS_ALGORITHM_NAME = "sideways_vwap_reversion_3_target_stop_cost"
SIDEWAYS_ROUND_TRIP_COST_PCT = 0.5
SIDEWAYS_TARGET_FILL_CUSHION_PCT = 0.5
SIDEWAYS_MAX_ENTRY_SLIPPAGE_PCT = 0.5
DEFAULT_RUNTIME_REGIME = "unknown"
DEFAULT_TIME_BUCKET = "unknown"

SQREAM_HOST = "192.168.0.26"
SQREAM_PORT = "3108"
SQREAM_DATABASE = "master"
SQREAM_USERNAME = "sqream"
SQREAM_PASSWORD = "sqream"
SQREAM_SERVICE = os.environ.get("SQREAM_SERVICE", "sqream")
SQREAM_BIN = "/SQREAM/sqream-db-v4.4.0/bin/sqream"


@dataclass
class SurgeSymbol:
    symbol: str
    first_signal_time: str
    max_day_return_pct: float
    max_close_price: float
    entry_price: float
    target_price: float
    stop_price: float


@dataclass
class PreSurgeWatchSymbol:
    symbol: str
    last_bar_time: str
    last_close: float
    total_volume: float
    day_return_pct: float
    intraday_range_pct: float
    minute_volume_burst_x: float
    high_from_open_pct: float


@dataclass
class D1Vol5Absret10Symbol:
    symbol: str
    signal_date: str
    close_price: float
    volume_count: int
    avg20_volume: float
    volume_x20: float
    ret_pct: float
    entry_price: float
    target_price: float
    stop_price: float


@dataclass
class StrategyTradeTarget:
    strategy_name: str
    symbol: str
    signal_time: str
    reference_price: float
    entry_price: float
    target_price: float
    stop_price: float
    score: float
    return_pct: float


@dataclass
class RuntimeStrategyPolicy:
    latest_bar_time: str
    latest_hhmm: str
    time_bucket: str
    regime: str
    allocation_rule: str
    surge_enabled: bool
    d1_enabled: bool
    sideways_enabled: bool
    position_size_multiplier: float
    max_new_sideways_positions: int
    rule_text: str


def sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def run_sqream_sql(sql: str, *, check: bool = True) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".sql", prefix="sqream_runtime_events_", delete=False) as f:
        f.write(sql)
        sql_path = Path(f.name)
    try:
        cmd = [
            SQREAM_BIN,
            "sql",
            "--host",
            SQREAM_HOST,
            "--port",
            SQREAM_PORT,
            "--database",
            SQREAM_DATABASE,
            "--username",
            SQREAM_USERNAME,
            "--password",
            SQREAM_PASSWORD,
            "--clustered=true",
            "--service",
            SQREAM_SERVICE,
            "--file",
            str(sql_path),
            "--results-only=true",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0 and check:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        return result.stdout.strip()
    finally:
        sql_path.unlink(missing_ok=True)


def ensure_runtime_objects() -> None:
    run_sqream_sql("create schema market_rt;", check=False)
    exists = run_sqream_sql("select count(*) from market_rt.report_events;", check=False)
    if not exists.strip():
        run_sqream_sql(
            """
create table market_rt.report_events (
  created_at text(32),
  event_type text(32),
  message text(512)
);
"""
        )
    paper_exists = run_sqream_sql("select count(*) from market_rt.paper_trade_ledger;", check=False)
    if not paper_exists.strip():
        run_sqream_sql(
            """
create table market_rt.paper_trade_ledger (
  trade_date text(10),
  algorithm text(64),
  symbol text(16),
  opened_at text(32),
  closed_at text(32),
  entry_price double,
  exit_price double,
  pnl_pct double,
  reason text(16)
);
"""
        )


def load_state() -> dict:
    STATE_DIR.mkdir(exist_ok=True)
    if not STATE_PATH.exists():
        return {"detected": {}, "positions": {}, "closed": []}
    state = json.loads(STATE_PATH.read_text())
    state.setdefault("detected", {})
    state.setdefault("pre_surge_watch", {})
    state.setdefault("d1_vol5_absret10_watch", {})
    state.setdefault("positions", {})
    state.setdefault("closed", [])
    return state


def save_state(state: dict) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True))


def build_trade_ledger_row(symbol: str, position: dict) -> dict:
    closed_at = str(position.get("closed_at", ""))
    opened_at = str(position.get("opened_at", ""))
    if closed_at.startswith("20") and len(closed_at) >= 10:
        trade_date = closed_at[:10]
    elif opened_at.startswith("20") and len(opened_at) >= 10:
        trade_date = opened_at[:10]
    else:
        trade_date = datetime.now(NY_TZ).date().isoformat()
    row = {
        "trade_date": trade_date,
        "algorithm": position.get("algorithm", ALGORITHM_NAME),
        "symbol": symbol,
        "opened_at": position.get("opened_at"),
        "closed_at": position.get("closed_at"),
        "entry_price": position.get("entry_price"),
        "exit_price": position.get("exit_price"),
        "pnl_pct": position.get("pnl_pct"),
        "reason": position.get("reason"),
    }
    return row


def insert_trade_ledger_row(row: dict) -> None:
    run_sqream_sql(
        "insert into market_rt.paper_trade_ledger values ("
        f"{sql_str(str(row['trade_date']))}, "
        f"{sql_str(str(row['algorithm']))}, "
        f"{sql_str(str(row['symbol']))}, "
        f"{sql_str(str(row.get('opened_at') or ''))}, "
        f"{sql_str(str(row.get('closed_at') or ''))}, "
        f"{float(row.get('entry_price') or 0.0)}, "
        f"{float(row.get('exit_price') or 0.0)}, "
        f"{float(row.get('pnl_pct') or 0.0)}, "
        f"{sql_str(str(row.get('reason') or ''))});"
    )


def append_trade_ledger(symbol: str, position: dict) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    row = build_trade_ledger_row(symbol, position)
    key = (row["algorithm"], row["symbol"], row["opened_at"], row["closed_at"], row["reason"])
    for existing in load_trade_ledger():
        existing_key = (
            existing.get("algorithm"),
            existing.get("symbol"),
            existing.get("opened_at"),
            existing.get("closed_at"),
            existing.get("reason"),
        )
        if existing_key == key:
            return
    with TRADE_LEDGER_PATH.open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    insert_trade_ledger_row(row)


def load_trade_ledger() -> list[dict]:
    if not TRADE_LEDGER_PATH.exists():
        return []
    rows = []
    for line in TRADE_LEDGER_PATH.read_text().splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def summarize_trades(rows: list[dict]) -> dict:
    pnls = [float(row.get("pnl_pct", 0.0)) for row in rows]
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl <= 0]
    return {
        "trades": len(pnls),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (len(wins) / len(pnls) * 100.0) if pnls else 0.0,
        "avg_pnl": (sum(pnls) / len(pnls)) if pnls else 0.0,
        "total_pnl": sum(pnls),
        "best": max(pnls) if pnls else 0.0,
        "worst": min(pnls) if pnls else 0.0,
    }


def recent_trading_day_rows(days: int = 10) -> list[dict]:
    rows = load_trade_ledger()
    dates = sorted({row.get("trade_date") for row in rows if row.get("trade_date")}, reverse=True)[:days]
    date_set = set(dates)
    return [row for row in rows if row.get("trade_date") in date_set]


def reset_daily_state() -> dict:
    return {"detected": {}, "pre_surge_watch": {}, "d1_vol5_absret10_watch": {}, "positions": {}, "closed": []}


def position_key(algorithm: str, symbol: str) -> str:
    return f"{algorithm}:{symbol}"


def position_symbol(key: str, position: dict) -> str:
    if position.get("symbol"):
        return str(position["symbol"])
    if ":" in key:
        return key.split(":", 1)[1]
    return key


def persist_report_event(created_at: str, event_type: str, text: str) -> None:
    run_sqream_sql(
        "insert into market_rt.report_events values ("
        f"{sql_str(created_at)}, {sql_str(event_type)}, {sql_str(text)});"
    )


def report(event_type: str, text: str, payload: dict | None = None) -> None:
    notify(event_type, text, payload, persist_report=persist_report_event)


def parse_surge_symbols(out: str) -> list[SurgeSymbol]:
    rows: list[SurgeSymbol] = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 7:
            continue
        rows.append(
            SurgeSymbol(
                symbol=parts[0],
                first_signal_time=parts[1],
                max_day_return_pct=float(parts[2]),
                max_close_price=float(parts[3]),
                entry_price=float(parts[4]),
                target_price=float(parts[5]),
                stop_price=float(parts[6]),
            )
        )
    return rows


def parse_pre_surge_watch_symbols(out: str) -> list[PreSurgeWatchSymbol]:
    rows: list[PreSurgeWatchSymbol] = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 8:
            continue
        rows.append(
            PreSurgeWatchSymbol(
                symbol=parts[0],
                last_bar_time=parts[1],
                last_close=float(parts[2]),
                total_volume=float(parts[3]),
                day_return_pct=float(parts[4]),
                intraday_range_pct=float(parts[5]),
                minute_volume_burst_x=float(parts[6]),
                high_from_open_pct=float(parts[7]),
            )
        )
    return rows


def parse_d1_vol5_absret10_symbols(out: str) -> list[D1Vol5Absret10Symbol]:
    rows: list[D1Vol5Absret10Symbol] = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 10:
            continue
        rows.append(
            D1Vol5Absret10Symbol(
                symbol=parts[0],
                signal_date=parts[1],
                close_price=float(parts[2]),
                volume_count=int(float(parts[3])),
                avg20_volume=float(parts[4]),
                volume_x20=float(parts[5]),
                ret_pct=float(parts[6]),
                entry_price=float(parts[7]),
                target_price=float(parts[8]),
                stop_price=float(parts[9]),
            )
        )
    return rows


def parse_strategy_trade_targets(out: str) -> list[StrategyTradeTarget]:
    rows: list[StrategyTradeTarget] = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 9:
            continue
        rows.append(
            StrategyTradeTarget(
                strategy_name=parts[0],
                symbol=parts[1],
                signal_time=parts[2],
                reference_price=float(parts[3]),
                entry_price=float(parts[4]),
                target_price=float(parts[5]),
                stop_price=float(parts[6]),
                score=float(parts[7]),
                return_pct=float(parts[8]),
            )
        )
    return rows


def fetch_runtime_strategy_policy() -> RuntimeStrategyPolicy:
    out = run_sqream_sql(
        """
select
  p.latest_bar_time,
  p.latest_hhmm,
  p.time_bucket,
  r.regime,
  r.recommended_allocation_rule,
  p.surge_enabled,
  p.d1_enabled,
  p.sideways_enabled,
  p.position_size_multiplier,
  p.max_new_sideways_positions,
  p.rule_text
from market_rt.current_time_strategy_policy p
join market_rt.market_regime_current r
  on 1 = 1
limit 1;
""",
        check=False,
    )
    parts = [p.strip() for p in out.split(",")]
    if len(parts) < 11:
        return RuntimeStrategyPolicy(
            latest_bar_time="",
            latest_hhmm="",
            time_bucket=DEFAULT_TIME_BUCKET,
            regime=DEFAULT_RUNTIME_REGIME,
            allocation_rule="fallback_no_policy",
            surge_enabled=True,
            d1_enabled=True,
            sideways_enabled=False,
            position_size_multiplier=0.25,
            max_new_sideways_positions=0,
            rule_text="fallback policy; SQream time/regime policy unavailable",
        )
    regime = parts[3]
    surge_enabled = parts[5] == "1"
    d1_enabled = parts[6] == "1"
    sideways_enabled = parts[7] == "1"
    size_multiplier = float(parts[8])
    max_new_sideways = int(float(parts[9]))
    if regime == "downtrend":
        surge_enabled = False
        d1_enabled = False
        sideways_enabled = False
        size_multiplier = min(size_multiplier, 0.20)
        max_new_sideways = 0
    elif regime == "uptrend":
        sideways_enabled = False
    elif regime != "sideways":
        sideways_enabled = False
        size_multiplier = min(size_multiplier, 0.40)
    return RuntimeStrategyPolicy(
        latest_bar_time=parts[0],
        latest_hhmm=parts[1],
        time_bucket=parts[2],
        regime=regime,
        allocation_rule=parts[4],
        surge_enabled=surge_enabled,
        d1_enabled=d1_enabled,
        sideways_enabled=sideways_enabled,
        position_size_multiplier=size_multiplier,
        max_new_sideways_positions=max_new_sideways,
        rule_text=parts[10],
    )


def fetch_detected_symbols(limit: int) -> list[SurgeSymbol]:
    out = run_sqream_sql(
        f"""
select
  symbol,
  first_signal_time,
  max_day_return_pct,
  max_close_price,
  min_pullback_35_entry_price,
  max_target_price,
  min_stop_price
from market_rt.delayed_surge_symbols_all
order by max_day_return_pct desc
limit {limit};
"""
    )
    return parse_surge_symbols(out)


def fetch_pre_surge_watch_symbols(limit: int) -> list[PreSurgeWatchSymbol]:
    out = run_sqream_sql(
        f"""
select
  symbol,
  last_bar_time,
  last_close,
  total_volume,
  day_return_pct,
  intraday_range_pct,
  minute_volume_burst_x,
  high_from_open_pct
from market_rt.delayed_pre_surge_watch_symbols_all
order by minute_volume_burst_x desc, total_volume desc
limit {limit};
"""
    )
    return parse_pre_surge_watch_symbols(out)


def fetch_d1_vol5_absret10_symbols(limit: int) -> list[D1Vol5Absret10Symbol]:
    out = run_sqream_sql(
        f"""
select
  t.symbol,
  t.signal_time,
  t.reference_price,
  d.volume_count,
  d.avg20_volume,
  t.score,
  t.return_pct,
  t.entry_price,
  t.target_price,
  t.stop_price
from market_rt.strategy_trade_targets t
join market_rt.d1_vol5_absret10_candidates d
  on t.symbol = d.symbol
 and t.signal_time = d.signal_date
where t.strategy_name = {sql_str(D1_ALGORITHM_NAME)}
order by t.score desc
limit {limit};
""",
        check=False,
    )
    return parse_d1_vol5_absret10_symbols(out)


def fetch_sideways_vwap_reversion_targets(limit: int) -> list[StrategyTradeTarget]:
    out = run_sqream_sql(
        f"""
select
  strategy_name,
  symbol,
  signal_time,
  reference_price,
  entry_price,
  target_price,
  stop_price,
  score,
  return_pct
from market_rt.strategy_trade_targets
where strategy_name = {sql_str(SIDEWAYS_ALGORITHM_NAME)}
order by signal_time desc, score desc
limit {limit};
""",
        check=False,
    )
    return parse_strategy_trade_targets(out)


def fetch_symbol_range(symbol: str, start_time: str) -> tuple[float, float, str] | None:
    out = run_sqream_sql(
        f"""
select
  max(high_price),
  min(low_price),
  max(bar_time)
from market_rt.delayed_intraday_bars_latest
where symbol = {sql_str(symbol)}
  and bar_time >= {sql_str(start_time)};
"""
    )
    parts = [p.strip() for p in out.split(",")]
    if len(parts) < 3 or not parts[0] or not parts[1]:
        return None
    if parts[0] in {"\\N", "null"} or parts[1] in {"\\N", "null"}:
        return None
    return float(parts[0]), float(parts[1]), parts[2]


def fetch_latest_price(symbol: str) -> tuple[str, float] | None:
    for table_name in ["market_rt.delayed_intraday_bars_latest", "market_rt.delayed_intraday_bars_raw"]:
        out = run_sqream_sql(
            f"""
select bar_time, close_price
from {table_name}
where symbol = {sql_str(symbol)}
order by bar_time desc
limit 1;
"""
        )
        parts = [p.strip() for p in out.split(",")]
        if len(parts) >= 2 and parts[0] not in {"", "\\N", "null"} and parts[1] not in {"", "\\N", "null"}:
            return parts[0], float(parts[1])
    return None


def record_detection(state: dict, item: SurgeSymbol) -> None:
    if item.symbol in state["detected"]:
        return
    state["detected"][item.symbol] = {
        "first_signal_time": item.first_signal_time,
        "max_day_return_pct": item.max_day_return_pct,
        "max_close_price": item.max_close_price,
        "entry_price": item.entry_price,
        "target_price": item.target_price,
        "stop_price": item.stop_price,
    }
    report(
        "매수후보 감지",
        (
            f"[매수후보 감지] 종목={item.symbol} 구분=급등후눌림 "
            f"상태=진입조건대기 현재상승={item.max_day_return_pct:.1f}% "
            f"신호시각={item.first_signal_time} 매수가={item.entry_price:.4f} "
            f"목표가={item.target_price:.4f} 손절가={item.stop_price:.4f}"
        ),
        state["detected"][item.symbol],
    )


def record_pre_surge_watch(state: dict, item: PreSurgeWatchSymbol) -> None:
    if item.symbol in state["pre_surge_watch"]:
        return
    state["pre_surge_watch"][item.symbol] = {
        "strategy": "pre_surge_watch",
        "last_bar_time": item.last_bar_time,
        "last_close": item.last_close,
        "total_volume": item.total_volume,
        "day_return_pct": item.day_return_pct,
        "intraday_range_pct": item.intraday_range_pct,
        "minute_volume_burst_x": item.minute_volume_burst_x,
        "high_from_open_pct": item.high_from_open_pct,
    }
    report(
        "감시대상",
        (
            f"[감시대상] 종목={item.symbol} 전략=pre_surge_watch "
            "매수여부=아님 상태=감시전용 "
            f"시각={item.last_bar_time} 현재가={item.last_close:.4f} "
            f"당일등락={item.day_return_pct:.1f}% 변동폭={item.intraday_range_pct:.1f}% "
            f"거래량폭증={item.minute_volume_burst_x:.1f}x 누적거래량={item.total_volume:.0f}"
        ),
        state["pre_surge_watch"][item.symbol],
    )


def record_d1_vol5_absret10_watch(state: dict, item: D1Vol5Absret10Symbol) -> None:
    if item.symbol in state["d1_vol5_absret10_watch"]:
        return
    state["d1_vol5_absret10_watch"][item.symbol] = {
        "strategy": "d1_vol5_absret10",
        "signal_date": item.signal_date,
        "close_price": item.close_price,
        "volume_count": item.volume_count,
        "avg20_volume": item.avg20_volume,
        "volume_x20": item.volume_x20,
        "ret_pct": item.ret_pct,
        "entry_price": item.entry_price,
        "target_price": item.target_price,
        "stop_price": item.stop_price,
    }
    report(
        "매수후보 감지",
        (
            f"[매수후보 감지] 종목={item.symbol} 전략=d1_vol5_absret10 "
            "매수여부=조건충족시매수 상태=선행검증 "
            f"신호일={item.signal_date} 기준가={item.close_price:.4f} "
            f"예상매수가={item.entry_price:.4f} 목표가={item.target_price:.4f} 손절가={item.stop_price:.4f} "
            f"전일거래량={item.volume_x20:.1f}x 전일등락={item.ret_pct:+.1f}%"
        ),
        state["d1_vol5_absret10_watch"][item.symbol],
    )


def maybe_open_position(state: dict, symbol: str, item: dict, policy: RuntimeStrategyPolicy) -> None:
    if not policy.surge_enabled:
        return
    key = position_key(ALGORITHM_NAME, symbol)
    if key in state["positions"] or symbol in state["positions"]:
        return
    price_range = fetch_symbol_range(symbol, item["first_signal_time"])
    if price_range is None:
        return
    high_price, low_price, last_bar_time = price_range
    entry_price = float(item["entry_price"])
    if low_price > entry_price:
        return
    state["positions"][key] = {
        "algorithm": ALGORITHM_NAME,
        "symbol": symbol,
        "opened_at": last_bar_time,
        "entry_price": entry_price,
        "target_price": float(item["target_price"]),
        "stop_price": float(item["stop_price"]),
        "status": "open",
        "market_regime": policy.regime,
        "time_bucket": policy.time_bucket,
        "position_size_multiplier": policy.position_size_multiplier,
    }
    report(
        "모의매수 발생",
        (
            f"[모의매수 발생] 종목={symbol} 전략={ALGORITHM_NAME} "
            f"매수가={entry_price:.4f} 목표가={float(item['target_price']):.4f} "
            f"손절가={float(item['stop_price']):.4f} 장세={policy.regime} "
            f"시간대={policy.time_bucket} 비중={policy.position_size_multiplier:.2f}"
        ),
        state["positions"][key],
    )


def maybe_open_d1_position(state: dict, symbol: str, item: dict, policy: RuntimeStrategyPolicy) -> None:
    if not policy.d1_enabled:
        return
    key = position_key(D1_ALGORITHM_NAME, symbol)
    if key in state["positions"]:
        return
    today = datetime.now(NY_TZ).date().isoformat()
    session_start = f"{today} 09:30:00"
    price_range = fetch_symbol_range(symbol, session_start)
    if price_range is None:
        return
    high_price, low_price, last_bar_time = price_range
    prior_close = float(item["close_price"])
    entry_price = float(item.get("entry_price") or prior_close * 1.02)
    if high_price < entry_price:
        return
    target_price = float(item.get("target_price") or entry_price * 1.10)
    stop_price = float(item.get("stop_price") or entry_price * 0.95)
    state["positions"][key] = {
        "algorithm": D1_ALGORITHM_NAME,
        "symbol": symbol,
        "opened_at": last_bar_time,
        "entry_price": entry_price,
        "target_price": target_price,
        "stop_price": stop_price,
        "status": "open",
        "source_signal_date": item["signal_date"],
        "source_volume_x20": item["volume_x20"],
        "source_ret_pct": item["ret_pct"],
        "market_regime": policy.regime,
        "time_bucket": policy.time_bucket,
        "position_size_multiplier": policy.position_size_multiplier,
    }
    report(
        "모의매수 발생",
        (
            f"[모의매수 발생] 종목={symbol} 전략={D1_ALGORITHM_NAME} "
            f"매수가={entry_price:.4f} 목표가={target_price:.4f} 손절가={stop_price:.4f} "
            f"근거=전일거래량{float(item['volume_x20']):.1f}x "
            f"장세={policy.regime} 시간대={policy.time_bucket} 비중={policy.position_size_multiplier:.2f}"
        ),
        state["positions"][key],
    )


def maybe_open_sideways_position(state: dict, item: StrategyTradeTarget, policy: RuntimeStrategyPolicy) -> None:
    if not policy.sideways_enabled:
        return
    open_sideways = [
        p for p in state.get("positions", {}).values()
        if p.get("status") == "open" and p.get("algorithm") == SIDEWAYS_ALGORITHM_NAME
    ]
    if len(open_sideways) >= policy.max_new_sideways_positions:
        return
    key = position_key(SIDEWAYS_ALGORITHM_NAME, item.symbol)
    existing = state["positions"].get(key)
    if existing and existing.get("status") == "open":
        return
    if existing and existing.get("closed_at") and item.signal_time <= existing["closed_at"]:
        return
    latest = fetch_latest_price(item.symbol)
    if latest is None:
        return
    latest_time, latest_price = latest
    entry_ceiling = item.entry_price * (1.0 + SIDEWAYS_MAX_ENTRY_SLIPPAGE_PCT / 100.0)
    if latest_time < item.signal_time:
        return
    if latest_price > entry_ceiling:
        return
    if latest_price >= item.target_price:
        return
    if latest_price <= item.stop_price:
        return
    entry_price = latest_price
    target_price = entry_price * 1.03
    stop_price = min(item.stop_price, entry_price * 0.98)
    state["positions"][key] = {
        "algorithm": SIDEWAYS_ALGORITHM_NAME,
        "symbol": item.symbol,
        "opened_at": latest_time,
        "source_signal_time": item.signal_time,
        "source_entry_price": item.entry_price,
        "entry_price": entry_price,
        "target_price": target_price,
        "stop_price": stop_price,
        "status": "open",
        "round_trip_cost_pct": SIDEWAYS_ROUND_TRIP_COST_PCT,
        "target_fill_cushion_pct": SIDEWAYS_TARGET_FILL_CUSHION_PCT,
        "max_entry_slippage_pct": SIDEWAYS_MAX_ENTRY_SLIPPAGE_PCT,
        "score": item.score,
        "return_pct": item.return_pct,
        "market_regime": policy.regime,
        "time_bucket": policy.time_bucket,
        "position_size_multiplier": policy.position_size_multiplier,
    }
    report(
        "모의매수 발생",
        (
            f"[모의매수 발생] 종목={item.symbol} 전략={SIDEWAYS_ALGORITHM_NAME} "
            f"매수가={entry_price:.4f} 목표가={target_price:.4f} 손절가={stop_price:.4f} "
            f"신호시각={item.signal_time} 체결시각={latest_time} "
            f"비용={SIDEWAYS_ROUND_TRIP_COST_PCT:.2f}% 체결쿠션={SIDEWAYS_TARGET_FILL_CUSHION_PCT:.2f}% "
            f"장세={policy.regime} 시간대={policy.time_bucket} 비중={policy.position_size_multiplier:.2f}"
        ),
        state["positions"][key],
    )


def maybe_close_position(state: dict, key: str, position: dict) -> None:
    if position.get("status") != "open":
        return
    symbol = position_symbol(key, position)
    price_range = fetch_symbol_range(symbol, position["opened_at"])
    if price_range is None:
        return
    high_price, low_price, last_bar_time = price_range
    entry_price = float(position["entry_price"])
    target_price = float(position["target_price"])
    stop_price = float(position["stop_price"])
    target_fill_cushion_pct = float(position.get("target_fill_cushion_pct") or 0.0)
    round_trip_cost_pct = float(position.get("round_trip_cost_pct") or 0.0)
    exit_price = None
    reason = None
    if high_price >= target_price * (1.0 + target_fill_cushion_pct / 100.0):
        exit_price = target_price
        reason = "target"
    elif low_price <= stop_price:
        exit_price = stop_price
        reason = "stop"
    if exit_price is None:
        return
    gross_pnl_pct = ((exit_price / entry_price) - 1.0) * 100.0
    pnl_pct = gross_pnl_pct - round_trip_cost_pct
    report(
        "모의매도 발생",
        f"[모의매도 발생] 종목={symbol} 매도가={exit_price:.4f} 사유={reason}",
        {"symbol": symbol, "exit_price": exit_price, "reason": reason},
    )
    position.update(
        {
            "status": "closed",
            "closed_at": last_bar_time,
            "exit_price": exit_price,
            "pnl_pct": pnl_pct,
            "reason": reason,
        }
    )
    state["closed"].append({"symbol": symbol, **position})
    append_trade_ledger(symbol, position)
    report(
        "모의정산",
        f"[모의정산] 종목={symbol} 매도가={exit_price:.4f} 사유={reason} "
        f"손익={pnl_pct:.2f}% 총손익={gross_pnl_pct:.2f}% 비용={round_trip_cost_pct:.2f}%",
        position,
    )


def close_open_positions_at_eod(state: dict) -> None:
    for key, position in list(state.get("positions", {}).items()):
        if position.get("status") != "open":
            continue
        symbol = position_symbol(key, position)
        latest = fetch_latest_price(symbol)
        if latest is None:
            continue
        closed_at, exit_price = latest
        entry_price = float(position["entry_price"])
        round_trip_cost_pct = float(position.get("round_trip_cost_pct") or 0.0)
        gross_pnl_pct = ((exit_price / entry_price) - 1.0) * 100.0
        pnl_pct = gross_pnl_pct - round_trip_cost_pct
        report(
            "모의매도 발생",
            f"[모의매도 발생] 종목={symbol} 매도가={exit_price:.4f} 사유=eod",
            {"symbol": symbol, "exit_price": exit_price, "reason": "eod"},
        )
        position.update(
            {
                "status": "closed",
                "closed_at": closed_at,
                "exit_price": exit_price,
                "pnl_pct": pnl_pct,
                "reason": "eod",
            }
        )
        state["closed"].append({"symbol": symbol, **position})
        append_trade_ledger(symbol, position)
        report(
            "모의정산",
            f"[모의정산] 종목={symbol} 매도가={exit_price:.4f} 사유=eod "
            f"손익={pnl_pct:.2f}% 총손익={gross_pnl_pct:.2f}% 비용={round_trip_cost_pct:.2f}%",
            position,
        )


def emit_daily_report(state: dict) -> None:
    today = datetime.now(NY_TZ).date().isoformat()
    closed = [row for row in load_trade_ledger() if row.get("trade_date") == today]
    open_positions = [x for x in state.get("positions", {}).values() if x.get("status") == "open"]
    today_summary = summarize_trades(closed)
    rolling_rows = recent_trading_day_rows(10)
    rolling_days = len({row.get("trade_date") for row in rolling_rows if row.get("trade_date")})
    rolling_summary = summarize_trades(rolling_rows)
    today_result = "수익" if today_summary["total_pnl"] > 0 else "손실" if today_summary["total_pnl"] < 0 else "보합"
    rolling_result = "수익" if rolling_summary["total_pnl"] > 0 else "손실" if rolling_summary["total_pnl"] < 0 else "보합"
    policy = fetch_runtime_strategy_policy()
    report(
        "일일결산",
        (
            f"[일일결산] algorithms={ALGORITHM_NAME},{D1_ALGORITHM_NAME},{SIDEWAYS_ALGORITHM_NAME} "
            f"regime={policy.regime} time_bucket={policy.time_bucket} allocation={policy.allocation_rule} "
            f"today={today_result} detected={len(state.get('detected', {}))} "
            f"pre_watch={len(state.get('pre_surge_watch', {}))} "
            f"d1_watch={len(state.get('d1_vol5_absret10_watch', {}))} "
            f"open={len(open_positions)} trades={today_summary['trades']} "
            f"wins={today_summary['wins']} losses={today_summary['losses']} "
            f"win_rate={today_summary['win_rate']:.1f}% "
            f"avg_pnl={today_summary['avg_pnl']:.2f}% total_pnl={today_summary['total_pnl']:.2f}% "
            f"rolling_10d={rolling_result} days={rolling_days} trades={rolling_summary['trades']} "
            f"wins={rolling_summary['wins']} losses={rolling_summary['losses']} "
            f"win_rate={rolling_summary['win_rate']:.1f}% "
            f"avg_pnl={rolling_summary['avg_pnl']:.2f}% total_pnl={rolling_summary['total_pnl']:.2f}% "
            f"best={rolling_summary['best']:.2f}% worst={rolling_summary['worst']:.2f}%"
        ),
        {
            "algorithms": [ALGORITHM_NAME, D1_ALGORITHM_NAME, SIDEWAYS_ALGORITHM_NAME],
            "detected": len(state.get("detected", {})),
            "pre_watch": len(state.get("pre_surge_watch", {})),
            "d1_watch": len(state.get("d1_vol5_absret10_watch", {})),
            "open": len(open_positions),
            "today": today_summary,
            "rolling_10d_days": rolling_days,
            "rolling_10d": rolling_summary,
            "market_regime": policy.regime,
            "time_bucket": policy.time_bucket,
            "allocation_rule": policy.allocation_rule,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--daily-report", action="store_true")
    parser.add_argument("--market-open", action="store_true")
    parser.add_argument("--market-close", action="store_true")
    args = parser.parse_args()

    closed_reason = market_closed_reason()
    if closed_reason:
        if args.market_open:
            report(
                "장휴장",
                f"[장휴장] market_date={datetime.now(NY_TZ).strftime('%Y-%m-%d')} reason={closed_reason}",
                {"reason": closed_reason},
            )
        elif not args.market_close and not args.daily_report:
            print(f"market closed: {closed_reason}")
        return 0

    ensure_runtime_objects()
    state = load_state()
    if args.market_open:
        state = reset_daily_state()
        report("장시작", "[장시작] delayed intraday collection/detection started")
        save_state(state)
        return 0
    if args.market_close:
        report("장종료", "[장종료] delayed intraday collection/detection stopped")
        close_open_positions_at_eod(state)
        emit_daily_report(state)
        save_state(state)
        return 0
    if args.daily_report:
        emit_daily_report(state)
        save_state(state)
        return 0

    for item in fetch_pre_surge_watch_symbols(min(args.limit, 30)):
        record_pre_surge_watch(state, item)
    for item in fetch_d1_vol5_absret10_symbols(min(args.limit, 30)):
        record_d1_vol5_absret10_watch(state, item)
    for item in fetch_detected_symbols(args.limit):
        record_detection(state, item)
    policy = fetch_runtime_strategy_policy()
    for symbol, item in list(state["detected"].items()):
        maybe_open_position(state, symbol, item, policy)
    for symbol, item in list(state["d1_vol5_absret10_watch"].items()):
        maybe_open_d1_position(state, symbol, item, policy)
    for item in fetch_sideways_vwap_reversion_targets(min(args.limit, 30)):
        maybe_open_sideways_position(state, item, policy)
    for key, position in list(state["positions"].items()):
        maybe_close_position(state, key, position)
    save_state(state)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        notify_error("sqream_runtime_events", exc, persist_report=persist_report_event)
        raise
