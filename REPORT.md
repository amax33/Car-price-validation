# Car market valuation — development report

> **Final result:** This document preserves the earlier synthetic/demo analysis for
> auditability. The current release, frozen real dataset, real-data validation,
> five real outputs, and active API model are documented in
> [FINAL_REPORT.md](FINAL_REPORT.md). Do not use the synthetic metrics below as the
> current headline result.

## Method

The pipeline reads public schema.org vehicle listings or exported CSV/JSON,
normalizes Persian/Arabic characters and digits, maps brand/model/body aliases,
converts Solar Hijri model years, rejects impossible values, de-duplicates IDs and
listing fingerprints, and removes only extreme within-model price outliers using a
robust median-absolute-deviation rule. Clean observations are stored in an indexed,
constraint-backed SQLite table.

The estimator predicts log asking price with histogram gradient boosting. Features
are make/model/trim, year, mileage, vehicle age, mileage per year, condition, city,
powertrain, and calendar month. Two quantile models define the initial interval;
a later chronological calibration window expands it with split-conformal residuals.
The final 15% of dates remains untouched for evaluation. A make/model median is the
baseline. Comparable vehicles are ranked by model match, year, mileage, condition,
city, and recency.

Because public ads do not reveal completed deals, `estimated_asking_price` is the
direct model output. `estimated_market_value` applies a transparent, configurable
0.97 transaction-to-ask assumption. It is a scenario, not an observed sale value.

## Offline demo findings

The included 900-row dataset is **synthetic** and exists to make the repository
fully runnable; these numbers are engineering validation, not claims about today's
Iranian car market. On the final chronological 135 rows:

| Metric | Model | Make/model median baseline |
|---|---:|---:|
| MAE (million IRR) | 1,254.1 | 2,150.6 |
| RMSE (million IRR) | 2,023.3 | 3,489.4 |
| MAPE | 8.93% | 16.99% |
| R² | 0.9497 | 0.8505 |

The nominal 90% interval covered 80.74% of the future holdout and averaged 33.48% of
the prediction width. That under-coverage is important: the synthetic market trends
up over time, so exchangeability is violated and older calibration residuals are too
optimistic. Production should monitor rolling coverage and widen/retrain intervals
when drift is detected.

## Real public snapshot

A bounded live run on 2026-10-15 collected 130 unique raw listings: 120 from five
Divar city index snapshots and 10 Bama detail pages discovered from its public car
index. Cleaning retained 121 rows (114 Divar and 7 Bama) and rejected nine with
missing or invalid required values. The retained data covers 29 makes, 79 model/trim
groups, nine cities, model years 1993–2026, and asking prices from 217 to 300,000
million IRR.

This real snapshot is not used for the headline model metrics. Only nine model groups
have at least three listings (35 rows total), making a chronological per-vehicle
valuation model unstable. A credible training set needs repeated daily snapshots and
hundreds of observations per major make/model/trim. The raw snapshot, clean CSV,
SQLite database, metadata, and reproducible collector are provided separately.

## Five reproducible examples

All figures below are million IRR and use `as_of_date=2026-09-30`.

| Vehicle | Listed | Estimated market | Range | Position | Confidence | Comparables |
|---|---:|---:|---:|---|---:|---:|
| 2022 Dena Plus Turbo Auto, 48k km, clean | 12,500 | 12,367.0 | 9,604.2–14,254.0 | Fair | 0.76 | 5 |
| 2019 Peugeot 206 Type 5, 105k km, one panel | 5,500 | 6,476.3 | 5,376.0–7,998.8 | Fair | 0.73 | 5 |
| 2022 Saipa Quick R, 42k km, clean | 4,800 | 6,287.5 | 5,350.6–7,305.5 | Below Market | 0.76 | 5 |
| 2017 Hyundai Santa Fe, 140k km, clean | 42,000 | 31,759.9 | 27,516.4–37,694.7 | Above Market | 0.77 | 5 |
| 2017 Renault L90 E2, 155k km, multiple panels | 7,000 | 8,467.5 | 6,885.8–9,353.4 | Fair | 0.72 | 5 |

## Error analysis and limitations

- Asking prices contain negotiation strategy, stale listings, scams, and selection
  bias. They cannot identify transaction value without dealer/auction/registration
  outcomes or a measured sale-to-ask study.
- The demo generator is intentionally learnable; real missingness, rare trims, regime
  shifts, sanctions, exchange rates, and regional supply will make errors larger.
- A single 3% discount is not credible across all segments. Replace it with a model
  trained on matched ask/sale pairs, or return asking-market value only.
- Unknown categories are accepted but have weak support. Confidence combines interval
  width and comparable support; it is a heuristic score, not a calibrated probability.
- Duplicate sellers can repost the same car with changed IDs. Image hashes, phone
  hashes, and fuzzy text matching would improve entity resolution where lawful.

## Recommended next steps

Collect a rolling, versioned snapshot from permitted public endpoints; add exchange
rate and inflation indices; label removed/sold ads; obtain a transaction benchmark;
backtest monthly; report errors by model, price band, and city; and add drift alarms
for MAPE, interval coverage, unknown-category rate, and data freshness.
