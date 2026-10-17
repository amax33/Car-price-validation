from .base import BaseScraper, ScrapeResult
from .jsonld import JsonLdVehicleScraper
from .index import PublicIndexScraper
from .local import LocalFileScraper

__all__ = ["BaseScraper", "JsonLdVehicleScraper", "LocalFileScraper", "PublicIndexScraper", "ScrapeResult"]
