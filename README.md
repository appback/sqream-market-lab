# US Stock Event Screener

브로커 API 없이 해외주식, 정확히는 미국 상장주를 대상으로 아래 이벤트를 스캔합니다.

- 최근 1년 내 `하루 상승률 100% 이상` 발생 종목
- 최근 가격/거래량 패턴상 `급등 조짐` 후보
- 최근 1년 내 `전일 종가 대비 50% 이상 급락`하며 `종가가 1달러 미만`으로 붕괴한 뒤 다시 반등한 종목

## 데이터 소스

- 종목 유니버스: Nasdaq Trader 심볼 디렉터리
- 일봉 가격: Stooq 공개 CSV 엔드포인트

이 스크립트는 `브로커 API` 없이 동작하며, 조회/알림만 수행합니다.

## 파일

- `stock_screener.py`: 본체
- `.env.example`: 텔레그램 환경변수 예제
- `output/`: 실행 시 JSON/CSV 리포트 생성
- `state/alert_state.json`: 중복 알림 방지 상태 저장

## 실행

네트워크가 열려 있어야 `nasdaqtrader.com`, `stooq.com`, `api.telegram.org`에 접근할 수 있습니다.

테스트:

```bash
python3 stock_screener.py --limit 50 --pause-seconds 0
```

전체 스캔:

```bash
python3 stock_screener.py
```

로컬 CSV로 오프라인 테스트:

```bash
python3 stock_screener.py --symbols-file sample_symbols.txt --price-dir sample_prices --pause-seconds 0
```

새 신호만 텔레그램 전송:

```bash
export TELEGRAM_BOT_TOKEN=...
export TELEGRAM_CHAT_ID=...
python3 stock_screener.py --telegram-only-new
```

## 스케줄링 예시

크론에서 매일 장 종료 후 1회 실행:

```cron
30 7 * * 2-6 cd /home/ospadmin/workspaces/remoteagent/cc6mog23 && /usr/bin/python3 stock_screener.py --telegram-only-new >> screener.log 2>&1
```

위 예시는 한국시간 오전 7시 30분 기준입니다. 미국장 종료 시각에 맞춰 조정하면 됩니다.

## 해석 주의

- `하루 100% 급등`은 일봉 종가 기준입니다. 장중 고점이 아니라 `전일 종가 대비 당일 종가` 기준입니다.
- `급등 조짐`은 예측 모델이 아니라 단순 휴리스틱입니다.
- `1달러 미만 후 반등`은 단순히 `1.01 -> 0.99` 같은 약한 이탈이 아니라, `전일 종가 대비 50% 이상 급락 + 종가 1달러 미만` 이벤트 뒤 반등을 찾습니다.
- 소형주, 저유동성주, 스플릿 이슈 때문에 오탐이 나올 수 있습니다.
- 로컬 CSV 테스트 형식은 `Date,Open,High,Low,Close,Volume` 헤더를 가진 `SYMBOL.csv` 입니다.
