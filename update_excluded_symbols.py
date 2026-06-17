#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log-file", type=Path, default=BASE_DIR / "logs" / "delayed_intraday_cycle.log")
    parser.add_argument("--output", type=Path, default=BASE_DIR / "monitor_excluded_symbols.txt")
    parser.add_argument("--min-failures", type=int, default=8)
    args = parser.parse_args()

    text = args.log_file.read_text(errors="ignore") if args.log_file.exists() else ""
    counts: Counter[str] = Counter()
    for symbol in re.findall(r"\$([A-Z][A-Z0-9.\-]{0,15}): possibly delisted", text):
        counts[symbol.upper()] += 1
    for group in re.findall(r"\[([^\]]+)\]: possibly delisted", text):
        for symbol in re.findall(r"'([^']+)'", group):
            counts[symbol.upper()] += 1

    excluded = sorted(symbol for symbol, count in counts.items() if count >= args.min_failures)
    args.output.write_text("\n".join(excluded) + ("\n" if excluded else ""))
    print(f"excluded={len(excluded)} min_failures={args.min_failures} output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
