from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .cleaning import clean_listings
from .config import Settings, settings
from .demo_data import generate_demo_data
from .model import ModelBundle, train_model
from .storage import save_listings


def prepare_data(config: Settings = settings, create_demo_if_missing: bool = False) -> tuple[pd.DataFrame, dict]:
    if not config.raw_data.exists():
        if not create_demo_if_missing:
            raise FileNotFoundError(f"Raw data not found: {config.raw_data}. Run `car-market demo-data` first.")
        generate_demo_data(config.raw_data, seed=config.random_seed)
    raw = pd.read_csv(config.raw_data)
    clean, report = clean_listings(raw)
    config.clean_data.parent.mkdir(parents=True, exist_ok=True)
    clean.to_csv(config.clean_data, index=False)
    save_listings(clean, config.database)
    return clean, report.as_dict()


def train(config: Settings = settings) -> ModelBundle:
    if config.clean_data.exists():
        listings = pd.read_csv(config.clean_data, parse_dates=["listing_date"])
    else:
        listings, _ = prepare_data(config)
    bundle = train_model(listings, config.transaction_to_ask_ratio, config.random_seed)
    bundle.save(config.artifact)
    config.metrics.parent.mkdir(parents=True, exist_ok=True)
    config.metrics.write_text(json.dumps(bundle.metrics, indent=2), encoding="utf-8")
    return bundle

