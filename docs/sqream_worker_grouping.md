# SQream Worker Grouping

Current operating layout:

| Worker | Service | Purpose |
| --- | --- | --- |
| sqream1 | ingest | Parquet staging load |
| sqream2 | ingest | Parquet staging load |
| sqream3 | analysis | latest rebuild, market regime, strategy SQL |
| sqream4 | analysis | latest rebuild, market regime, strategy SQL |
| sqream5 | sqream | runtime detection and paper-trading state SQL |

## Rationale

The current bottleneck is not raw collection or file upload.
The measured 2026-06-17 load-only cycle showed:

- collect avg: 63.764s
- parquet write avg: 1.371s
- upload avg: 0.218s
- SQream load avg: 11.078s
- SQream lock wait avg: 21.143s
- SQream lock wait p95: 42.078s
- total avg: 97.575s

Because SQream load itself is around 11s, adding more ingest workers is not the first fix.
The higher-impact fix is to reduce write-side conflicts by making ingest append-only and moving `latest` rebuilds to the analysis cycle.

## Policy

- Keep `2 ingest / 2 analysis / 1 sqream` until the ingest SQL is changed to append-only.
- Do not route runtime detection through `analysis`; keep it on `sqream` so analysis backtests do not delay alerts.
- If `sqream_lock_wait` remains above 30s p95 after append-only ingest, test `3 ingest / 2 analysis` next.
- If analysis exceeds 60s per cycle, keep `2 analysis` and reduce strategy SQL frequency before adding ingest workers.

## Script Mapping

- `run_delayed_intraday_cycle_a.sh` through `run_delayed_intraday_cycle_e.sh`: `SQREAM_SERVICE=ingest`
- `run_sqream_analysis_cycle.sh`: `SQREAM_SERVICE=analysis`
- `run_detection_cycle.sh`: `SQREAM_SERVICE=sqream`

## Next Structural Improvement

Change intraday loading from:

1. insert raw rows
2. rebuild partition latest table
3. rebuild global latest table

to:

1. insert raw rows only in ingest workers
2. rebuild latest tables once in analysis worker after all partitions load

