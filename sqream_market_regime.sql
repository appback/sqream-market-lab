create or replace table market_rt.market_regime_current as
select
  x.latest_bar_time,
  x.symbol_count,
  x.up_count,
  (x.up_count * 100.0 / x.symbol_count) as breadth_up_pct,
  x.avg_return_pct,
  x.min_return_pct,
  x.max_return_pct,
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
  end as regime,
  case
    when (x.up_count * 100.0 / x.symbol_count) >= 55
      and x.avg_return_pct >= 0.3
      and x.tqqq_return_pct > 0
      then 'momentum_breakout_size_100_pct'
    when (x.up_count * 100.0 / x.symbol_count) between 40 and 55
      and x.avg_return_pct between -0.5 and 0.5
      and x.tqqq_return_pct between -1.0 and 1.0
      then 'sideways_reversion_size_60_pct'
    when (x.up_count * 100.0 / x.symbol_count) <= 45
      or x.avg_return_pct <= -0.5
      then 'defensive_size_20_pct_or_cash'
    else 'sideways_reversion_size_40_pct'
  end as recommended_allocation_rule
from (
  select
    b.latest_bar_time,
    b.symbol_count,
    b.up_count,
    b.avg_return_pct,
    b.min_return_pct,
    b.max_return_pct,
    sum(case when i.symbol = 'TQQQ' then i.ret_pct else 0 end) as tqqq_return_pct,
    sum(case when i.symbol = 'SQQQ' then i.ret_pct else 0 end) as sqqq_return_pct
  from (
    select
      max(last_bar_time) as latest_bar_time,
      count(*) as symbol_count,
      sum(up_flag) as up_count,
      avg(ret_pct) as avg_return_pct,
      min(ret_pct) as min_return_pct,
      max(ret_pct) as max_return_pct
    from (
      select
        d.symbol,
        d.last_bar_time,
        case when d.last_close > d.day_open then 1 else 0 end as up_flag,
        ((d.last_close / d.day_open) - 1) * 100 as ret_pct
      from (
        select
          s.symbol,
          s.last_bar_time,
          o.open_price as day_open,
          l.close_price as last_close
        from (
          select symbol, min(bar_time) as first_bar_time, max(bar_time) as last_bar_time
          from market_rt.delayed_intraday_bars_latest
          group by symbol
        ) s
        join market_rt.delayed_intraday_bars_latest o
          on o.symbol = s.symbol and o.bar_time = s.first_bar_time
        join market_rt.delayed_intraday_bars_latest l
          on l.symbol = s.symbol and l.bar_time = s.last_bar_time
        where o.open_price > 0 and l.close_price > 0
      ) d
    ) r
  ) b
  join (
    select
      d.symbol,
      ((d.last_close / d.day_open) - 1) * 100 as ret_pct
    from (
      select
        s.symbol,
        o.open_price as day_open,
        l.close_price as last_close
      from (
        select symbol, min(bar_time) as first_bar_time, max(bar_time) as last_bar_time
        from market_rt.delayed_intraday_bars_latest
        where symbol in ('TQQQ', 'SQQQ')
        group by symbol
      ) s
      join market_rt.delayed_intraday_bars_latest o
        on o.symbol = s.symbol and o.bar_time = s.first_bar_time
      join market_rt.delayed_intraday_bars_latest l
        on l.symbol = s.symbol and l.bar_time = s.last_bar_time
      where o.open_price > 0 and l.close_price > 0
    ) d
  ) i
    on 1 = 1
  group by
    b.latest_bar_time,
    b.symbol_count,
    b.up_count,
    b.avg_return_pct,
    b.min_return_pct,
    b.max_return_pct
) x;

select
  latest_bar_time,
  symbol_count,
  up_count,
  breadth_up_pct,
  avg_return_pct,
  tqqq_return_pct,
  sqqq_return_pct,
  regime,
  recommended_allocation_rule
from market_rt.market_regime_current;
