create or replace table market_rt.strategy_lab_exit_grid as
select 0.5 as target_pct, 0.5 as stop_pct
union all select 0.5, 1.0
union all select 1.0, 0.5
union all select 1.0, 1.0
union all select 1.5, 0.5
union all select 1.5, 1.0
union all select 2.0, 0.5
union all select 2.0, 1.0
union all select 3.0, 1.0
union all select 3.0, 1.5;

create or replace table market_rt.strategy_lab_exit_grid_entries as
select
  c.strategy_name as entry_rule,
  c.strategy_group,
  c.trade_date,
  c.symbol,
  c.entry_time,
  c.entry_price,
  g.target_pct,
  g.stop_pct,
  c.regime
from market_rt.strategy_lab_live_safe_candidates c
join market_rt.strategy_lab_exit_grid g
  on 1 = 1;

create or replace table market_rt.strategy_lab_exit_grid_first_entries as
select e.*
from market_rt.strategy_lab_exit_grid_entries e
join (
  select entry_rule, target_pct, stop_pct, trade_date, symbol, min(entry_time) as entry_time
  from market_rt.strategy_lab_exit_grid_entries
  group by entry_rule, target_pct, stop_pct, trade_date, symbol
) m
  on m.entry_rule = e.entry_rule
 and m.target_pct = e.target_pct
 and m.stop_pct = e.stop_pct
 and m.trade_date = e.trade_date
 and m.symbol = e.symbol
 and m.entry_time = e.entry_time;

create or replace table market_rt.strategy_lab_exit_grid_hits as
select
  e.entry_rule,
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
from market_rt.strategy_lab_exit_grid_first_entries e
join market_rt.backtest_current_strategy_bars b
  on b.trade_date = e.trade_date
 and b.symbol = e.symbol
 and b.bar_time >= e.entry_time
group by
  e.entry_rule,
  e.strategy_group,
  e.trade_date,
  e.symbol,
  e.entry_time,
  e.entry_price,
  e.target_pct,
  e.stop_pct,
  e.regime;

create or replace table market_rt.strategy_lab_exit_grid_results as
select
  h.entry_rule,
  h.strategy_group,
  h.trade_date,
  h.symbol,
  h.entry_time,
  h.entry_price,
  h.target_pct,
  h.stop_pct,
  h.regime,
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
from market_rt.strategy_lab_exit_grid_hits h
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

create or replace table market_rt.strategy_lab_exit_grid_summary as
select
  entry_rule,
  strategy_group,
  target_pct,
  stop_pct,
  count(*) as trades,
  sum(case when pnl_pct > 0 then 1 else 0 end) as wins,
  sum(case when pnl_pct <= 0 then 1 else 0 end) as losses,
  avg(pnl_pct) as avg_pnl_pct,
  sum(pnl_pct) as total_pnl_pct,
  min(pnl_pct) as worst_pnl_pct,
  max(pnl_pct) as best_pnl_pct
from market_rt.strategy_lab_exit_grid_results
group by entry_rule, strategy_group, target_pct, stop_pct;

select
  entry_rule,
  strategy_group,
  target_pct,
  stop_pct,
  trades,
  wins,
  losses,
  avg_pnl_pct,
  total_pnl_pct,
  worst_pnl_pct,
  best_pnl_pct
from market_rt.strategy_lab_exit_grid_summary
where trades >= 50
order by avg_pnl_pct desc
limit 20;
