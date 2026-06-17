create or replace table market_rt.breakout_candidate_param_grid as
select 0.1 as breakout_pct, 500000.0 as min_run_volume, 0.0 as rel_strength_pct, 55.0 as min_breadth, 2.0 as target_pct, 1.0 as stop_pct
union all select 0.1, 500000.0, 0.5, 55.0, 2.0, 1.0
union all select 0.1, 1000000.0, 0.5, 55.0, 3.0, 1.5
union all select 0.1, 2000000.0, 1.0, 55.0, 3.0, 1.5
union all select 0.2, 500000.0, 0.5, 55.0, 3.0, 1.5
union all select 0.2, 1000000.0, 0.5, 55.0, 3.0, 1.5
union all select 0.2, 2000000.0, 1.0, 55.0, 3.0, 1.5
union all select 0.2, 5000000.0, 1.0, 55.0, 3.0, 1.5
union all select 0.5, 500000.0, 0.5, 55.0, 3.0, 1.5
union all select 0.5, 1000000.0, 1.0, 55.0, 3.0, 1.5
union all select 0.5, 2000000.0, 1.0, 55.0, 4.0, 2.0
union all select 0.5, 5000000.0, 1.5, 55.0, 4.0, 2.0
union all select 1.0, 500000.0, 1.0, 55.0, 4.0, 2.0
union all select 1.0, 1000000.0, 1.0, 55.0, 4.0, 2.0
union all select 1.0, 2000000.0, 1.5, 55.0, 4.0, 2.0
union all select 1.0, 5000000.0, 2.0, 55.0, 4.0, 2.0
union all select 0.2, 1000000.0, 1.0, 60.0, 3.0, 1.5
union all select 0.5, 1000000.0, 1.0, 60.0, 3.0, 1.5
union all select 0.5, 2000000.0, 1.5, 60.0, 4.0, 2.0
union all select 1.0, 2000000.0, 2.0, 60.0, 4.0, 2.0
union all select 0.5, 1000000.0, 1.5, 65.0, 3.0, 1.5
union all select 1.0, 1000000.0, 2.0, 65.0, 4.0, 2.0;

create or replace table market_rt.breakout_candidate_grid_entries_raw as
select
  'uptrend_breakout_grid' as strategy_family,
  f.trade_date,
  f.symbol,
  f.bar_time as entry_time,
  f.close_price as entry_price,
  f.run_volume,
  f.run_return_pct,
  r.avg_return_pct,
  r.breadth_up_pct,
  f.run_return_pct - r.avg_return_pct as rel_strength_pct,
  p.breakout_pct,
  p.min_run_volume,
  p.rel_strength_pct as min_rel_strength_pct,
  p.min_breadth,
  p.target_pct,
  p.stop_pct
from market_rt.strategy_lab_live_safe_features f
join market_rt.backtest_live_safe_regime r
  on r.trade_date = f.trade_date
 and r.bar_time = f.bar_time
join market_rt.breakout_candidate_param_grid p
  on 1 = 1
where r.regime = 'uptrend'
  and r.breadth_up_pct >= p.min_breadth
  and substring(f.bar_time, 12, 5) >= '10:15'
  and substring(f.bar_time, 12, 5) < '14:30'
  and substring(f.bar_time, 15, 2) in ('00','05','10','15','20','25','30','35','40','45','50','55')
  and f.prev_run_high is not null
  and f.run_volume >= p.min_run_volume
  and f.close_price between 0.2 and 30
  and f.run_return_pct between 0.5 and 15
  and f.run_return_pct - r.avg_return_pct >= p.rel_strength_pct
  and f.close_price >= f.prev_run_high * (1 + p.breakout_pct / 100.0);

create or replace table market_rt.breakout_candidate_grid_entries as
select e.*
from market_rt.breakout_candidate_grid_entries_raw e
join (
  select
    breakout_pct,
    min_run_volume,
    min_rel_strength_pct,
    min_breadth,
    target_pct,
    stop_pct,
    trade_date,
    symbol,
    min(entry_time) as entry_time
  from market_rt.breakout_candidate_grid_entries_raw
  group by
    breakout_pct,
    min_run_volume,
    min_rel_strength_pct,
    min_breadth,
    target_pct,
    stop_pct,
    trade_date,
    symbol
) m
  on m.breakout_pct = e.breakout_pct
 and m.min_run_volume = e.min_run_volume
 and m.min_rel_strength_pct = e.min_rel_strength_pct
 and m.min_breadth = e.min_breadth
 and m.target_pct = e.target_pct
 and m.stop_pct = e.stop_pct
 and m.trade_date = e.trade_date
 and m.symbol = e.symbol
 and m.entry_time = e.entry_time;

create or replace table market_rt.breakout_candidate_grid_hits as
select
  e.strategy_family,
  e.trade_date,
  e.symbol,
  e.entry_time,
  e.entry_price,
  e.run_volume,
  e.run_return_pct,
  e.avg_return_pct,
  e.breadth_up_pct,
  e.rel_strength_pct,
  e.breakout_pct,
  e.min_run_volume,
  e.min_rel_strength_pct,
  e.min_breadth,
  e.target_pct,
  e.stop_pct,
  e.entry_price * (1 + e.target_pct / 100.0) as target_price,
  e.entry_price * (1 - e.stop_pct / 100.0) as stop_price,
  min(case when b.high_price >= e.entry_price * (1 + e.target_pct / 100.0) * 1.005 then b.bar_time else null end) as target_hit_time,
  min(case when b.low_price <= e.entry_price * (1 - e.stop_pct / 100.0) then b.bar_time else null end) as stop_hit_time
from market_rt.breakout_candidate_grid_entries e
join market_rt.backtest_current_strategy_bars b
  on b.trade_date = e.trade_date
 and b.symbol = e.symbol
 and b.bar_time >= e.entry_time
group by
  e.strategy_family,
  e.trade_date,
  e.symbol,
  e.entry_time,
  e.entry_price,
  e.run_volume,
  e.run_return_pct,
  e.avg_return_pct,
  e.breadth_up_pct,
  e.rel_strength_pct,
  e.breakout_pct,
  e.min_run_volume,
  e.min_rel_strength_pct,
  e.min_breadth,
  e.target_pct,
  e.stop_pct;

create or replace table market_rt.breakout_candidate_grid_results as
select
  h.strategy_family,
  h.trade_date,
  h.symbol,
  h.entry_time,
  h.entry_price,
  h.run_volume,
  h.run_return_pct,
  h.avg_return_pct,
  h.breadth_up_pct,
  h.rel_strength_pct,
  h.breakout_pct,
  h.min_run_volume,
  h.min_rel_strength_pct,
  h.min_breadth,
  h.target_pct,
  h.stop_pct,
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
from market_rt.breakout_candidate_grid_hits h
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

create or replace table market_rt.breakout_candidate_grid_summary as
select
  breakout_pct,
  min_run_volume,
  min_rel_strength_pct,
  min_breadth,
  target_pct,
  stop_pct,
  count(*) as trades,
  sum(case when pnl_pct > 0 then 1 else 0 end) as wins,
  sum(case when pnl_pct <= 0 then 1 else 0 end) as losses,
  avg(pnl_pct) as avg_pnl_pct,
  sum(pnl_pct) as total_pnl_pct,
  min(pnl_pct) as worst_pnl_pct,
  max(pnl_pct) as best_pnl_pct
from market_rt.breakout_candidate_grid_results
group by
  breakout_pct,
  min_run_volume,
  min_rel_strength_pct,
  min_breadth,
  target_pct,
  stop_pct;

select
  breakout_pct,
  min_run_volume,
  min_rel_strength_pct,
  min_breadth,
  target_pct,
  stop_pct,
  trades,
  wins,
  losses,
  avg_pnl_pct,
  total_pnl_pct,
  worst_pnl_pct,
  best_pnl_pct
from market_rt.breakout_candidate_grid_summary
where trades >= 20
order by avg_pnl_pct desc
limit 20;
