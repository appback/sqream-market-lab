create or replace table market_rt.time_strategy_policy_base as
select
  'opening_0930_1015' as time_bucket,
  '09:30' as start_hhmm,
  '10:15' as end_hhmm,
  1 as surge_enabled,
  1 as d1_enabled,
  0 as sideways_enabled,
  0.30 as position_size_multiplier,
  0 as max_new_sideways_positions,
  'opening volatility; D1 precursor breakout allowed with small sizing; sideways disabled' as rule_text
union all
select
  'morning_1015_1130',
  '10:15',
  '11:30',
  1,
  0,
  0,
  0.50,
  0,
  'trend confirmation window; D1 precursor disabled after opening based on ledger evidence; avoid sideways until range stabilizes'
union all
select
  'midday_1130_1430',
  '11:30',
  '14:30',
  0,
  0,
  0,
  0.00,
  0,
  'sideways VWAP disabled; live-safe backtest negative; pending stricter filter'
union all
select
  'late_1430_1530',
  '14:30',
  '15:30',
  0,
  0,
  0,
  0.00,
  0,
  'late window failed backtest; no new entries; manage existing exits only'
union all
select
  'close_1530_1600',
  '15:30',
  '16:00',
  0,
  0,
  0,
  0.00,
  0,
  'no new entries; manage exits and daily settlement';

create or replace table market_rt.current_time_strategy_policy as
select
  l.latest_bar_time,
  substring(l.latest_bar_time, 12, 5) as latest_hhmm,
  p.time_bucket,
  p.start_hhmm,
  p.end_hhmm,
  p.surge_enabled,
  p.d1_enabled,
  p.sideways_enabled,
  p.position_size_multiplier,
  p.max_new_sideways_positions,
  p.rule_text
from (
  select max(bar_time) as latest_bar_time
  from market_rt.delayed_intraday_bars_latest
) l
join market_rt.time_strategy_policy_base p
  on substring(l.latest_bar_time, 12, 5) >= p.start_hhmm
 and substring(l.latest_bar_time, 12, 5) < p.end_hhmm;

create or replace table market_rt.strategy_context_policy as
select
  'd1_vol5_absret10_breakout_2_target10_stop5_eod' as strategy_name,
  'sideways' as regime,
  'opening_0930_1015' as time_bucket,
  1 as enabled,
  0.30 as position_size_multiplier,
  'promoted from 2026-06-16 CTM win and ledger analysis: opening bucket 10 trades, 8 wins, avg +7.60pct; non-opening disabled' as rule_text
union all
select
  'd1_vol5_absret10_breakout_2_target10_stop5_eod',
  'uptrend',
  'opening_0930_1015',
  1,
  0.30,
  'allowed in opening only; validate separately from sideways evidence'
union all
select
  'd1_vol5_absret10_breakout_2_target10_stop5_eod',
  'downtrend',
  'opening_0930_1015',
  0,
  0.00,
  'downtrend disables new D1 entries'
union all
select
  'sideways_vwap_reversion_3_target_stop_cost',
  'sideways',
  'midday_1130_1430',
  0,
  0.00,
  'disabled after live-safe backtest failure; keep lab-only until stricter filter is proven'
union all
select
  'uptrend_breakout_b05_vol2m_rs15_breadth60_t4_stop2_cost',
  'uptrend',
  'morning_1015_1130',
  0,
  0.00,
  'candidate only; not active paper until more out-of-sample days confirm'
union all
select
  'uptrend_breakout_b05_vol2m_rs15_breadth60_t4_stop2_cost',
  'uptrend',
  'midday_1130_1430',
  0,
  0.00,
  'candidate only; not active paper until more out-of-sample days confirm';

create or replace table market_rt.current_strategy_context_policy as
select
  p.latest_bar_time,
  p.latest_hhmm,
  r.regime,
  p.time_bucket,
  c.strategy_name,
  c.enabled,
  c.position_size_multiplier,
  c.rule_text
from market_rt.current_time_strategy_policy p
join market_rt.market_regime_current r
  on 1 = 1
join market_rt.strategy_context_policy c
  on c.regime = r.regime
 and c.time_bucket = p.time_bucket;

create or replace table market_rt.time_bucket_paper_trade_summary as
select
  trade_date,
  algorithm,
  case
    when substring(opened_at, 12, 5) >= '09:30' and substring(opened_at, 12, 5) < '10:15' then 'opening_0930_1015'
    when substring(opened_at, 12, 5) >= '10:15' and substring(opened_at, 12, 5) < '11:30' then 'morning_1015_1130'
    when substring(opened_at, 12, 5) >= '11:30' and substring(opened_at, 12, 5) < '14:30' then 'midday_1130_1430'
    when substring(opened_at, 12, 5) >= '14:30' and substring(opened_at, 12, 5) < '15:30' then 'late_1430_1530'
    else 'close_1530_1600'
  end as time_bucket,
  count(*) as trades,
  sum(case when pnl_pct > 0 then 1 else 0 end) as wins,
  avg(pnl_pct) as avg_pnl_pct,
  sum(pnl_pct) as total_pnl_pct
from market_rt.paper_trade_ledger
group by
  trade_date,
  algorithm,
  case
    when substring(opened_at, 12, 5) >= '09:30' and substring(opened_at, 12, 5) < '10:15' then 'opening_0930_1015'
    when substring(opened_at, 12, 5) >= '10:15' and substring(opened_at, 12, 5) < '11:30' then 'morning_1015_1130'
    when substring(opened_at, 12, 5) >= '11:30' and substring(opened_at, 12, 5) < '14:30' then 'midday_1130_1430'
    when substring(opened_at, 12, 5) >= '14:30' and substring(opened_at, 12, 5) < '15:30' then 'late_1430_1530'
    else 'close_1530_1600'
  end;

select
  latest_bar_time,
  latest_hhmm,
  time_bucket,
  surge_enabled,
  d1_enabled,
  sideways_enabled,
  position_size_multiplier,
  max_new_sideways_positions
from market_rt.current_time_strategy_policy;

select
  latest_bar_time,
  regime,
  time_bucket,
  strategy_name,
  enabled,
  position_size_multiplier
from market_rt.current_strategy_context_policy
order by strategy_name;
