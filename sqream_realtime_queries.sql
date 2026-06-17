-- 1) Daily feature table에서 실시간 감시 대상만 추출
select
  symbol,
  'precursor_breakout' as watch_type,
  precursor_breakout_score as score
from market_analysis.symbol_features
where precursor_breakout_flag = 1

union all

select
  symbol,
  'bottom_watch' as watch_type,
  bottom_watch_score as score
from market_analysis.symbol_features
where bottom_watch_flag = 1;

-- 2) 장중 1분봉에서 거래량 급증 + 고점 돌파가 같이 나오는지 확인
select
  b.symbol,
  max(b.close_price) as latest_close,
  sum(b.volume_count) as last_window_volume
from market_rt.intraday_bars b
where b.bar_time >= '2026-05-26 09:30:00'
group by b.symbol;

-- 3) 장중 실시간 신호 테이블에서 최근 발생 이벤트 확인
select
  symbol,
  event_time,
  signal_type,
  signal_score,
  price,
  detail
from market_rt.signal_events
order by event_time desc
limit 100;
