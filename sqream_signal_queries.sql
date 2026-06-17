select
  symbol,
  as_of_date,
  close_price,
  ret_5d,
  ret_20d,
  volume_ratio_20_50,
  price_vs_90d_high,
  precursor_breakout_score
from market_analysis.symbol_features
where precursor_breakout_flag = 1
order by precursor_breakout_score desc
limit 20;

select
  symbol,
  as_of_date,
  close_price,
  ret_5d,
  ret_20d,
  drawdown_from_252d_high,
  crash_50pct_sub1_flag,
  bottom_watch_score
from market_analysis.symbol_features
where bottom_watch_flag = 1
order by bottom_watch_score desc
limit 20;

select
  symbol,
  event_date,
  event_type,
  magnitude_pct,
  next_day_direction,
  next_day_change_pct
from market_analysis.symbol_events
order by event_date desc
limit 50;
