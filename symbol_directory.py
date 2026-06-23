#!/usr/bin/env python3

from __future__ import annotations

import csv
import io
import json
import time
import urllib.request
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
STATE_DIR = BASE_DIR / "state"
CACHE_PATH = STATE_DIR / "symbol_directory.json"
CACHE_TTL_SECONDS = 24 * 60 * 60
NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
_CACHE: dict[str, str] | None = None


def _fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _clean_name(name: str) -> str:
    value = " ".join(name.strip().split())
    for suffix in [
        " - Common Stock",
        " Common Stock",
        " - Ordinary Shares",
        " Ordinary Shares",
        " - Class A Common Stock",
        " Class A Common Stock",
        " - Class B Common Stock",
        " Class B Common Stock",
    ]:
        if value.endswith(suffix):
            value = value[: -len(suffix)].strip()
    return value


def _parse_symbol_file(text: str, symbol_column: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in csv.DictReader(io.StringIO(text), delimiter="|"):
        symbol = (row.get(symbol_column) or "").strip().upper()
        name = _clean_name(row.get("Security Name") or "")
        if not symbol or symbol.startswith("FILE CREATION TIME"):
            continue
        if not name:
            continue
        result[symbol] = name
    return result


def _read_cache() -> dict[str, str]:
    if not CACHE_PATH.exists():
        return {}
    try:
        payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    symbols = payload.get("symbols") if isinstance(payload, dict) else None
    return symbols if isinstance(symbols, dict) else {}


def _cache_is_fresh() -> bool:
    if not CACHE_PATH.exists():
        return False
    return time.time() - CACHE_PATH.stat().st_mtime < CACHE_TTL_SECONDS


def load_symbol_directory(force_refresh: bool = False) -> dict[str, str]:
    global _CACHE
    if _CACHE is not None and not force_refresh:
        return _CACHE

    if not force_refresh and _cache_is_fresh():
        _CACHE = _read_cache()
        return _CACHE

    cached = _read_cache()
    try:
        symbols: dict[str, str] = {}
        symbols.update(_parse_symbol_file(_fetch_text(NASDAQ_LISTED_URL), "Symbol"))
        symbols.update(_parse_symbol_file(_fetch_text(OTHER_LISTED_URL), "ACT Symbol"))
        if symbols:
            STATE_DIR.mkdir(exist_ok=True)
            CACHE_PATH.write_text(
                json.dumps({"updated_at": int(time.time()), "symbols": symbols}, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            _CACHE = symbols
            return symbols
    except Exception:
        pass

    _CACHE = cached
    return _CACHE


def symbol_name(symbol: str) -> str | None:
    return load_symbol_directory().get(symbol.strip().upper())


def symbol_identity(symbol: str) -> str:
    code = symbol.strip().upper()
    name = symbol_name(code) or "확인불가"
    return f"종목명={name} 코드={code}"
