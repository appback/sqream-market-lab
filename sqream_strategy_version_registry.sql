create or replace table market_rt.strategy_version_registry as
select
  'surge_pullback_v1' as version_id,
  'surge_pullback_35_target25_stop15_eod' as strategy_name,
  'surge_pullback' as strategy_type,
  'active_paper' as status,
  'intraday +100pct surge; enter 35pct pullback; target +25pct; stop -15pct; EOD close' as rule_summary,
  'keep paper-only while collecting samples' as decision_note
union all
select
  'd1_precursor_v1',
  'd1_vol5_absret10_breakout_2_target10_stop5_eod',
  'precursor_breakout',
  'superseded',
  'prior-day volume >= 5x 20d average and abs return <= 10pct; entry +2pct; target +10pct; stop -5pct',
  'superseded by d1_precursor_v1_1 after ledger showed edge concentrated in opening bucket'
union all
select
  'd1_precursor_v1_1',
  'd1_vol5_absret10_breakout_2_target10_stop5_eod',
  'precursor_breakout',
  'active_paper',
  'prior-day volume >= 5x 20d average and abs return <= 10pct; entry +2pct; target +10pct; stop -5pct; opening_0930_1015 only; size multiplier 0.30',
  'active paper only in opening bucket: ledger 10 trades; 8 wins; avg +7.60pct; CTM 2026-06-16 +10pct'
union all
select
  'sideways_vwap_v1',
  'sideways_vwap_reversion_3_target_stop_cost',
  'mean_reversion',
  'disabled',
  'sideways lower-range VWAP reversion; target +3pct; stop around -2pct; cost 0.5pct; fill cushion 0.5pct',
  'disabled after live-safe backtest: 1080 trades; avg -0.75pct'
union all
select
  'uptrend_breakout_v0_1',
  'uptrend_breakout_t3_stop15_cost',
  'breakout',
  'superseded',
  'uptrend; 10:15-14:30; close breaks previous running high by 0.2pct; target +3pct; stop -1.5pct; cost 0.5pct',
  'superseded by uptrend_breakout_v0_2'
union all
select
  'uptrend_breakout_v0_2',
  'uptrend_breakout_b05_vol2m_rs15_breadth60_t4_stop2_cost',
  'breakout',
  'candidate',
  'uptrend; breadth >= 60pct; close breaks previous running high by 0.5pct; run volume >= 2M; relative strength >= +1.5pctp; target +4pct; stop -2pct; cost 0.5pct',
  'best current candidate from breakout grid: 50 trades; 33 wins; avg +0.36pct'
union all
select
  'uptrend_high_hold_v0_1',
  'uptrend_high_hold_t3_stop15_cost',
  'high_hold',
  'disabled',
  'uptrend; close near running high; target +3pct; stop -1.5pct',
  'disabled after lab avg -0.43pct'
union all
select
  'uptrend_vwap_pullback_v0_1',
  'uptrend_vwap_pullback_t2_stop1_cost',
  'trend_pullback',
  'disabled',
  'uptrend; positive return; below VWAP pullback; target +2pct; stop -1pct',
  'disabled after lab avg -0.86pct'
union all
select
  'mr_lower10_v0_1',
  'mr_lower10_t1_stop1_cost',
  'mean_reversion',
  'disabled',
  'sideways lower 10pct range; target +1pct; stop -1pct',
  'disabled after lab avg -0.75pct';

select
  version_id,
  strategy_name,
  strategy_type,
  status,
  decision_note
from market_rt.strategy_version_registry
order by version_id;
