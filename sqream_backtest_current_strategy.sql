create or replace table market_rt.backtest_current_strategy_bars as
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
  and bar_time <= '2026-06-15T23:59:59'
group by
  substring(bar_time, 1, 10),
  symbol,
  bar_time;

create or replace table market_rt.backtest_current_strategy_daily as
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
  d.vwap_price,
  ((l.close_price / o.open_price) - 1) * 100 as day_return_pct,
  ((d.day_high / d.day_low) - 1) * 100 as range_pct,
  d.day_low + ((d.day_high - d.day_low) * 0.25) as lower_range_price
from (
  select
    trade_date,
    symbol,
    min(bar_time) as first_bar_time,
    max(bar_time) as last_bar_time,
    max(high_price) as day_high,
    min(low_price) as day_low,
    sum(volume_count) as total_volume,
    sum(close_price * volume_count) / sum(volume_count) as vwap_price
  from market_rt.backtest_current_strategy_bars
  group by trade_date, symbol
) d
join market_rt.backtest_current_strategy_bars o
  on o.trade_date = d.trade_date and o.symbol = d.symbol and o.bar_time = d.first_bar_time
join market_rt.backtest_current_strategy_bars l
  on l.trade_date = d.trade_date and l.symbol = d.symbol and l.bar_time = d.last_bar_time
where o.open_price > 0
  and l.close_price > 0
  and d.day_low > 0
  and d.total_volume > 0;

create or replace table market_rt.backtest_current_strategy_regime as
select
  x.trade_date,
  x.symbol_count,
  x.up_count,
  (x.up_count * 100.0 / x.symbol_count) as breadth_up_pct,
  x.avg_return_pct,
  x.tqqq_return_pct,
  x.sqqq_return_pct,
  case
    when (x.up_count * 100.0 / x.symbol_count) >= 55
      and x.avg_return_pct >= 0.3
      and x.tqqq_return_pct > 0
      then 'uptrend'
    when (x.up_count * 100.0 / x.symbol_count) between 40 and 55
      and x.avg_return_pct between -0.5 and 0.5
      and x.tqqq_return_pct between -1.0 and 1.0
      then 'sideways'
    when (x.up_count * 100.0 / x.symbol_count) <= 45
      or x.avg_return_pct <= -0.5
      then 'downtrend'
    else 'sideways'
  end as regime
from (
  select
    trade_date,
    count(*) as symbol_count,
    sum(case when last_close > day_open then 1 else 0 end) as up_count,
    avg(day_return_pct) as avg_return_pct,
    sum(case when symbol = 'TQQQ' then day_return_pct else 0 end) as tqqq_return_pct,
    sum(case when symbol = 'SQQQ' then day_return_pct else 0 end) as sqqq_return_pct
  from market_rt.backtest_current_strategy_daily
  group by trade_date
) x;

create or replace table market_rt.backtest_current_strategy_universe as
select d.*
from market_rt.backtest_current_strategy_daily d
join market_rt.backtest_current_strategy_regime r
  on r.trade_date = d.trade_date
where r.regime = 'sideways'
  and d.total_volume >= 1000000
  and d.last_close >= 0.2
  and d.last_close <= 30
  and d.day_return_pct >= -5
  and d.day_return_pct <= 5
  and d.range_pct >= 3
  and d.range_pct <= 12;

create or replace table market_rt.backtest_current_strategy_entry_candidates as
select
  b.trade_date,
  b.symbol,
  b.bar_time as entry_time,
  b.close_price as entry_price,
  u.vwap_price,
  u.day_low,
  u.day_return_pct,
  u.total_volume,
  case
    when substring(b.bar_time, 12, 5) >= '11:30' and substring(b.bar_time, 12, 5) < '14:30' then 'midday_1130_1430'
    when substring(b.bar_time, 12, 5) >= '14:30' and substring(b.bar_time, 12, 5) < '15:30' then 'late_1430_1530'
    else 'blocked_time'
  end as time_bucket
from market_rt.backtest_current_strategy_bars b
join market_rt.backtest_current_strategy_universe u
  on u.trade_date = b.trade_date
 and u.symbol = b.symbol
where substring(b.bar_time, 15, 2) in ('00','05','10','15','20','25','30','35','40','45','50','55')
  and substring(b.bar_time, 12, 5) >= '11:30'
  and substring(b.bar_time, 12, 5) < '15:30'
  and b.close_price > 0
  and b.close_price <= u.lower_range_price
  and b.close_price < u.vwap_price;

create or replace table market_rt.backtest_current_strategy_entries as
select e.*
from market_rt.backtest_current_strategy_entry_candidates e
join (
  select trade_date, symbol, min(entry_time) as entry_time
  from market_rt.backtest_current_strategy_entry_candidates
  group by trade_date, symbol
) m
  on m.trade_date = e.trade_date
 and m.symbol = e.symbol
 and m.entry_time = e.entry_time;

create or replace table market_rt.backtest_current_strategy_hits as
select
  e.trade_date,
  e.symbol,
  e.entry_time,
  e.entry_price,
  e.time_bucket,
  e.vwap_price,
  e.day_low,
  e.day_return_pct,
  e.total_volume,
  e.entry_price * 1.03 as target_price,
  case
    when e.day_low * 0.995 < e.entry_price * 0.98 then e.day_low * 0.995
    else e.entry_price * 0.98
  end as stop_price,
  min(case when b.high_price >= e.entry_price * 1.03 * 1.005 then b.bar_time else null end) as target_hit_time,
  min(case
    when b.low_price <= case
      when e.day_low * 0.995 < e.entry_price * 0.98 then e.day_low * 0.995
      else e.entry_price * 0.98
    end then b.bar_time
    else null
  end) as stop_hit_time
from market_rt.backtest_current_strategy_entries e
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
  e.vwap_price,
  e.day_low,
  e.day_return_pct,
  e.total_volume;

create or replace table market_rt.backtest_current_strategy_results as
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
from market_rt.backtest_current_strategy_hits h
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

create or replace table market_rt.backtest_current_strategy_summary as
select
  trade_date,
  count(*) as trades,
  sum(case when pnl_pct > 0 then 1 else 0 end) as wins,
  sum(case when pnl_pct <= 0 then 1 else 0 end) as losses,
  avg(pnl_pct) as avg_pnl_pct,
  sum(pnl_pct) as total_pnl_pct,
  min(pnl_pct) as worst_pnl_pct,
  max(pnl_pct) as best_pnl_pct
from market_rt.backtest_current_strategy_results
group by trade_date;

select
  count(*) as trades,
  sum(case when pnl_pct > 0 then 1 else 0 end) as wins,
  sum(case when pnl_pct <= 0 then 1 else 0 end) as losses,
  avg(pnl_pct) as avg_pnl_pct,
  sum(pnl_pct) as total_pnl_pct,
  min(pnl_pct) as worst_pnl_pct,
  max(pnl_pct) as best_pnl_pct
from market_rt.backtest_current_strategy_results;

select
  trade_date,
  trades,
  wins,
  losses,
  avg_pnl_pct,
  total_pnl_pct,
  worst_pnl_pct,
  best_pnl_pct
from market_rt.backtest_current_strategy_summary
order by trade_date;

select
  r.trade_date,
  r.regime,
  r.breadth_up_pct,
  r.avg_return_pct,
  count(b.symbol) as trades,
  avg(b.pnl_pct) as avg_pnl_pct,
  sum(b.pnl_pct) as total_pnl_pct
from market_rt.backtest_current_strategy_regime r
left join market_rt.backtest_current_strategy_results b
  on b.trade_date = r.trade_date
group by
  r.trade_date,
  r.regime,
  r.breadth_up_pct,
  r.avg_return_pct
order by r.trade_date;
