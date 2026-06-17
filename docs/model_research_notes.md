# Model Research Notes

Updated: 2026-06-16 08:50 KST

## Practical Conclusion

There are pretrained time-series foundation models, but there is no reliable plug-in model that can take our stock/order-flow variables and safely predict a tradable 5-minute price move without local validation.

For this project, the practical path is:

1. Use SQream to generate clean point-in-time features and labels.
2. Train/test lightweight models on our own collected universe.
3. Treat model output as one filter among strategy rules, not as an autonomous buy/sell oracle.
4. Add Toss real-time order-book and execution-strength fields later.

## Candidate Model Families

- `TimeGPT`: hosted time-series foundation model. Useful for quick zero-shot forecasting and anomaly tests, but API/service dependency and not trained specifically on our execution features.
- `Chronos / Chronos-2`: open pretrained time-series forecasting family from Amazon. Useful for local or SageMaker tests; better fit for sequence forecasting than LLM-style finance text models.
- `TimesFM`: Google Research time-series foundation model, available as open source and in BigQuery. Useful baseline for generic time-series forecasting.
- `FinGPT`: financial LLM project. Useful for news/text/sentiment or financial language tasks, not primarily a 5-minute tick-price forecaster.

## Local Data Prepared

SQream feature dataset:

- `market_rt.ml_5m_feature_dataset`
- `market_rt.ml_5m_feature_labels`
- `market_rt.ml_5m_feature_summary`

Label:

- `future_return_5m_pct`
- `label_up_30bp`: future 5-minute return >= +0.3%
- `label_down_30bp`: future 5-minute return <= -0.3%

Current features:

- symbol/date/time
- current close
- running return
- running intraday range
- VWAP gap
- running volume
- market breadth
- market average return
- relative strength
- TQQQ/SQQQ proxy return
- regime

## Important Limitation

The feature table is point-in-time, but it still lacks:

- order-book depth
- bid/ask spread
- queue size by price
- execution strength
- trade aggressor side
- venue and liquidity fragmentation

So model predictions must be paper-tested with execution penalties before any real trading use.
