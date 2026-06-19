#!/usr/bin/env python3

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo


NY_TZ = ZoneInfo("America/New_York")

# Minimal explicit calendar for the active operating year. This prevents weekday
# cron jobs from treating exchange holidays as real sessions and reloading stale
# previous-session bars.
US_MARKET_HOLIDAYS_2026 = {
    date(2026, 1, 1): "New Year's Day",
    date(2026, 1, 19): "Martin Luther King Jr. Day",
    date(2026, 2, 16): "Presidents Day",
    date(2026, 4, 3): "Good Friday",
    date(2026, 5, 25): "Memorial Day",
    date(2026, 6, 19): "Juneteenth",
    date(2026, 7, 3): "Independence Day observed",
    date(2026, 9, 7): "Labor Day",
    date(2026, 11, 26): "Thanksgiving Day",
    date(2026, 12, 25): "Christmas Day",
}


def market_date(now: datetime | None = None) -> date:
    now = now or datetime.now(NY_TZ)
    return now.astimezone(NY_TZ).date()


def market_closed_reason(now: datetime | None = None) -> str:
    current_date = market_date(now)
    if current_date.weekday() >= 5:
        return "weekend"
    return US_MARKET_HOLIDAYS_2026.get(current_date, "")


def is_regular_market_day(now: datetime | None = None) -> bool:
    return market_closed_reason(now) == ""
