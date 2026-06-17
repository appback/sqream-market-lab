create schema market_rt;

create or replace table market_rt.watchlist (
  symbol text(32),
  watch_type text(32),         -- precursor_breakout / bottom_watch / event_followup
  score float,
  inserted_at text(19)
);

create or replace table market_rt.intraday_bars (
  symbol text(32),
  bar_time text(19),           -- UTC or ET timestamp string
  open_price float,
  high_price float,
  low_price float,
  close_price float,
  volume_count int,
  vwap_price float,
  source text(32)
);

create or replace table market_rt.signal_events (
  symbol text(32),
  event_time text(19),
  signal_type text(32),        -- precursor_trigger / bottom_trigger / halt_risk / breakout_confirmed
  signal_score float,
  price float,
  volume_count int,
  detail text(256)
);
