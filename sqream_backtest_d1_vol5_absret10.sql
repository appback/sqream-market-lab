create or replace table market_rt.d1_backtest_bars as
select
  substring(bar_time, 1, 10) as trade_date,
  symbol,
  bar_time,
  max(open_price) as open_price,
  max(high_price) as high_price,
  min(low_price) as low_price,
  max(close_price) as close_price,
  max(volume_count) as volume_count
from market_rt.delayed_intraday_bars_raw
where bar_time >= '2026-05-27'
  and bar_time <= '2026-06-16T23:59:59'
group by
  substring(bar_time, 1, 10),
  symbol,
  bar_time;

create or replace table market_rt.d1_backtest_daily as
select
  d.trade_date,
  d.symbol,
  d.first_bar_time,
  d.last_bar_time,
  o.open_price as day_open,
  l.close_price as last_close,
  d.day_high,
  d.day_low,
  d.total_volume,
  ((l.close_price / o.open_price) - 1) * 100 as day_return_pct
from (
  select
    trade_date,
    symbol,
    min(bar_time) as first_bar_time,
    max(bar_time) as last_bar_time,
    max(high_price) as day_high,
    min(low_price) as day_low,
    sum(volume_count) as total_volume
  from market_rt.d1_backtest_bars
  group by trade_date, symbol
) d
join market_rt.d1_backtest_bars o
  on o.trade_date = d.trade_date
 and o.symbol = d.symbol
 and o.bar_time = d.first_bar_time
join market_rt.d1_backtest_bars l
  on l.trade_date = d.trade_date
 and l.symbol = d.symbol
 and l.bar_time = d.last_bar_time
where o.open_price > 0
  and l.close_price > 0
  and d.day_low > 0
  and d.total_volume > 0;

create or replace table market_rt.d1_backtest_market_dates as
select trade_date
from market_rt.d1_backtest_daily
group by trade_date;

create or replace table market_rt.d1_backtest_signals as
select
  d.trade_date as signal_date,
  n.trade_date as trade_date,
  d.symbol,
  d.last_close as signal_close,
  d.total_volume as signal_volume,
  avg(p.total_volume) as avg_prior_volume,
  count(*) as prior_days,
  d.day_return_pct as signal_return_pct,
  d.total_volume / avg(p.total_volume) as volume_x_prior,
  d.last_close * 1.02 as entry_price,
  d.last_close * 1.02 * 1.10 as target_price,
  d.last_close * 1.02 * 0.95 as stop_price
from market_rt.d1_backtest_daily d
join market_rt.d1_backtest_daily p
  on p.symbol = d.symbol
 and p.trade_date < d.trade_date
join (
  select
    m.trade_date as signal_date,
    min(n.trade_date) as trade_date
  from market_rt.d1_backtest_market_dates m
  join market_rt.d1_backtest_market_dates n
    on n.trade_date > m.trade_date
  group by m.trade_date
) n
  on n.signal_date = d.trade_date
group by
  d.trade_date,
  n.trade_date,
  d.symbol,
  d.last_close,
  d.total_volume,
  d.day_return_pct
having count(*) >= 3
   and d.total_volume / avg(p.total_volume) >= 5.0
   and d.day_return_pct between -10.0 and 10.0
   and d.last_close between 0.2 and 30.0;

create or replace table market_rt.d1_backtest_features as
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
  ((b.close_price / d.day_open) - 1) * 100 as run_return_pct
from market_rt.d1_backtest_bars b
join market_rt.d1_backtest_daily d
  on d.trade_date = b.trade_date
 and d.symbol = b.symbol
where b.bar_time >= d.first_bar_time
  and b.close_price > 0
  and b.volume_count > 0;

create or replace table market_rt.d1_backtest_regime as
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
from market_rt.d1_backtest_features
group by trade_date, bar_time;

create or replace table market_rt.d1_vol5_absret10_backtest_entries_raw as
select
  s.signal_date,
  s.trade_date,
  s.symbol,
  b.bar_time as entry_time,
  b.close_price as trigger_close_price,
  s.entry_price,
  s.target_price,
  s.stop_price,
  s.signal_volume,
  s.avg_prior_volume,
  s.volume_x_prior,
  s.signal_return_pct,
  r.regime,
  case
    when substring(b.bar_time, 12, 5) >= '09:30' and substring(b.bar_time, 12, 5) < '10:15' then 'opening_0930_1015'
    when substring(b.bar_time, 12, 5) >= '10:15' and substring(b.bar_time, 12, 5) < '11:30' then 'morning_1015_1130'
    when substring(b.bar_time, 12, 5) >= '11:30' and substring(b.bar_time, 12, 5) < '14:30' then 'midday_1130_1430'
    when substring(b.bar_time, 12, 5) >= '14:30' and substring(b.bar_time, 12, 5) < '15:30' then 'late_1430_1530'
    else 'blocked_time'
  end as time_bucket
from market_rt.d1_backtest_signals s
join market_rt.d1_backtest_bars b
  on b.trade_date = s.trade_date
 and b.symbol = s.symbol
join market_rt.d1_backtest_regime r
  on r.trade_date = b.trade_date
 and r.bar_time = b.bar_time
where substring(b.bar_time, 12, 5) >= '09:30'
  and substring(b.bar_time, 12, 5) < '15:30'
  and b.high_price >= s.entry_price;

create or replace table market_rt.d1_vol5_absret10_backtest_entries as
select e.*
from market_rt.d1_vol5_absret10_backtest_entries_raw e
join (
  select
    signal_date,
    trade_date,
    symbol,
    min(entry_time) as entry_time
  from market_rt.d1_vol5_absret10_backtest_entries_raw
  group by signal_date, trade_date, symbol
) m
  on m.signal_date = e.signal_date
 and m.trade_date = e.trade_date
 and m.symbol = e.symbol
 and m.entry_time = e.entry_time;

create or replace table market_rt.d1_vol5_absret10_backtest_hits as
select
  e.signal_date,
  e.trade_date,
  e.symbol,
  e.entry_time,
  e.entry_price,
  e.target_price,
  e.stop_price,
  e.signal_volume,
  e.avg_prior_volume,
  e.volume_x_prior,
  e.signal_return_pct,
  e.regime,
  e.time_bucket,
  min(case when b.high_price >= e.target_price then b.bar_time else null end) as target_hit_time,
  min(case when b.low_price <= e.stop_price then b.bar_time else null end) as stop_hit_time
from market_rt.d1_vol5_absret10_backtest_entries e
join market_rt.d1_backtest_bars b
  on b.trade_date = e.trade_date
 and b.symbol = e.symbol
 and b.bar_time >= e.entry_time
group by
  e.signal_date,
  e.trade_date,
  e.symbol,
  e.entry_time,
  e.entry_price,
  e.target_price,
  e.stop_price,
  e.signal_volume,
  e.avg_prior_volume,
  e.volume_x_prior,
  e.signal_return_pct,
  e.regime,
  e.time_bucket;

create or replace table market_rt.d1_vol5_absret10_backtest_results as
select
  h.signal_date,
  h.trade_date,
  h.symbol,
  h.entry_time,
  h.entry_price,
  h.target_price,
  h.stop_price,
  h.volume_x_prior,
  h.signal_return_pct,
  h.regime,
  h.time_bucket,
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
  case
    when h.stop_hit_time is not null and (h.target_hit_time is null or h.stop_hit_time <= h.target_hit_time) then h.stop_hit_time
    when h.target_hit_time is not null then h.target_hit_time
    else l.last_bar_time
  end as exit_time,
  (((case
    when h.stop_hit_time is not null and (h.target_hit_time is null or h.stop_hit_time <= h.target_hit_time) then h.stop_price
    when h.target_hit_time is not null then h.target_price
    else l.last_close
  end / h.entry_price) - 1) * 100) as pnl_pct
from market_rt.d1_vol5_absret10_backtest_hits h
join market_rt.d1_backtest_daily l
  on l.trade_date = h.trade_date
 and l.symbol = h.symbol;

create or replace table market_rt.d1_vol5_absret10_backtest_summary as
select
  regime,
  time_bucket,
  count(*) as trades,
  sum(case when pnl_pct > 0 then 1 else 0 end) as wins,
  sum(case when pnl_pct <= 0 then 1 else 0 end) as losses,
  avg(pnl_pct) as avg_pnl_pct,
  sum(pnl_pct) as total_pnl_pct,
  min(pnl_pct) as worst_pnl_pct,
  max(pnl_pct) as best_pnl_pct
from market_rt.d1_vol5_absret10_backtest_results
group by regime, time_bucket;

select
  count(*) as signals,
  sum(case when trade_date is not null then 1 else 0 end) as tradable_signals
from market_rt.d1_backtest_signals;

select
  count(*) as trades,
  sum(case when pnl_pct > 0 then 1 else 0 end) as wins,
  sum(case when pnl_pct <= 0 then 1 else 0 end) as losses,
  avg(pnl_pct) as avg_pnl_pct,
  sum(pnl_pct) as total_pnl_pct,
  min(pnl_pct) as worst_pnl_pct,
  max(pnl_pct) as best_pnl_pct
from market_rt.d1_vol5_absret10_backtest_results;

select
  regime,
  time_bucket,
  trades,
  wins,
  losses,
  avg_pnl_pct,
  total_pnl_pct,
  worst_pnl_pct,
  best_pnl_pct
from market_rt.d1_vol5_absret10_backtest_summary
order by avg_pnl_pct desc;

select
  trade_date,
  symbol,
  entry_time,
  entry_price,
  exit_time,
  exit_price,
  reason,
  pnl_pct,
  volume_x_prior,
  signal_return_pct,
  regime,
  time_bucket
from market_rt.d1_vol5_absret10_backtest_results
order by trade_date, symbol
limit 50;
