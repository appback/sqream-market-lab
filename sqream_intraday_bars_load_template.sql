create or replace foreign table market_rt.delayed_intraday_bars_stage (
  symbol text(32),
  bar_time text(32),
  open_price float,
  high_price float,
  low_price float,
  close_price float,
  volume_count int,
  source text(32),
  collected_at text(32)
)
wrapper parquet_fdw
options (location = '{{INTRADAY_BARS_PARQUET_PATH}}');

insert into market_rt.delayed_intraday_bars_raw
select * from market_rt.delayed_intraday_bars_stage;

create or replace table market_rt.delayed_intraday_bars_latest_{{PARTITION}} as
select * from market_rt.delayed_intraday_bars_stage;

create or replace table market_rt.delayed_intraday_bars_latest as
select * from market_rt.delayed_intraday_bars_latest_a
union all
select * from market_rt.delayed_intraday_bars_latest_b
union all
select * from market_rt.delayed_intraday_bars_latest_c
union all
select * from market_rt.delayed_intraday_bars_latest_d
union all
select * from market_rt.delayed_intraday_bars_latest_e;

select count(*) from market_rt.delayed_intraday_bars_raw;
select count(*) from market_rt.delayed_intraday_bars_latest;
