# Data dictionary

All prices use **million Iranian rial (IRR)**. Dates use ISO-8601.

| Field | Type | Meaning |
|---|---:|---|
| `source` | string | Origin platform or `demo_synthetic` |
| `source_listing_id` | string | Stable ID within the source |
| `make`, `model`, `trim` | string | Canonical vehicle identity |
| `year` | integer | Gregorian model year; Solar Hijri inputs are converted |
| `mileage_km` | integer | Odometer reading in kilometres |
| `body_condition` | category | `clean`, `one_panel`, `multiple_panels`, `replaced_panel`, or `damaged` when recognized |
| `city` | string | Listing market |
| `transmission`, `fuel_type` | category | Powertrain attributes |
| `asking_price` | float | Advertised price, not a completed-sale price |
| `listing_date` | date | Date used for temporal validation and market trend |
| `url` | string | Public source page, when retained |

The compound key `(source, source_listing_id)` is unique in SQLite. A second
fingerprint catches cross-ID duplicates during cleaning.

## Historical collection tables

- `listings`: latest normalized listing state, first/last seen timestamps, and count.
- `listing_observations`: immutable asking-price and mileage observation per crawl run.
- `crawl_runs`: start/end status and new/changed/error counts for every cycle.
- `crawl_errors`: source scope and error text retained for diagnosis.

Absence from a single index snapshot does not prove that an advertisement was sold
or removed, so the collector does not claim an `is_active` value.

