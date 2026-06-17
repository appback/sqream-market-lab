create or replace table market_rt.strategy_registry as
select
  'surge_pullback_35_target25_stop15_eod' as strategy_name,
  'active_paper_trade' as strategy_type,
  'delayed_surge_symbols_all' as source_table,
  'day_return_pct >= 100, entry=max_close*0.65, target=entry*1.25, stop=entry*0.85' as rule_text
union all
select
  'pre_surge_watch' as strategy_name,
  'watch_only' as strategy_type,
  'delayed_pre_surge_watch_symbols_all' as source_table,
  'range>=8, volume burst>=5 or total volume>=500k, return between -15 and 35' as rule_text
union all
select
  'd1_vol5_absret10_breakout_2_target10_stop5_eod' as strategy_name,
  'active_paper_trade' as strategy_type,
  'd1_vol5_absret10_candidates' as source_table,
  'prior day volume >= 5x 20d average and abs return <= 10, entry=prior close*1.02, target=entry*1.10, stop=entry*0.95' as rule_text
union all
select
  'sideways_vwap_reversion_3_target_stop_cost' as strategy_name,
  'active_paper_trade' as strategy_type,
  'sideways_vwap_reversion_entries' as source_table,
  'high volume sideways, lower 25pct range and below VWAP, one open position per symbol, target=entry*1.03, stop=range break or -2pct, roundtrip cost=0.5pct, target fill cushion=0.5pct' as rule_text;

create or replace table market_rt.strategy_candidates_all as
select
  'surge_pullback_35_target25_stop15_eod' as strategy_name,
  symbol,
  first_signal_time as signal_time,
  max_close_price as reference_price,
  min_pullback_35_entry_price as entry_price,
  max_target_price as target_price,
  min_stop_price as stop_price,
  max_day_return_pct as score,
  max_day_return_pct as return_pct,
  'trade_target' as candidate_type
from market_rt.delayed_surge_symbols_all
union all
select
  'pre_surge_watch' as strategy_name,
  symbol,
  last_bar_time as signal_time,
  last_close as reference_price,
  0.0 as entry_price,
  0.0 as target_price,
  0.0 as stop_price,
  minute_volume_burst_x as score,
  day_return_pct as return_pct,
  'watch_only' as candidate_type
from market_rt.delayed_pre_surge_watch_symbols_all
union all
select
  'd1_vol5_absret10_breakout_2_target10_stop5_eod' as strategy_name,
  symbol,
  signal_date as signal_time,
  close_price as reference_price,
  close_price * 1.02 as entry_price,
  close_price * 1.02 * 1.10 as target_price,
  close_price * 1.02 * 0.95 as stop_price,
  volume_x20 as score,
  ret_pct as return_pct,
  'trade_target' as candidate_type
from market_rt.d1_vol5_absret10_candidates
union all
select
  'sideways_vwap_reversion_3_target_stop_cost' as strategy_name,
  e.symbol,
  e.entry_time as signal_time,
  e.entry_price as reference_price,
  e.entry_price as entry_price,
  e.entry_price * 1.03 as target_price,
  case
    when u.day_low * 0.995 < e.entry_price * 0.98 then u.day_low * 0.995
    else e.entry_price * 0.98
  end as stop_price,
  u.total_volume as score,
  u.day_return_pct as return_pct,
  'trade_target' as candidate_type
from market_rt.sideways_vwap_reversion_entries e
join market_rt.sideways_vwap_reversion_universe u
  on u.symbol = e.symbol;

create or replace table market_rt.strategy_trade_targets as
select *
from market_rt.strategy_candidates_all
where candidate_type = 'trade_target';

select count(*) from market_rt.strategy_registry;
select count(*) from market_rt.strategy_candidates_all;
select count(*) from market_rt.strategy_trade_targets;
