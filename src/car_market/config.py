from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    raw_data: Path = ROOT / "data" / "raw" / "demo_listings.csv"
    clean_data: Path = ROOT / "data" / "processed" / "listings.csv"
    database: Path = ROOT / "data" / "market.db"
    artifact: Path = ROOT / "artifacts" / "model.joblib"
    metrics: Path = ROOT / "artifacts" / "metrics.json"
    # Assumption only: completed transactions are unavailable in public listings.
    transaction_to_ask_ratio: float = 0.97
    random_seed: int = 42


settings = Settings()

