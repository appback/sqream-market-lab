create or replace table market_analysis.event_paths (
  symbol text(32),
  event_type text(32),
  event_date text(10),
  prev_close float,
  event_open float,
  event_high float,
  event_low float,
  event_close float,
  event_volume int,
  event_return_pct float,
  intraday_range_pct float,
  close_from_high_pct float,
  close_from_low_pct float,
  next_1d_high_return_pct float,
  next_3d_high_return_pct float,
  next_5d_high_return_pct float,
  next_10d_high_return_pct float,
  next_3d_low_return_pct float,
  next_5d_low_return_pct float,
  next_10d_low_return_pct float
);

create or replace table market_analysis.paper_trades (
  symbol text(32),
  source_event_type text(32),
  strategy text(48),
  signal_date text(10),
  entry_date text(10),
  exit_date text(10),
  entry_price float,
  exit_price float,
  target_price float,
  stop_price float,
  max_hold_days int,
  return_pct float,
  exit_reason text(32),
  entry_delay_days float,
  hold_days float,
  event_return_pct float,
  event_close_from_high_pct float
);

create or replace foreign table market_analysis.event_paths_stage (
  symbol text(32),
  event_type text(32),
  event_date text(10),
  prev_close float,
  event_open float,
  event_high float,
  event_low float,
  event_close float,
  event_volume int,
  event_return_pct float,
  intraday_range_pct float,
  close_from_high_pct float,
  close_from_low_pct float,
  next_1d_high_return_pct float,
  next_3d_high_return_pct float,
  next_5d_high_return_pct float,
  next_10d_high_return_pct float,
  next_3d_low_return_pct float,
  next_5d_low_return_pct float,
  next_10d_low_return_pct float
)
wrapper parquet_fdw
options (location = '{{EVENT_PATHS_PARQUET_PATH}}');

create or replace foreign table market_analysis.paper_trades_stage (
  symbol text(32),
  source_event_type text(32),
  strategy text(48),
  signal_date text(10),
  entry_date text(10),
  exit_date text(10),
  entry_price float,
  exit_price float,
  target_price float,
  stop_price float,
  max_hold_days int,
  return_pct float,
  exit_reason text(32),
  entry_delay_days float,
  hold_days float,
  event_return_pct float,
  event_close_from_high_pct float
)
wrapper parquet_fdw
options (location = '{{PAPER_TRADES_PARQUET_PATH}}');

insert into market_analysis.event_paths
select * from market_analysis.event_paths_stage;

insert into market_analysis.paper_trades
select * from market_analysis.paper_trades_stage;

select count(*) from market_analysis.event_paths;
select count(*) from market_analysis.paper_trades;
