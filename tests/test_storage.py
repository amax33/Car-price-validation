import pandas as pd

from car_market.storage import (
    finish_crawl_run,
    load_listings,
    save_listings,
    save_observations,
    start_crawl_run,
)


def test_storage_upserts_by_source_id(tmp_path):
    row = {
        "source": "test", "source_listing_id": "1", "make": "Saipa", "model": "Quick",
        "trim": "R", "year": 2022, "mileage_km": 10_000, "body_condition": "clean",
        "city": "Tehran", "transmission": "manual", "fuel_type": "gasoline",
        "asking_price": 5000.0, "listing_date": "2026-01-01", "url": "",
    }
    path = tmp_path / "test.db"
    save_listings(pd.DataFrame([row]), path)
    row["asking_price"] = 5100.0
    save_listings(pd.DataFrame([row]), path)
    stored = load_listings(path)
    assert len(stored) == 1
    assert stored.iloc[0]["asking_price"] == 5100.0


def test_observations_preserve_price_history(tmp_path):
    row = {
        "source": "test", "source_listing_id": "history-1", "make": "Saipa", "model": "Quick",
        "trim": "R", "year": 2022, "mileage_km": 10_000, "body_condition": "clean",
        "city": "Tehran", "transmission": "manual", "fuel_type": "gasoline",
        "asking_price": 5000.0, "listing_date": "2026-01-01", "url": "https://example.test/1",
        "crawl_scope": "test_scope",
    }
    path = tmp_path / "history.db"
    run1 = start_crawl_run(path, {"test": True})
    first = save_observations(pd.DataFrame([row]), path, run1, "2026-01-01T00:00:00+00:00")
    finish_crawl_run(path, run1, "complete", 1, 1, first, [])
    row["asking_price"] = 4800.0
    run2 = start_crawl_run(path, {"test": True})
    second = save_observations(pd.DataFrame([row]), path, run2, "2026-01-02T00:00:00+00:00")
    finish_crawl_run(path, run2, "complete", 1, 1, second, [])

    import sqlite3
    with sqlite3.connect(path) as connection:
        prices = [item[0] for item in connection.execute(
            "SELECT asking_price FROM listing_observations ORDER BY observed_at"
        )]
        listing = connection.execute(
            "SELECT asking_price,seen_count,first_seen_at,last_seen_at FROM listings"
        ).fetchone()
    assert prices == [5000.0, 4800.0]
    assert listing == (4800.0, 2, "2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00")
    assert second.changed == 1
