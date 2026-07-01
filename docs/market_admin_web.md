# Market Admin Web

Small dependency-free admin web for SQream Market Lab paper trading statistics.

## Run

```bash
./run_market_admin_web.sh
```

Defaults:

- Host: `127.0.0.1`
- Port: `18085`

Override:

```bash
MARKET_ADMIN_HOST=0.0.0.0 MARKET_ADMIN_PORT=18085 ./run_market_admin_web.sh
```

## Pages

- `/`: recent dashboard
  - summary cards for active/candidate and all strategies
  - performance charts for strategy PnL, strategy win rate, and recent daily PnL
- `/api/summary?days=10`: JSON summary
- `/admin/strategies`: strategy status and decision memo editor

## Data Sources

- Paper trade ledger: `state/paper_trade_ledger.jsonl`
- Strategy registry: `docs/strategy_versions.json`

The dashboard separates active/candidate strategy aggregation from all-strategy aggregation so disabled historical experiments do not distort the current operating view.

## Chart Scope

The admin dashboard intentionally shows performance charts only.
It does not show stock price, candle, or intraday quote charts.

Current charts:

- strategy total PnL,
- strategy win rate,
- recent daily PnL and running PnL.

Chart rendering uses Chart.js through a browser-side script include.
If the dashboard must run without internet access, replace this with a vendored Chart.js asset or simple inline SVG rendering.
