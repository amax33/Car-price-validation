from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import pandas as pd


@dataclass
class ScrapeResult:
    rows: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows)


class BaseScraper(ABC):
    """Interface for polite, public-only collectors; implementations never bypass controls."""

    @abstractmethod
    def collect(self) -> ScrapeResult:
        raise NotImplementedError

