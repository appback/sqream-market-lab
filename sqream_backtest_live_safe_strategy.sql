create or replace table market_rt.backtest_live_safe_features as
select
  b.trade_date,
  b.symbol,
  b.bar_time,
  b.open_price,
  b.high_price,
  b.low_price,
  b.close_price,
  b.volume_count,
  d.day_open,
  max(b.high_price) over (
    partition by b.trade_date, b.symbol
    order by b.bar_time
    rows between unbounded preceding and current row
  ) as run_high,
  min(b.low_price) over (
    partition by b.trade_date, b.symbol
    order by b.bar_time
    rows between unbounded preceding and current row
  ) as run_low,
  sum(b.volume_count) over (
    partition by b.trade_date, b.symbol
    order by b.bar_time
    rows between unbounded preceding and current row
  ) as run_volume,
  sum(b.close_price * b.volume_count) over (
    partition by b.trade_date, b.symbol
    order by b.bar_time
    rows between unbounded preceding and current row
  ) / sum(b.volume_count) over (
    partition by b.trade_date, b.symbol
    order by b.bar_time
    rows between unbounded preceding and current row
  ) as run_vwap,
  ((b.close_price / d.day_open) - 1) * 100 as run_return_pct
from market_rt.backtest_current_strategy_bars b
join market_rt.backtest_current_strategy_daily d
  on d.trade_date = b.trade_date
 and d.symbol = b.symbol
where b.bar_time >= d.first_bar_time
  and b.close_price > 0
  and b.volume_count > 0;

create or replace table market_rt.backtest_live_safe_regime as
select
  trade_date,
  bar_time,
  count(*) as symbol_count,
  sum(case when close_price > day_open then 1 else 0 end) as up_count,
  (sum(case when close_price > day_open then 1 else 0 end) * 100.0 / count(*)) as breadth_up_pct,
  avg(run_return_pct) as avg_return_pct,
  sum(case when symbol = 'TQQQ' then run_return_pct else 0 end) as tqqq_return_pct,
  sum(case when symbol = 'SQQQ' then run_return_pct else 0 end) as sqqq_return_pct,
  case
    when (sum(case when close_price > day_open then 1 else 0 end) * 100.0 / count(*)) >= 55
      and avg(run_return_pct) >= 0.3
      and sum(case when symbol = 'TQQQ' then run_return_pct else 0 end) > 0
      then 'uptrend'
    when (sum(case when close_price > day_open then 1 else 0 end) * 100.0 / count(*)) between 40 and 55
      and avg(run_return_pct) between -0.5 and 0.5
      and sum(case when symbol = 'TQQQ' then run_return_pct else 0 end) between -1.0 and 1.0
      then 'sideways'
    when (sum(case when close_price > day_open then 1 else 0 end) * 100.0 / count(*)) <= 45
      or avg(run_return_pct) <= -0.5
      then 'downtrend'
    else 'sideways'
  end as regime
from market_rt.backtest_live_safe_features
group by trade_date, bar_time;

create or replace table market_rt.backtest_live_safe_entry_candidates as
select
  f.trade_date,
  f.symbol,
  f.bar_time as entry_time,
  f.close_price as entry_price,
  f.run_vwap,
  f.run_low,
  f.run_high,
  f.run_volume,
  f.run_return_pct,
  ((f.run_high / f.run_low) - 1) * 100 as run_range_pct,
  r.regime,
  'midday_1130_1430' as time_bucket
from market_rt.backtest_live_safe_features f
join market_rt.backtest_live_safe_regime r
  on r.trade_date = f.trade_date
 and r.bar_time = f.bar_time
where r.regime = 'sideways'
  and substring(f.bar_time, 12, 5) >= '11:30'
  and substring(f.bar_time, 12, 5) < '14:30'
  and substring(f.bar_time, 15, 2) in ('00','05','10','15','20','25','30','35','40','45','50','55')
  and f.run_volume >= 1000000
  and f.close_price >= 0.2
  and f.close_price <= 30
  and f.run_low > 0
  and f.run_return_pct >= -5
  and f.run_return_pct <= 5
  and ((f.run_high / f.run_low) - 1) * 100 >= 3
  and ((f.run_high / f.run_low) - 1) * 100 <= 12
  and f.close_price <= f.run_low + ((f.run_high - f.run_low) * 0.25)
  and f.close_price < f.run_vwap;

create or replace table market_rt.backtest_live_safe_entries as
select e.*
from market_rt.backtest_live_safe_entry_candidates e
join (
  select trade_date, symbol, min(entry_time) as entry_time
  from market_rt.backtest_live_safe_entry_candidates
  group by trade_date, symbol
) m
  on m.trade_date = e.trade_date
 and m.symbol = e.symbol
 and m.entry_time = e.entry_time;

create or replace table market_rt.backtest_live_safe_hits as
select
  e.trade_date,
  e.symbol,
  e.entry_time,
  e.entry_price,
  e.time_bucket,
  e.run_vwap,
  e.run_low,
  e.run_high,
  e.run_volume,
  e.run_return_pct,
  e.entry_price * 1.03 as target_price,
  case
    when e.run_low * 0.995 < e.entry_price * 0.98 then e.run_low * 0.995
    else e.entry_price * 0.98
  end as stop_price,
  min(case when b.high_price >= e.entry_price * 1.03 * 1.005 then b.bar_time else null end) as target_hit_time,
  min(case
    when b.low_price <= case
      when e.run_low * 0.995 < e.entry_price * 0.98 then e.run_low * 0.995
      else e.entry_price * 0.98
    end then b.bar_time
    else null
  end) as stop_hit_time
from market_rt.backtest_live_safe_entries e
join market_rt.backtest_current_strategy_bars b
  on b.trade_date = e.trade_date
 and b.symbol = e.symbol
 and b.bar_time >= e.entry_time
group by
  e.trade_date,
  e.symbol,
  e.entry_time,
  e.entry_price,
  e.time_bucket,
  e.run_vwap,
  e.run_low,
  e.run_high,
  e.run_volume,
  e.run_return_pct;

create or replace table market_rt.backtest_live_safe_results as
select
  h.trade_date,
  h.symbol,
  h.entry_time,
  h.entry_price,
  h.time_bucket,
  h.target_price,
  h.stop_price,
  h.target_hit_time,
  h.stop_hit_time,
  l.last_bar_time,
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
from market_rt.backtest_live_safe_hits h
join (
  select
    d.trade_date,
    d.symbol,
    d.last_bar_time,
    b.close_price as last_close
  from market_rt.backtest_current_strategy_daily d
  join market_rt.backtest_current_strategy_bars b
    on b.trade_date = d.trade_date
   and b.symbol = d.symbol
   and b.bar_time = d.last_bar_time
) l
  on l.trade_date = h.trade_date
 and l.symbol = h.symbol;

create or replace table market_rt.backtest_live_safe_summary as
select
  trade_date,
  count(*) as trades,
  sum(case when pnl_pct > 0 then 1 else 0 end) as wins,
  sum(case when pnl_pct <= 0 then 1 else 0 end) as losses,
  avg(pnl_pct) as avg_pnl_pct,
  sum(pnl_pct) as total_pnl_pct,
  min(pnl_pct) as worst_pnl_pct,
  max(pnl_pct) as best_pnl_pct
from market_rt.backtest_live_safe_results
group by trade_date;

select
  count(*) as trades,
  sum(case when pnl_pct > 0 then 1 else 0 end) as wins,
  sum(case when pnl_pct <= 0 then 1 else 0 end) as losses,
  avg(pnl_pct) as avg_pnl_pct,
  sum(pnl_pct) as total_pnl_pct,
  min(pnl_pct) as worst_pnl_pct,
  max(pnl_pct) as best_pnl_pct
from market_rt.backtest_live_safe_results;

select
  trade_date,
  trades,
  wins,
  losses,
  avg_pnl_pct,
  total_pnl_pct,
  worst_pnl_pct,
  best_pnl_pct
from market_rt.backtest_live_safe_summary
order by trade_date;

select
  reason,
  count(*) as trades,
  avg(pnl_pct) as avg_pnl_pct,
  sum(pnl_pct) as total_pnl_pct
from market_rt.backtest_live_safe_results
group by reason
order by reason;
