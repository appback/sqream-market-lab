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
  - D1 current-policy summary card
  - performance charts for strategy PnL, strategy win rate, and recent daily PnL
  - D1 current-policy trade detail and excluded trade detail
- `/api/summary?days=10`: JSON summary
- `/admin/strategies`: strategy status and decision memo editor
- `/admin/condition-sets`: integrated condition-set manager

## Data Sources

- Paper trade ledger: `state/paper_trade_ledger.jsonl`
- Strategy registry: `docs/strategy_versions.json`
- Strategy condition sets: `docs/strategy_condition_sets.json`

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

## D1 Current Policy View

The dashboard separates D1 current-policy performance from raw all-time performance.

Current D1 policy:

- strategy: `d1_vol5_absret10_breakout_2_target10_stop5_eod`
- include only entries where `09:30 <= opened_at < 10:15` ET
- show excluded historical D1 trades separately

This avoids mixing early non-policy paper trades with the currently intended opening-only D1 operation.

## Condition Set Admin

`/admin/condition-sets` manages reusable condition combinations separately from the raw strategy version registry.

Condition categories:

- `time_window`
- `market_regime`
- `pattern`
- `volume`
- `risk`
- `allocation`

This is currently an admin/config layer only. Runtime code still uses the existing strategy-specific logic.
Before wiring condition sets into runtime execution, add validation and a dry-run comparison against current behavior.

Runtime policy:

- `runtime_mode`: `config_only`
- condition-set changes do not affect live runtime detection,
- condition-set changes do not affect paper-trading decisions,
- promotion to runtime requires manual approval, dry-run validation, and explicit code change.
