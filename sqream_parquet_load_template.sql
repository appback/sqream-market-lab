create or replace foreign table market_analysis.symbol_features_stage (
  symbol text(32),
  as_of_date text(10),
  close_price float,
  volume_count int,
  ret_1d float,
  ret_5d float,
  ret_20d float,
  ret_60d float,
  range_pct float,
  volume_ratio_20_50 float,
  price_vs_20dma float,
  price_vs_50dma float,
  price_vs_90d_high float,
  drawdown_from_252d_high float,
  volatility_20d float,
  one_day_100pct_flag int,
  crash_50pct_sub1_flag int,
  rebound_after_crash_flag int,
  surge_setup_flag int,
  breakout_score float,
  distress_rebound_score float,
  precursor_breakout_score float,
  bottom_watch_score float,
  precursor_breakout_flag int,
  bottom_watch_flag int
)
wrapper parquet_fdw
options (location = '{{FEATURES_PARQUET_PATH}}');

create or replace foreign table market_analysis.symbol_events_stage (
  symbol text(32),
  event_date text(10),
  event_type text(32),
  magnitude_pct float,
  close_price float,
  next_day_direction text(16),
  next_day_change_pct float
)
wrapper parquet_fdw
options (location = '{{EVENTS_PARQUET_PATH}}');

insert into market_analysis.symbol_features
select * from market_analysis.symbol_features_stage;

insert into market_analysis.symbol_events
select * from market_analysis.symbol_events_stage;

select count(*) from market_analysis.symbol_features;
select count(*) from market_analysis.symbol_events;
