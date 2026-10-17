from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .base import BaseScraper, ScrapeResult


class LocalFileScraper(BaseScraper):
    """Ingest exported CSV/JSON data through the same collector contract as web sources."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def collect(self) -> ScrapeResult:
        if not self.path.exists():
            return ScrapeResult(errors=[f"File does not exist: {self.path}"])
        try:
            if self.path.suffix.casefold() == ".csv":
                rows = pd.read_csv(self.path).to_dict(orient="records")
            elif self.path.suffix.casefold() in {".json", ".jsonl"}:
                text = self.path.read_text(encoding="utf-8")
                data = [json.loads(line) for line in text.splitlines()] if self.path.suffix == ".jsonl" else json.loads(text)
                rows = data if isinstance(data, list) else data["listings"]
            else:
                return ScrapeResult(errors=["Only CSV, JSON, and JSONL are supported"])
            return ScrapeResult(rows=rows)
        except (OSError, ValueError, KeyError) as exc:
            return ScrapeResult(errors=[f"Could not parse {self.path}: {exc}"])

