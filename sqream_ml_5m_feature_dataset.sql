create or replace table market_rt.ml_5m_feature_dataset as
select
  f.trade_date,
  f.symbol,
  f.bar_time,
  substring(f.bar_time, 12, 5) as hhmm,
  f.close_price,
  f.run_return_pct,
  ((f.run_high / f.run_low) - 1) * 100 as run_range_pct,
  ((f.close_price / f.run_vwap) - 1) * 100 as vwap_gap_pct,
  f.run_volume,
  r.breadth_up_pct,
  r.avg_return_pct as market_avg_return_pct,
  f.run_return_pct - r.avg_return_pct as rel_strength_pct,
  r.tqqq_return_pct,
  r.sqqq_return_pct,
  r.regime,
  lead(f.close_price, 5) over (
    partition by f.trade_date, f.symbol
    order by f.bar_time
  ) as future_close_5m,
  lead(f.bar_time, 5) over (
    partition by f.trade_date, f.symbol
    order by f.bar_time
  ) as future_time_5m
from market_rt.backtest_live_safe_features f
join market_rt.backtest_live_safe_regime r
  on r.trade_date = f.trade_date
 and r.bar_time = f.bar_time
where substring(f.bar_time, 12, 5) >= '10:00'
  and substring(f.bar_time, 12, 5) < '15:30'
  and substring(f.bar_time, 15, 2) in ('00','05','10','15','20','25','30','35','40','45','50','55')
  and f.close_price between 0.2 and 50
  and f.run_low > 0
  and f.run_volume > 0;

create or replace table market_rt.ml_5m_feature_labels as
select
  trade_date,
  symbol,
  bar_time,
  hhmm,
  close_price,
  run_return_pct,
  run_range_pct,
  vwap_gap_pct,
  run_volume,
  breadth_up_pct,
  market_avg_return_pct,
  rel_strength_pct,
  tqqq_return_pct,
  sqqq_return_pct,
  regime,
  future_time_5m,
  future_close_5m,
  ((future_close_5m / close_price) - 1) * 100 as future_return_5m_pct,
  case when ((future_close_5m / close_price) - 1) * 100 >= 0.3 then 1 else 0 end as label_up_30bp,
  case when ((future_close_5m / close_price) - 1) * 100 <= -0.3 then 1 else 0 end as label_down_30bp
from market_rt.ml_5m_feature_dataset
where future_close_5m is not null
  and future_time_5m is not null;

create or replace table market_rt.ml_5m_feature_summary as
select
  regime,
  count(*) as samples,
  sum(label_up_30bp) as up_30bp_count,
  sum(label_down_30bp) as down_30bp_count,
  avg(future_return_5m_pct) as avg_future_return_5m_pct,
  min(future_return_5m_pct) as min_future_return_5m_pct,
  max(future_return_5m_pct) as max_future_return_5m_pct
from market_rt.ml_5m_feature_labels
group by regime;

select
  count(*) as samples,
  avg(future_return_5m_pct) as avg_future_return_5m_pct,
  sum(label_up_30bp) as up_30bp_count,
  sum(label_down_30bp) as down_30bp_count
from market_rt.ml_5m_feature_labels;

select
  regime,
  samples,
  up_30bp_count,
  down_30bp_count,
  avg_future_return_5m_pct,
  min_future_return_5m_pct,
  max_future_return_5m_pct
from market_rt.ml_5m_feature_summary
order by regime;
