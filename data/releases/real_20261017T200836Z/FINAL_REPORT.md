# Final real-data car valuation report

Release: `real_20261017T200836Z`  
Dataset SHA-256: `d8cd53c40e533f6c944f7fa435c2ab07e34dfe1f23c5251265afa839844b66ca`

## Dataset

The frozen dataset contains **1,062 cleaned public listings**: bama 96, divar 966.
It covers 100 makes, 384 make/model groups, and 49 cities. Cleaning removed 1 duplicates, 0 invalid rows, and 21 robust price outliers from the database export.
Training uses **1,013 eligible whole-car ads**. It excludes 49 malformed, partial-price, transfer-right, salvage, temporary-import, or installment-focused ads using a versioned deterministic policy.

## Validation

Only a few listing dates are available, so honest future-market validation is not yet possible. The reported figures use five-fold shuffled out-of-fold predictions and must be interpreted as cross-sectional model checks, not temporal backtesting.

| Metric | Model | Hierarchical median baseline |
|---|---:|---:|
| MAE (million IRR) | 11,002.6 | 11,630.0 |
| RMSE (million IRR) | 45,710.7 | 46,208.3 |
| MAPE | 38.50% | 43.72% |
| Median APE | 13.33% | 19.39% |
| WMAPE | 40.01% | 42.29% |
| R² | 0.1233 | 0.1041 |

For supported segments:

| Segment | Rows | MAPE | Median APE | MAE |
|---|---:|---:|---:|---:|
| support at least 5 | 513 | 17.70% | 9.30% | 1,709.1 |
| support at least 10 | 352 | 18.42% | 9.97% | 1,554.7 |

The out-of-fold interval coverage is 89.93%, with mean width 157.71% of the point estimate. Because the same OOF residuals calibrate and summarize the interval, independent temporal coverage may be worse.

## Five real examples

| Vehicle | Listed | Estimated market | Range | Position | Confidence | Exact support |
|---|---:|---:|---:|---|---:|---:|
| 2011 Peugeot 206 2, 190,000 km | 10,000.0 | 9,646.4 | 4,678.0–19,891.5 | Fair | 0.54 | 44 |
| 2017 Pride 131 Se, 250,000 km | 7,150.0 | 7,451.8 | 3,613.7–15,366.1 | Fair | 0.54 | 34 |
| 2023 Saina Manual S, 70,000 km | 15,000.0 | 13,821.0 | 6,702.5–28,499.8 | Fair | 0.58 | 20 |
| 2013 Samand Lx Basic, 350,000 km | 9,180.0 | 9,006.6 | 4,367.7–18,572.2 | Fair | 0.51 | 18 |
| 2020 Tiba Hatchback Ex, 108,000 km | 11,500.0 | 10,590.2 | 5,135.7–21,837.8 | Fair | 0.55 | 11 |

## Fallback and API behavior

Make/model groups with fewer than five training rows blend the learned estimate with an exact-model, make-level, or global median. Their ranges widen and confidence falls with exact-model support. The API returns five comparable listings and states the number of exact training examples.

## Limitations

- Labels are asking prices, not completed transactions.
- The 0.97 transaction-to-ask ratio remains an explicit scenario assumption.
- Collection spans too few dates to test inflation, drift, seasonality, or future performance.
- Most body-condition values are unavailable in public structured data.
- Rare models depend heavily on hierarchical fallback estimates.
- Bama price magnitudes are interpreted as toman despite its current JSON-LD IRR label.

This is a credible challenge submission and research prototype, not a production appraisal service.
