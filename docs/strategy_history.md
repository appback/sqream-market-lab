# Strategy Version History

Updated: 2026-06-17 08:05 KST

This document is the human-readable strategy registry. SQream remains the source for measured results; this file records version, type, status, rule intent, and decision history.

## Status Definitions

- `active_paper`: enabled for paper-trading runtime.
- `candidate`: valid enough for additional testing, not yet enabled by default.
- `watch_only`: used for detection or monitoring, not automatic paper entry.
- `disabled`: failed live-safe validation or blocked by risk controls.
- `retired`: not used unless explicitly revived.

## Current Runtime Guardrails

- New entries are controlled by SQream tables `market_rt.market_regime_current` and `market_rt.current_time_strategy_policy`.
- Strategy activation is now also documented in `market_rt.strategy_context_policy`: market regime + time bucket + strategy.
- `downtrend` disables new active entries.
- `15:30~16:00` disables new entries and only manages exits/settlement.
- `d1_vol5_absret10_breakout_2_target10_stop5_eod` is active only in `09:30~10:15`; non-opening entries are disabled from the time policy.
- `sideways_vwap_reversion_3_target_stop_cost` is disabled after live-safe backtest failure.
- Position sizing is represented as `position_size_multiplier` in runtime state, not capital-account execution yet.

## Versions

| Version | Strategy | Type | Status | Rule Summary | Latest Evidence | Decision |
|---|---|---|---|---|---|---|
| `surge_pullback_v1` | `surge_pullback_35_target25_stop15_eod` | surge pullback | active_paper | Detect intraday +100% surge, enter 35% pullback, target +25%, stop -15%, EOD close. | Runtime ledger exists; high variance. | Keep as paper-only while collecting more samples. |
| `d1_precursor_v1` | `d1_vol5_absret10_breakout_2_target10_stop5_eod` | precursor breakout | superseded | Prior-day volume >= 5x 20-day average and abs return <= 10%, entry +2%, target +10%, stop -5%. | Ledger showed non-opening entries dilute edge. | Superseded by `d1_precursor_v1_1`. |
| `d1_precursor_v1_1` | `d1_vol5_absret10_breakout_2_target10_stop5_eod` | precursor breakout | active_paper | Same D1 precursor, but enabled only in `opening_0930_1015`; opening size multiplier 0.30; disabled after 10:15. | Paper ledger: 19 total trades, avg +2.42%; opening bucket 10 trades, 8 wins, avg +7.60%; non-opening buckets weak. CTM 2026-06-16 hit +10%. | Keep active paper only for opening bucket; collect more out-of-sample days. |
| `sideways_vwap_v1` | `sideways_vwap_reversion_3_target_stop_cost` | mean reversion | disabled | High-volume sideways, lower range + below VWAP, target +3%, stop around -2%, cost 0.5%, fill cushion 0.5%. | Live-safe test: 1,080 trades, 323 wins, avg -0.75%, total -807.45%p. | Disabled. Do not enable until stricter filter is found. |
| `uptrend_breakout_v0_1` | `uptrend_breakout_t3_stop15_cost` | breakout | superseded | Uptrend regime, 10:15~14:30, close breaks previous running high by 0.2%, target +3%, stop -1.5%, cost 0.5%. | Exit-grid test: 276 trades, 146 wins, avg +0.09%, total +25.06%p. | Superseded by `uptrend_breakout_v0_2`. |
| `uptrend_breakout_v0_2` | `uptrend_breakout_b05_vol2m_rs15_breadth60_t4_stop2_cost` | breakout | candidate | Uptrend, breadth >= 60%, close breaks previous running high by 0.5%, run volume >= 2M, relative strength >= +1.5%p, target +4%, stop -2%, cost 0.5%. | Candidate grid test: 50 trades, 33 wins, avg +0.36%, total +17.94%p. | Best current candidate; keep lab-only until more days confirm. |
| `uptrend_high_hold_v0_1` | `uptrend_high_hold_t3_stop15_cost` | high hold | disabled | Uptrend, close near running high, target +3%, stop -1.5%. | Exit-grid test: 1,167 trades, avg -0.43%. | Disabled. |
| `uptrend_vwap_pullback_v0_1` | `uptrend_vwap_pullback_t2_stop1_cost` | trend pullback | disabled | Uptrend, positive return, below VWAP pullback, target +2%, stop -1%. | Strategy lab test: 452 trades, avg -0.86%. | Disabled. |
| `mr_lower10_v0_1` | `mr_lower10_t1_stop1_cost` | mean reversion | disabled | Sideways, lower 10% range, target +1%, stop -1%. | Strategy lab test: 634 trades, avg -0.75%. | Disabled. |

## Latest Lab Result

Best current candidate is `uptrend_breakout_v0_2`. It improves edge by filtering breadth, relative strength, and volume, but sample size is only 50 trades.

- Run on additional future days before enabling.
- Add order-book and execution-strength fields when Toss real-time data is available.
- Keep `candidate` until out-of-sample results remain positive.

## Context Policy Rule

Runtime decisions should be made in this order:

1. SQream updates raw/latest bars.
2. SQream classifies current market regime.
3. SQream classifies current time bucket.
4. SQream selects allowed strategies from `market_rt.strategy_context_policy`.
5. Runtime only monitors/opens positions for enabled strategy-context combinations.

Current highest-confidence active combination:

- Strategy: `d1_vol5_absret10_breakout_2_target10_stop5_eod`
- Regime: `sideways` or `uptrend`, excluding `downtrend`
- Time bucket: `opening_0930_1015`
- Size: 0.30 multiplier
- Rationale: recent paper evidence is concentrated in the opening bucket; non-opening D1 entries are disabled until proven otherwise.

## Versioning Rule

- `v0.x`: lab candidate only.
- `v1.x`: paper-trading enabled.
- `v2.x`: paper strategy with capital sizing and realistic fill modeling.
- `disabled` strategies stay documented with failure evidence; they are not deleted.
