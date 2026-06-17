import datetime as dt

from stock_screener import Candle, scan_one_day_doublers, scan_sub_dollar_rebound, scan_surge_setup


def make_candle(day_offset: int, open_: float, high: float, low: float, close: float, volume: int) -> Candle:
    base = dt.date.today() - dt.timedelta(days=120)
    return Candle(
        date=base + dt.timedelta(days=day_offset),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def test_one_day_doubler_detected() -> None:
    candles = [
        make_candle(0, 10, 10.5, 9.8, 10, 1000),
        make_candle(1, 10.5, 21, 10.5, 20.5, 5000),
    ]
    signals = scan_one_day_doublers("MOCK", candles)
    assert len(signals) == 1
    assert signals[0].category == "one_day_100pct"


def test_sub_dollar_rebound_detected() -> None:
    candles = [
        make_candle(0, 2.0, 2.1, 1.95, 2.0, 900),
        make_candle(1, 2.0, 2.05, 0.75, 0.8, 3000),
        make_candle(2, 0.82, 0.9, 0.8, 0.85, 1800),
        make_candle(3, 0.9, 1.3, 0.88, 1.2, 2500),
    ]
    signals = scan_sub_dollar_rebound("MOCK", candles)
    assert len(signals) == 1
    assert signals[0].category == "sub_dollar_rebound"


def test_surge_setup_detected() -> None:
    candles = []
    close = 10.0
    for i in range(90):
        if i >= 70:
            close += 0.22
            volume = 5000
        else:
            close += 0.01
            volume = 1000
        candles.append(make_candle(i, close - 0.1, close + 0.2, close - 0.2, close, volume))
    signals = scan_surge_setup("MOCK", candles)
    assert len(signals) == 1
    assert signals[0].category == "surge_setup"
