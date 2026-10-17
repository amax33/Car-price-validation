import pandas as pd

from car_market.cleaning import clean_listings


def test_cleaning_removes_duplicate_and_invalid_rows():
    rows = []
    for index in range(10):
        rows.append({
            "source": "demo", "source_listing_id": str(index), "make": "ایران خودرو",
            "model": "دنا پلاس", "year": "۱۴۰۲", "mileage_km": index * 1000,
            "body_condition": "بدون رنگ", "city": "Tehran", "asking_price": 10_000 + index,
            "listing_date": "2026-01-01",
        })
    rows.append(rows[0].copy())
    rows.append({**rows[0], "source_listing_id": "bad", "asking_price": -1})
    clean, report = clean_listings(pd.DataFrame(rows))
    assert len(clean) == 10
    assert report.duplicates_removed == 1
    assert report.invalid_removed == 1
    assert clean.iloc[0]["make"] == "Iran Khodro"

