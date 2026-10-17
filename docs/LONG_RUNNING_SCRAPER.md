# Long-running public collector

## Start it

From the repository root:

```bash
PYTHONPATH=src python3 scripts/run_long_scraper.py \
  --hours 8 \
  --cycle-minutes 15 \
  --delay 3
```

For a terminal-independent process:

```bash
nohup env PYTHONPATH=src python3 scripts/run_long_scraper.py \
  --hours 8 --cycle-minutes 15 --delay 3 \
  > data/raw/long_scraper.console.log 2>&1 &
echo $!
```

Watch progress with:

```bash
tail -f data/raw/long_scraper.log
cat data/raw/long_scraper_state.json
```

Stop it gracefully with `Ctrl+C`, or `kill <PID>` when started through `nohup`. A
database lock prevents accidental concurrent collectors. A later invocation resumes
from the existing SQLite data; no special resume flag is needed.

## Collection behavior

Each cycle visits the configured Divar city index pages sequentially, then discovers
a bounded number of public Bama detail links from its car index. The default delay is
three seconds per request and the default cycle interval is 15 minutes. When at least
half the attempted scopes fail, the next interval doubles, up to four times the base.

The collector stops when its duration, optional `--max-cycles`, or `--max-db-mb`
limit is reached. `--hours 0` means run until interrupted. It never authenticates,
solves CAPTCHAs, rotates IP addresses or identities, uses proxies, or retries around
access controls. It fails closed when robots rules disallow a configured index.

Useful options:

```bash
# Four hours, selected cities, at most 10 Bama details per cycle
PYTHONPATH=src python3 scripts/run_long_scraper.py \
  --hours 4 --cities tehran,karaj,mashhad,shiraz --bama-details 10

# Continuous collection with a 512 MB database cap
PYTHONPATH=src python3 scripts/run_long_scraper.py \
  --hours 0 --max-db-mb 512

# One-cycle operational check
PYTHONPATH=src python3 scripts/run_long_scraper.py \
  --hours 1 --max-cycles 1 --cities tehran --bama-details 2
```

## Outputs

| Path | Purpose |
|---|---|
| `data/real_market.db` | Canonical cumulative listings, observations, runs, and errors |
| `data/raw/latest_real_snapshot.csv` | Most recent successful cycle |
| `data/raw/real_listings.csv` | Cumulative raw listing IDs seen by this collector |
| `data/raw/snapshots/` | Immutable per-cycle CSV snapshots |
| `data/processed/real_listings.csv` | Latest normalized state exported from SQLite |
| `data/raw/long_scraper_state.json` | Machine-readable checkpoint and totals |
| `data/raw/long_scraper.log` | Human-readable operational log |

## Inspect history

```sql
-- Run health
SELECT id, started_at, status, raw_count, clean_count,
       new_count, changed_count, error_count
FROM crawl_runs
ORDER BY id DESC
LIMIT 20;

-- Listings with observed price changes
SELECT l.source, l.source_listing_id, l.make, l.model,
       COUNT(DISTINCT o.asking_price) AS price_versions,
       MIN(o.asking_price) AS lowest_price,
       MAX(o.asking_price) AS highest_price
FROM listings l
JOIN listing_observations o ON o.listing_id = l.id
GROUP BY l.id
HAVING COUNT(DISTINCT o.asking_price) > 1
ORDER BY price_versions DESC;

-- Data freshness
SELECT source, COUNT(*) AS listings, MIN(last_seen_at), MAX(last_seen_at)
FROM listings
GROUP BY source;
```

## Interpretation limits

Index membership changes as listings are ranked and rotated. A listing not observed
in one cycle is not necessarily removed or sold, so the collector records staleness
but does not invent an active/sold label. Similarly, observed price changes are asking
price changes—not transactions. Review source terms and robots rules before every
extended collection campaign because they can change independently of this code.
