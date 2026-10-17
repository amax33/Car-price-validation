# Narin car market estimator

A modular reference implementation for collecting car listings, cleaning and
normalizing them, storing them in SQLite, validating a market-price model over time,
and serving estimates through an API.

The repository is runnable offline. The synthetic dataset remains available for
pipeline tests, while the active API model now uses the frozen, versioned real-data
release described in [the final report](FINAL_REPORT.md).

## Included real snapshot

The cumulative SQLite database reached 1,084 unique public listings. Finalization
froze 1,062 clean rows and selected 1,013 eligible whole-car ads for training. Seller
names, phone numbers, descriptions, and images are not retained. Release hashes,
cleaning decisions, metrics, five examples, and the database snapshot live under the
directory referenced by `data/releases/latest.json`.

## What it returns

`POST /v1/estimate` returns:

- predicted asking price and assumption-adjusted market value;
- a conformalized price range;
- `Below Market`, `Fair`, or `Above Market` for a supplied price;
- a 0–1 confidence heuristic and its ingredients;
- five recent, similar listings and a short explanation.

Prices are consistently expressed in **million IRR**. See
[the data dictionary](docs/DATA_DICTIONARY.md) and [the analysis report](REPORT.md).

## Quick start

Python 3.10+ is required.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'

car-market demo-data --rows 900
car-market prepare
car-market train
car-market estimate examples/request.json
```

The commands above exercise the offline demo. To rebuild and activate the final model
from the cumulative real database, run:

```bash
PYTHONPATH=src python3 scripts/finalize_real_project.py
```

Start the API:

```bash
uvicorn car_market.api:app --reload
```

Open `http://127.0.0.1:8000/docs`, or call it directly:

```bash
curl -X POST http://127.0.0.1:8000/v1/estimate \
  -H 'content-type: application/json' \
  --data @examples/request.json
```

The health endpoint reports whether an artifact exists:

```bash
curl http://127.0.0.1:8000/health
```

## Using public data responsibly

The generic collector reads schema.org `Vehicle`, `Car`, or `Product` JSON-LD from
URLs you explicitly provide. It has a delay, does not discover pages, and does not
bypass login, CAPTCHA, robots restrictions, or rate limits.

```bash
car-market scrape --source example --delay 2.0 --price-unit irr \
  'https://example.org/public-listing/123' \
  'https://example.org/public-listing/456'
car-market prepare
car-market train
```

Dynamic sites may not expose useful JSON-LD. In that case, use a permitted export and
map it to the columns in the data dictionary. `LocalFileScraper` accepts CSV, JSON,
and JSONL so a source-specific adapter can remain isolated from the rest of the
pipeline. `--price-unit` converts full IRR or toman values to million IRR; leave it at
`million_irr` only when the page already uses that unit. Confirm the source's terms
and local law before collection.

To reproduce the bounded multi-city snapshot:

```bash
PYTHONPATH=src python3 scripts/collect_public_snapshot.py --delay 2
```

The pages and schemas can change at any time. Review both sites' current rules before
rerunning it; an empty city result is recorded as an error rather than circumvented.

### Long-running collection

For an eight-hour resumable run across the configured public city indexes:

```bash
PYTHONPATH=src python3 scripts/run_long_scraper.py \
  --hours 8 \
  --cycle-minutes 15 \
  --delay 3
```

Use `--hours 0` to continue until `Ctrl+C`. The runner checks robots rules before
starting, prevents two processes from using the same database, checkpoints every
cycle, backs off when many sources fail, imposes a database size limit, and handles
`SIGINT`/`SIGTERM` cleanly. See [the long-running collector guide](docs/LONG_RUNNING_SCRAPER.md).

Unlike the one-shot CSV, the long-running database preserves every observation. The
`listings` table stores the latest state plus `first_seen_at`, `last_seen_at`, and
`seen_count`; `listing_observations` retains price/mileage history; and `crawl_runs`
and `crawl_errors` provide an audit trail.

## Project layout

```text
src/car_market/
  scrapers/          source adapters and public JSON-LD collector
  normalization.py  Persian/Arabic and categorical normalization
  cleaning.py       validation, duplicate and robust outlier handling
  storage.py        SQLite schema and idempotent upsert
  model.py          temporal split, baseline, quantiles, conformal interval
  service.py        comparable search, classification, confidence, explanation
  api.py             FastAPI transport
  pipeline.py        reproducible prepare/train orchestration
data/raw/            immutable input snapshot (demo supplied)
data/processed/      generated clean table
artifacts/           generated model and holdout metrics
notebooks/           reproducible EDA/model inspection
tests/               unit and end-to-end coverage
```

## Modeling and validation contract

The synthetic demonstration uses a chronological 70/15/15 split. The current real
release spans too few distinct dates for honest temporal testing, so its report uses
five-fold out-of-fold validation and explicitly labels that limitation. Its baseline
is a hierarchical exact-model/make/global median. The active estimator uses one-hot
categorical features, Extra Trees, low-support fallback blending, and conformalized
log-residual ranges.

The target is the advertised asking price. The API also returns a market-value
scenario using `transaction_to_ask_ratio=0.97` from `config.py`; this is explicitly
identified as an assumption in every response. Do not relabel it as a verified
transaction price.

## Tests and reproducibility

```bash
pytest -q
```

Training uses fixed seeds. `artifacts/metrics.json` and
`artifacts/real_metrics.json` record the active real-data result. Generated model
binaries and SQLite files are ignored by git; rebuild them with the commands above.

## Production checklist

- Pin and version raw snapshots, mappings, model artifacts, and training metadata.
- Add source-specific contract tests and observability for schema changes.
- Schedule collection only at an allowed rate; retain provenance and deletion rules.
- Monitor freshness, unknown categories, segment errors, temporal MAPE, and interval
  coverage; retrain or abstain when thresholds fail.
- Authenticate/rate-limit the API and avoid returning seller personal information.
- Replace the 0.97 assumption with matched transaction outcomes when available.
