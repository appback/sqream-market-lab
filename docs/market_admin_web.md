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
- `/api/summary?days=10`: JSON summary
- `/admin/strategies`: strategy status and decision memo editor

## Data Sources

- Paper trade ledger: `state/paper_trade_ledger.jsonl`
- Strategy registry: `docs/strategy_versions.json`

The dashboard separates active/candidate strategy aggregation from all-strategy aggregation so disabled historical experiments do not distort the current operating view.
