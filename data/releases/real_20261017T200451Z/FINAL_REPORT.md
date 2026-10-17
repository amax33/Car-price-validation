# Final real-data car valuation report

Release: `real_20261017T200451Z`  
Dataset SHA-256: `d8cd53c40e533f6c944f7fa435c2ab07e34dfe1f23c5251265afa839844b66ca`

## Dataset

The frozen dataset contains **1,062 cleaned public listings**: bama 96, divar 966.
It covers 100 makes, 384 make/model groups, and 49 cities. Cleaning removed 1 duplicates, 0 invalid rows, and 21 robust price outliers from the database export.

## Validation

Only a few listing dates are available, so honest future-market validation is not yet possible. The reported figures use five-fold shuffled out-of-fold predictions and must be interpreted as cross-sectional model checks, not temporal backtesting.

| Metric | Model | Hierarchical median baseline |
|---|---:|---:|
| MAE (million IRR) | 11,648.1 | 12,266.4 |
| RMSE (million IRR) | 46,556.4 | 47,159.6 |
| MAPE | 1998.34% | 2053.37% |
| R² | 0.0836 | 0.0597 |

The out-of-fold interval coverage is 90.02%, with mean width 178.11% of the point estimate. Because the same OOF residuals calibrate and summarize the interval, independent temporal coverage may be worse.

## Five real examples

| Vehicle | Listed | Estimated market | Range | Position | Confidence | Exact support |
|---|---:|---:|---:|---|---:|---:|
| 2011 Peugeot 206 2, 190,000 km | 10,000.0 | 9,624.2 | 6,003.9–17,025.2 | Fair | 0.59 | 44 |
| 2017 Pride 131 Se, 250,000 km | 7,150.0 | 7,472.3 | 4,999.9–11,497.2 | Fair | 0.63 | 34 |
| 2023 Saina Manual S, 70,000 km | 15,000.0 | 14,391.1 | 2,138.1–22,594.4 | Fair | 0.60 | 20 |
| 2013 Samand Lx Basic, 350,000 km | 9,180.0 | 8,890.6 | 6,410.8–14,486.1 | Fair | 0.60 | 18 |
| 2018 Tiba Hatchback Ex, 175,000 km | 10,800.0 | 10,490.4 | 7,516.6–20,098.0 | Fair | 0.57 | 12 |

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
