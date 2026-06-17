create or replace table market_rt.sideways_5m_target3_universe as
select
  x.symbol,
  x.first_bar_time,
  x.last_bar_time,
  x.day_open,
  x.last_close,
  x.day_high,
  x.day_low,
  x.total_volume,
  ((x.last_close / x.day_open) - 1) * 100 as day_return_pct,
  ((x.day_high / x.day_low) - 1) * 100 as range_pct
from (
  select
    s.symbol,
    s.first_bar_time,
    s.last_bar_time,
    o.open_price as day_open,
    l.close_price as last_close,
    s.day_high,
    s.day_low,
    s.total_volume
  from (
    select
      symbol,
      min(bar_time) as first_bar_time,
      max(bar_time) as last_bar_time,
      max(high_price) as day_high,
      min(low_price) as day_low,
      sum(volume_count) as total_volume
    from market_rt.delayed_intraday_bars_latest
    group by symbol
  ) s
  join market_rt.delayed_intraday_bars_latest o
    on o.symbol = s.symbol and o.bar_time = s.first_bar_time
  join market_rt.delayed_intraday_bars_latest l
    on l.symbol = s.symbol and l.bar_time = s.last_bar_time
) x
where x.total_volume >= 1000000
  and x.last_close >= 0.2
  and x.last_close <= 30
  and x.day_open > 0
  and x.day_low > 0
  and ((x.last_close / x.day_open) - 1) * 100 >= -5
  and ((x.last_close / x.day_open) - 1) * 100 <= 5
  and ((x.day_high / x.day_low) - 1) * 100 >= 3
  and ((x.day_high / x.day_low) - 1) * 100 <= 12;

create or replace table market_rt.sideways_5m_target3_entries as
select
  'sideways_high_volume_5m_target3' as strategy_name,
  b.symbol,
  b.bar_time as entry_time,
  b.close_price as entry_price,
  b.close_price * 1.03 as target_price
from market_rt.delayed_intraday_bars_latest b
join market_rt.sideways_5m_target3_universe u
  on u.symbol = b.symbol
where substring(b.bar_time, 15, 2) in ('00','05','10','15','20','25','30','35','40','45','50','55')
  and b.close_price > 0;

create or replace table market_rt.sideways_5m_target3_hits as
select
  e.strategy_name,
  e.symbol,
  e.entry_time,
  e.entry_price,
  e.target_price,
  min(h.bar_time) as hit_time
from market_rt.sideways_5m_target3_entries e
left join market_rt.delayed_intraday_bars_latest h
  on h.symbol = e.symbol
 and h.bar_time >= e.entry_time
 and h.high_price >= e.target_price
group by
  e.strategy_name,
  e.symbol,
  e.entry_time,
  e.entry_price,
  e.target_price;

create or replace table market_rt.sideways_5m_target3_results as
select
  h.strategy_name,
  h.symbol,
  h.entry_time,
  h.entry_price,
  h.target_price,
  h.hit_time,
  case when h.hit_time is null then 0 else 1 end as target_hit,
  l.last_bar_time,
  l.last_close,
  case
    when h.hit_time is null then ((l.last_close / h.entry_price) - 1) * 100
    else 3.0
  end as pnl_pct
from market_rt.sideways_5m_target3_hits h
join (
  select
    m.symbol,
    m.last_bar_time,
    b.close_price as last_close
  from (
    select symbol, max(bar_time) as last_bar_time
    from market_rt.delayed_intraday_bars_latest
    group by symbol
  ) m
  join market_rt.delayed_intraday_bars_latest b
    on b.symbol = m.symbol and b.bar_time = m.last_bar_time
) l
  on l.symbol = h.symbol;
