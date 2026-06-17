# Realtime Strategy

## 목표

이미 급등한 종목을 뒤늦게 잡는 것이 아니라:

- `급등 직전` 후보를 빠르게 감지
- `급락 후 아직 본격 반등 전` 후보를 감시
- 신호가 바뀌는 순간 텔레그램으로 알림

## 수집 방식

### 1. 장 시작 전

- `market_analysis.symbol_features`에서 감시 대상 추출
- `precursor_breakout_flag = 1`
- `bottom_watch_flag = 1`
- 결과를 `market_rt.watchlist`에 적재

### 2. 장중

- 실시간 데이터 공급원에서 `1분봉 또는 trade/quote stream` 수집
- 각 심볼의 최신 데이터를 `market_rt.intraday_bars`에 적재

실시간 공급원은 `REST polling`보다 `WebSocket`이 맞습니다.

- Polygon stocks websocket: https://polygon.io/docs/websocket/stocks/overview
- Polygon trades stream: https://polygon.io/docs/websocket/stocks/trades
- Finnhub rate limit 문서도 실시간은 websocket 사용을 권장: https://api.finnhub.io/docs/api/rate-limit

## 즉각 반응 규칙

### A. Precursor Breakout Trigger

조건 예시:

- 최근 5분 누적 거래량이 평소 같은 시간대 대비 `3배 이상`
- 현재가가 `전일 고가` 또는 `90일 고점 근처` 돌파
- 장중 수익률은 아직 `+25% 미만`

의미:

- 이미 폭발한 뒤가 아니라 `막 수급이 붙는 초입`을 잡는 조건

### B. Bottom Watch Trigger

조건 예시:

- 과거 큰 급락 이력 있음
- 아직 `1달러 회복` 또는 `2배 반등`은 안 나옴
- 장중 저점 이탈 멈춤
- 거래량 증가 + 5분/15분 고점 갱신 시작

의미:

- 이미 반등한 종목이 아니라 `바닥 형성 시작`을 보는 조건

### C. Reject / Skip

아래는 알림 제외:

- 이미 당일 `+100%` 급등한 종목
- 이미 5일간 과도하게 반등한 종목
- 거래량 없이 단순 갭만 뜬 종목

## 알림 시점

텔레그램은 아래 순간에만 보냅니다.

1. `flag 0 -> 1`로 바뀌는 순간
2. 가격 돌파 + 거래량 조건이 동시에 처음 충족된 순간
3. 같은 종목은 일정 시간 재알림 금지

## 운영 방식

- 장 시작 전 1회: 후보군 선별
- 장중 1분 단위 또는 websocket tick 단위: 상태 갱신
- 종가 후 1회: 일봉 피처 재계산, 다음 날 watchlist 재생성

## 핵심

즉각 반응은 `실시간 수집`과 `상태 변화 감지`가 핵심입니다.

- `일봉 분석 DB`는 누구를 감시할지 결정
- `장중 스트림`은 언제 신호가 켜졌는지 결정
- `텔레그램`은 신호가 켜지는 순간만 발송
