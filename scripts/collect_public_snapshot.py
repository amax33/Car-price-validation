"""Collect a small, public-only Divar/Bama snapshot without bypassing controls."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from car_market.cleaning import clean_listings
from car_market.scrapers import JsonLdVehicleScraper, PublicIndexScraper
from car_market.storage import save_listings


DIVAR_CITIES = {
    "tehran": "Tehran",
    "karaj": "Karaj",
    "shiraz": "Shiraz",
    "mashhad": "Mashhad",
    "tabriz": "Tabriz",
}


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-output", type=Path, default=Path("data/raw/real_listings.csv"))
    parser.add_argument("--clean-output", type=Path, default=Path("data/processed/real_listings.csv"))
    parser.add_argument("--database", type=Path, default=Path("data/real_market.db"))
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--bama-details", type=int, default=24)
    return parser.parse_args()


def main() -> None:
    args = arguments()
    rows: list[dict] = []
    errors: list[str] = []
    counts: dict[str, int] = {}

    for slug, city in DIVAR_CITIES.items():
        result = JsonLdVehicleScraper(
            [f"https://divar.ir/s/{slug}/car"], "divar", args.delay, "irr"
        ).collect()
        for row in result.rows:
            if row.get("city") == "unknown":
                row["city"] = city
        rows.extend(result.rows)
        errors.extend(result.errors)
        counts[f"divar_{slug}"] = len(result.rows)
        time.sleep(max(args.delay, 1.0))

    bama = PublicIndexScraper(
        "https://bama.ir/car",
        "bama",
        "/car/detail-",
        max_details=args.bama_details,
        delay_seconds=args.delay,
        # Bama currently labels this IRR, but observed magnitudes are toman.
        price_unit="toman",
    ).collect()
    rows.extend(bama.rows)
    errors.extend(bama.errors)
    counts["bama"] = len(bama.rows)

    raw = pd.DataFrame(rows).drop_duplicates(["source", "source_listing_id"], keep="last")
    clean, report = clean_listings(raw)
    args.raw_output.parent.mkdir(parents=True, exist_ok=True)
    args.clean_output.parent.mkdir(parents=True, exist_ok=True)
    raw.to_csv(args.raw_output, index=False)
    clean.to_csv(args.clean_output, index=False)
    save_listings(clean, args.database)

    metadata = {
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "public_only": True,
        "counts": counts,
        "raw_rows": len(raw),
        "clean_rows": len(clean),
        "cleaning": report.as_dict(),
        "errors": errors,
        "notes": [
            "No login, CAPTCHA, or rate-limit bypass is attempted.",
            "Divar structured prices are converted from IRR.",
            "Bama price magnitudes are treated as toman despite current JSON-LD priceCurrency=IRR.",
        ],
    }
    metadata_path = args.raw_output.with_name("real_collection_metadata.json")
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
