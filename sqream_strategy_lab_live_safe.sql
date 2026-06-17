create or replace table market_rt.strategy_lab_live_safe_features as
select
  f.*,
  max(f.high_price) over (
    partition by f.trade_date, f.symbol
    order by f.bar_time
    rows between unbounded preceding and 1 preceding
  ) as prev_run_high,
  min(f.low_price) over (
    partition by f.trade_date, f.symbol
    order by f.bar_time
    rows between unbounded preceding and 1 preceding
  ) as prev_run_low
from market_rt.backtest_live_safe_features f;

create or replace table market_rt.strategy_lab_live_safe_candidates as
select
  'mr_lower25_t1_stop1' as strategy_name,
  f.trade_date,
  f.symbol,
  f.bar_time as entry_time,
  f.close_price as entry_price,
  1.0 as target_pct,
  1.0 as stop_pct,
  r.regime,
  'mean_reversion' as strategy_group
from market_rt.strategy_lab_live_safe_features f
join market_rt.backtest_live_safe_regime r
  on r.trade_date = f.trade_date and r.bar_time = f.bar_time
where r.regime = 'sideways'
  and substring(f.bar_time, 12, 5) >= '11:30'
  and substring(f.bar_time, 12, 5) < '14:30'
  and substring(f.bar_time, 15, 2) in ('00','05','10','15','20','25','30','35','40','45','50','55')
  and f.run_volume >= 1000000
  and f.close_price between 0.2 and 30
  and f.run_low > 0
  and f.run_return_pct between -5 and 5
  and ((f.run_high / f.run_low) - 1) * 100 >= 3
  and ((f.run_high / f.run_low) - 1) * 100 <= 12
  and f.close_price <= f.run_low + ((f.run_high - f.run_low) * 0.25)
  and f.close_price < f.run_vwap
union all
select
  'mr_lower25_t2_stop2',
  f.trade_date,
  f.symbol,
  f.bar_time,
  f.close_price,
  2.0,
  2.0,
  r.regime,
  'mean_reversion'
from market_rt.strategy_lab_live_safe_features f
join market_rt.backtest_live_safe_regime r
  on r.trade_date = f.trade_date and r.bar_time = f.bar_time
where r.regime = 'sideways'
  and substring(f.bar_time, 12, 5) >= '11:30'
  and substring(f.bar_time, 12, 5) < '14:30'
  and substring(f.bar_time, 15, 2) in ('00','05','10','15','20','25','30','35','40','45','50','55')
  and f.run_volume >= 1000000
  and f.close_price between 0.2 and 30
  and f.run_low > 0
  and f.run_return_pct between -5 and 5
  and ((f.run_high / f.run_low) - 1) * 100 >= 3
  and ((f.run_high / f.run_low) - 1) * 100 <= 12
  and f.close_price <= f.run_low + ((f.run_high - f.run_low) * 0.25)
  and f.close_price < f.run_vwap
union all
select
  'mr_lower10_t1_stop1',
  f.trade_date,
  f.symbol,
  f.bar_time,
  f.close_price,
  1.0,
  1.0,
  r.regime,
  'mean_reversion'
from market_rt.strategy_lab_live_safe_features f
join market_rt.backtest_live_safe_regime r
  on r.trade_date = f.trade_date and r.bar_time = f.bar_time
where r.regime = 'sideways'
  and substring(f.bar_time, 12, 5) >= '11:30'
  and substring(f.bar_time, 12, 5) < '14:30'
  and substring(f.bar_time, 15, 2) in ('00','05','10','15','20','25','30','35','40','45','50','55')
  and f.run_volume >= 1000000
  and f.close_price between 0.2 and 30
  and f.run_low > 0
  and f.run_return_pct between -5 and 5
  and ((f.run_high / f.run_low) - 1) * 100 >= 3
  and ((f.run_high / f.run_low) - 1) * 100 <= 12
  and f.close_price <= f.run_low + ((f.run_high - f.run_low) * 0.10)
  and f.close_price < f.run_vwap
union all
select
  'uptrend_vwap_pullback_t2_stop1',
  f.trade_date,
  f.symbol,
  f.bar_time,
  f.close_price,
  2.0,
  1.0,
  r.regime,
  'trend_pullback'
from market_rt.strategy_lab_live_safe_features f
join market_rt.backtest_live_safe_regime r
  on r.trade_date = f.trade_date and r.bar_time = f.bar_time
where r.regime = 'uptrend'
  and substring(f.bar_time, 12, 5) >= '10:15'
  and substring(f.bar_time, 12, 5) < '14:30'
  and substring(f.bar_time, 15, 2) in ('00','05','10','15','20','25','30','35','40','45','50','55')
  and f.run_volume >= 1000000
  and f.close_price between 0.2 and 30
  and f.run_return_pct between 0.5 and 8
  and f.close_price < f.run_vwap
  and f.close_price >= f.run_low + ((f.run_high - f.run_low) * 0.35)
union all
select
  'uptrend_breakout_t2_stop1',
  f.trade_date,
  f.symbol,
  f.bar_time,
  f.close_price,
  2.0,
  1.0,
  r.regime,
  'breakout'
from market_rt.strategy_lab_live_safe_features f
join market_rt.backtest_live_safe_regime r
  on r.trade_date = f.trade_date and r.bar_time = f.bar_time
where r.regime = 'uptrend'
  and substring(f.bar_time, 12, 5) >= '10:15'
  and substring(f.bar_time, 12, 5) < '14:30'
  and substring(f.bar_time, 15, 2) in ('00','05','10','15','20','25','30','35','40','45','50','55')
  and f.prev_run_high is not null
  and f.run_volume >= 1000000
  and f.close_price between 0.2 and 30
  and f.run_return_pct between 1 and 12
  and f.close_price >= f.prev_run_high * 1.002
union all
select
  'uptrend_high_hold_t15_stop1',
  f.trade_date,
  f.symbol,
  f.bar_time,
  f.close_price,
  1.5,
  1.0,
  r.regime,
  'high_hold'
from market_rt.strategy_lab_live_safe_features f
join market_rt.backtest_live_safe_regime r
  on r.trade_date = f.trade_date and r.bar_time = f.bar_time
where r.regime = 'uptrend'
  and substring(f.bar_time, 12, 5) >= '10:15'
  and substring(f.bar_time, 12, 5) < '14:30'
  and substring(f.bar_time, 15, 2) in ('00','05','10','15','20','25','30','35','40','45','50','55')
  and f.run_volume >= 1000000
  and f.close_price between 0.2 and 30
  and f.run_return_pct between 1 and 10
  and f.run_high > 0
  and f.close_price >= f.run_high * 0.985;

create or replace table market_rt.strategy_lab_live_safe_entries as
select c.*
from market_rt.strategy_lab_live_safe_candidates c
join (
  select strategy_name, trade_date, symbol, min(entry_time) as entry_time
  from market_rt.strategy_lab_live_safe_candidates
  group by strategy_name, trade_date, symbol
) m
  on m.strategy_name = c.strategy_name
 and m.trade_date = c.trade_date
 and m.symbol = c.symbol
 and m.entry_time = c.entry_time;

create or replace table market_rt.strategy_lab_live_safe_hits as
select
  e.strategy_name,
  e.strategy_group,
  e.trade_date,
  e.symbol,
  e.entry_time,
  e.entry_price,
  e.target_pct,
  e.stop_pct,
  e.regime,
  e.entry_price * (1 + e.target_pct / 100.0) as target_price,
  e.entry_price * (1 - e.stop_pct / 100.0) as stop_price,
  min(case when b.high_price >= e.entry_price * (1 + e.target_pct / 100.0) * 1.005 then b.bar_time else null end) as target_hit_time,
  min(case when b.low_price <= e.entry_price * (1 - e.stop_pct / 100.0) then b.bar_time else null end) as stop_hit_time
from market_rt.strategy_lab_live_safe_entries e
join market_rt.backtest_current_strategy_bars b
  on b.trade_date = e.trade_date
 and b.symbol = e.symbol
 and b.bar_time >= e.entry_time
group by
  e.strategy_name,
  e.strategy_group,
  e.trade_date,
  e.symbol,
  e.entry_time,
  e.entry_price,
  e.target_pct,
  e.stop_pct,
  e.regime;

create or replace table market_rt.strategy_lab_live_safe_results as
select
  h.strategy_name,
  h.strategy_group,
  h.trade_date,
  h.symbol,
  h.entry_time,
  h.entry_price,
  h.target_pct,
  h.stop_pct,
  h.regime,
  h.target_price,
  h.stop_price,
  h.target_hit_time,
  h.stop_hit_time,
  l.last_close,
  case
    when h.stop_hit_time is not null and (h.target_hit_time is null or h.stop_hit_time <= h.target_hit_time) then h.stop_price
    when h.target_hit_time is not null then h.target_price
    else l.last_close
  end as exit_price,
  case
    when h.stop_hit_time is not null and (h.target_hit_time is null or h.stop_hit_time <= h.target_hit_time) then 'stop'
    when h.target_hit_time is not null then 'target'
    else 'eod'
  end as reason,
  (((case
    when h.stop_hit_time is not null and (h.target_hit_time is null or h.stop_hit_time <= h.target_hit_time) then h.stop_price
    when h.target_hit_time is not null then h.target_price
    else l.last_close
  end / h.entry_price) - 1) * 100) - 0.5 as pnl_pct
from market_rt.strategy_lab_live_safe_hits h
join (
  select
    d.trade_date,
    d.symbol,
    b.close_price as last_close
  from market_rt.backtest_current_strategy_daily d
  join market_rt.backtest_current_strategy_bars b
    on b.trade_date = d.trade_date
   and b.symbol = d.symbol
   and b.bar_time = d.last_bar_time
) l
  on l.trade_date = h.trade_date
 and l.symbol = h.symbol;

create or replace table market_rt.strategy_lab_live_safe_summary as
select
  strategy_name,
  strategy_group,
  count(*) as trades,
  sum(case when pnl_pct > 0 then 1 else 0 end) as wins,
  sum(case when pnl_pct <= 0 then 1 else 0 end) as losses,
  avg(pnl_pct) as avg_pnl_pct,
  sum(pnl_pct) as total_pnl_pct,
  min(pnl_pct) as worst_pnl_pct,
  max(pnl_pct) as best_pnl_pct
from market_rt.strategy_lab_live_safe_results
group by strategy_name, strategy_group;

select
  strategy_name,
  strategy_group,
  trades,
  wins,
  losses,
  avg_pnl_pct,
  total_pnl_pct,
  worst_pnl_pct,
  best_pnl_pct
from market_rt.strategy_lab_live_safe_summary
order by avg_pnl_pct desc;
