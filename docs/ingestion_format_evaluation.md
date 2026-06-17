# Ingestion Format Evaluation

Updated: 2026-06-16

## Decision

Keep the current Parquet staging path for the live collector.

ORC remains a candidate for later retesting, but the first benchmark did not show enough load-time improvement to justify replacing Parquet in the production path.

## Current Live Path

1. Collector writes staged intraday bars as Parquet.
2. File is uploaded to `/data/cluster/sqream_stage`.
3. SQream creates a `parquet_fdw` foreign table.
4. SQream inserts from the foreign table into `market_rt.delayed_intraday_bars_raw`.

CSV is not allowed in the ingestion staging path. It may only be used as a one-off human-readable export outside the SQream load path.

## Benchmark

Sample file:

- Source: `staging/delayed_intraday_bars_a_20260615_165503.parquet`
- Rows: `175,361`

Local file-size/write comparison:

| Format | Compression | Size | Ratio vs Parquet | Local Write Time |
| --- | --- | ---: | ---: | ---: |
| Parquet | existing | `2,922,069` bytes | `1.000x` | existing |
| ORC | uncompressed | `18,493,189` bytes | `6.329x` | `0.049s` |
| ORC | snappy | `3,551,529` bytes | `1.215x` | `0.052s` |
| ORC | zlib | `2,607,711` bytes | `0.892x` | `0.123s` |
| ORC | zstd | `2,349,539` bytes | `0.804x` | `0.062s` |

SQream foreign-table count benchmark:

| Format | Size | Elapsed |
| --- | ---: | ---: |
| Parquet | `2,922,069` bytes | `0.887s` |
| ORC zstd | `2,349,539` bytes | `0.888s` |
| ORC zlib | `2,607,711` bytes | `0.870s` |

SQream materialize benchmark (`create table as select * from external`):

| Format | Size | Elapsed |
| --- | ---: | ---: |
| Parquet | `2,922,069` bytes | `1.012s` |
| ORC zstd | `2,349,539` bytes | `1.072s` |
| ORC zlib | `2,607,711` bytes | `1.125s` |

## Interpretation

ORC with zstd compressed about `19.6%` smaller than the current Parquet file, but actual SQream materialization was slightly slower on this sample. The read/count path was effectively tied.

For the current intraday bars schema and batch size, Parquet is still the safer default because:

- It is already implemented and stable.
- SQream supports it directly through `parquet_fdw`.
- Materialization was fastest in the sample test.
- ORC would require changing writer settings and operational validation without a demonstrated load-time benefit.

## Retest Conditions

Reconsider ORC if one of these becomes true:

- Stage file transfer becomes the primary bottleneck instead of SQream lock/load time.
- Batch size increases enough that ORC compression materially reduces network or disk time.
- A larger multi-partition benchmark shows ORC zstd consistently faster end-to-end.
- SQream worker service separation removes lock contention and exposes file scan speed as the main bottleneck.

## Next Improvements Before Format Replacement

1. Split SQream services into `ingest` and `analysis`.
2. Keep Parquet staging, but tune row group/compression settings.
3. Remove stale CSV staging files from the live path.
4. Retest Parquet vs ORC after service-pool separation.
