create or replace table market_rt.delayed_surge_candidates_all as
select
  b.symbol,
  b.bar_time,
  b.open_price,
  b.high_price,
  b.low_price,
  b.close_price,
  b.volume_count,
  ((b.close_price / d.day_open) - 1.0) * 100.0 as day_return_pct,
  d.day_high,
  ((b.close_price / d.day_high) - 1.0) * 100.0 as close_from_day_high_pct,
  b.close_price * 0.65 as pullback_35_entry_price,
  b.close_price * 0.65 * 1.25 as target_price,
  b.close_price * 0.65 * 0.85 as stop_price
from market_rt.delayed_intraday_bars_latest b
join (
  select
    o.symbol,
    o.open_price as day_open,
    h.day_high
  from market_rt.delayed_intraday_bars_latest o
  join (
    select symbol, min(bar_time) as first_bar_time, max(high_price) as day_high
    from market_rt.delayed_intraday_bars_latest
    group by symbol
  ) h
    on o.symbol = h.symbol
   and o.bar_time = h.first_bar_time
) d
  on b.symbol = d.symbol
where d.day_open > 0
  and ((b.close_price / d.day_open) - 1.0) * 100.0 >= 100.0;

create or replace table market_rt.delayed_surge_candidates as
select *
from market_rt.delayed_surge_candidates_all
where close_price between 3.0 and 10.0;

create or replace table market_rt.delayed_surge_symbols_all as
select
  symbol,
  min(bar_time) as first_signal_time,
  max(day_return_pct) as max_day_return_pct,
  max(close_price) as max_close_price,
  min(pullback_35_entry_price) as min_pullback_35_entry_price,
  max(target_price) as max_target_price,
  min(stop_price) as min_stop_price
from market_rt.delayed_surge_candidates_all
group by symbol;

create or replace table market_rt.delayed_pullback_entries as
select
  c.symbol,
  c.bar_time as signal_time,
  min(b.bar_time) as entry_time,
  c.pullback_35_entry_price as entry_price,
  c.target_price,
  c.stop_price
from market_rt.delayed_surge_candidates c
join market_rt.delayed_intraday_bars_latest b
  on c.symbol = b.symbol
 and b.bar_time >= c.bar_time
 and b.low_price <= c.pullback_35_entry_price
group by c.symbol, c.bar_time, c.pullback_35_entry_price, c.target_price, c.stop_price;

select count(*) from market_rt.delayed_surge_candidates_all;
select count(*) from market_rt.delayed_surge_symbols_all;
select count(*) from market_rt.delayed_surge_candidates;
select count(*) from market_rt.delayed_pullback_entries;

create or replace table market_rt.delayed_pre_surge_watch_symbols_all as
select *
from (
  select
    a.symbol,
    a.first_bar_time,
    a.last_bar_time,
    f.open_price as day_open,
    l.close_price as last_close,
    a.day_high,
    a.day_low,
    a.total_volume,
    a.max_bar_volume,
    a.avg_bar_volume,
    case when f.open_price > 0 then ((l.close_price / f.open_price) - 1.0) * 100.0 else -999.0 end as day_return_pct,
    case when a.day_low > 0 then ((a.day_high / a.day_low) - 1.0) * 100.0 else 0.0 end as intraday_range_pct,
    case when a.avg_bar_volume > 0 then (a.max_bar_volume / a.avg_bar_volume) else 0.0 end as minute_volume_burst_x,
    case when f.open_price > 0 then ((a.day_high / f.open_price) - 1.0) * 100.0 else 0.0 end as high_from_open_pct
  from (
    select
      symbol,
      min(bar_time) as first_bar_time,
      max(bar_time) as last_bar_time,
      max(high_price) as day_high,
      min(low_price) as day_low,
      sum(volume_count * 1.0) as total_volume,
      max(volume_count * 1.0) as max_bar_volume,
      avg(volume_count * 1.0) as avg_bar_volume
    from market_rt.delayed_intraday_bars_latest
    group by symbol
  ) a
  join market_rt.delayed_intraday_bars_latest f
    on a.symbol = f.symbol
   and a.first_bar_time = f.bar_time
  join market_rt.delayed_intraday_bars_latest l
    on a.symbol = l.symbol
   and a.last_bar_time = l.bar_time
) x
where day_open > 0
  and day_low > 0
  and avg_bar_volume > 0
  and last_close between 0.2 and 15.0
  and total_volume >= 50000
  and day_return_pct >= -15.0
  and day_return_pct <= 35.0
  and intraday_range_pct >= 8.0
  and (
    minute_volume_burst_x >= 5.0
    or total_volume >= 500000
  );

select count(*) from market_rt.delayed_pre_surge_watch_symbols_all;

select
  symbol,
  bar_time,
  close_price,
  day_return_pct,
  close_from_day_high_pct,
  pullback_35_entry_price,
  target_price,
  stop_price
from market_rt.delayed_surge_candidates
order by day_return_pct desc
limit 20;

select
  symbol,
  bar_time,
  close_price,
  day_return_pct,
  close_from_day_high_pct,
  pullback_35_entry_price,
  target_price,
  stop_price
from market_rt.delayed_surge_candidates_all
order by day_return_pct desc
limit 20;

select
  symbol,
  last_bar_time,
  last_close,
  total_volume,
  day_return_pct,
  intraday_range_pct,
  minute_volume_burst_x,
  high_from_open_pct
from market_rt.delayed_pre_surge_watch_symbols_all
order by minute_volume_burst_x desc, total_volume desc
limit 20;
