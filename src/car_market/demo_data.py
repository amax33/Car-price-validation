from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


PROFILES = [
    ("Iran Khodro", "Dena Plus", "Turbo Automatic", 2022, 10_200),
    ("Iran Khodro", "Dena Plus", "base", 2020, 8_100),
    ("Peugeot", "206", "Type 5", 2019, 6_200),
    ("Peugeot", "Pars", "LX", 2018, 6_700),
    ("Saipa", "Pride 131", "SE", 2017, 3_300),
    ("Saipa", "Quick", "R", 2021, 4_900),
    ("Renault", "L90", "E2", 2017, 8_500),
    ("Hyundai", "Santa Fe", "Limited", 2017, 31_000),
    ("Kia", "Cerato", "2.0", 2018, 22_500),
]


def generate_demo_data(path: str | Path, rows: int = 900, seed: int = 42) -> pd.DataFrame:
    """Create reproducible, realistic-shaped data for running the project offline.

    These rows are synthetic and are intentionally marked as source=demo_synthetic.
    They validate the full pipeline but must not be presented as current market evidence.
    """
    rng = np.random.default_rng(seed)
    cities = np.array(["Tehran", "Karaj", "Isfahan", "Shiraz", "Mashhad"])
    city_factor = {"Tehran": 1.03, "Karaj": 1.01, "Isfahan": 0.99, "Shiraz": 0.98, "Mashhad": 0.985}
    conditions = np.array(["clean", "one_panel", "multiple_panels", "replaced_panel", "damaged"])
    condition_factor = {"clean": 1.0, "one_panel": 0.96, "multiple_panels": 0.90, "replaced_panel": 0.86, "damaged": 0.76}
    start = pd.Timestamp("2025-01-01")
    end = pd.Timestamp("2026-09-30")
    records: list[dict] = []
    for index in range(rows):
        make, model, trim, profile_year, base_price = PROFILES[index % len(PROFILES)]
        listing_date = start + pd.Timedelta(days=int(rng.integers(0, (end - start).days + 1)))
        year = int(np.clip(profile_year + rng.integers(-3, 3), 2012, 2026))
        age = max(listing_date.year - year, 0)
        mileage = max(0, int(age * rng.normal(17_000, 5_000) + rng.normal(8_000, 12_000)))
        city = str(rng.choice(cities, p=[0.50, 0.13, 0.13, 0.11, 0.13]))
        condition = str(rng.choice(conditions, p=[0.67, 0.16, 0.09, 0.05, 0.03]))
        model_year_factor = 1 + 0.055 * (year - profile_year)
        mileage_factor = max(0.68, 1 - mileage * 0.00000125)
        market_factor = 1 + ((listing_date - start).days / 365) * 0.18
        noise = rng.lognormal(mean=0, sigma=0.055)
        price = base_price * model_year_factor * mileage_factor * market_factor * city_factor[city] * condition_factor[condition] * noise
        records.append({
            "source": "demo_synthetic",
            "source_listing_id": f"demo-{index:05d}",
            "make": make,
            "model": model,
            "trim": trim,
            "year": year,
            "mileage_km": mileage,
            "body_condition": condition,
            "city": city,
            "transmission": "automatic" if any(x in trim.casefold() for x in ("automatic", "limited", "2.0")) else "manual",
            "fuel_type": "gasoline",
            "asking_price": round(price, 1),
            "listing_date": listing_date.date().isoformat(),
            "url": "",
        })
    frame = pd.DataFrame(records).sort_values("listing_date")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return frame

