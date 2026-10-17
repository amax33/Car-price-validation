from __future__ import annotations

import json
import time
from datetime import date
from hashlib import sha256
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from .base import BaseScraper, ScrapeResult


class JsonLdVehicleScraper(BaseScraper):
    """Conservative collector for explicitly supplied public listing URLs.

    It reads schema.org Product/Vehicle JSON-LD only. It does not discover pages,
    authenticate, solve CAPTCHAs, or retry rate limits.
    """

    def __init__(
        self,
        urls: list[str],
        source: str,
        delay_seconds: float = 1.0,
        price_unit: str = "million_irr",
    ):
        self.urls = urls
        self.source = source
        self.delay_seconds = max(delay_seconds, 0.5)
        if price_unit not in {"million_irr", "irr", "toman"}:
            raise ValueError("price_unit must be million_irr, irr, or toman")
        self.price_unit = price_unit

    def collect(self) -> ScrapeResult:
        result = ScrapeResult()
        for index, url in enumerate(self.urls):
            if index:
                time.sleep(self.delay_seconds)
            try:
                request = Request(url, headers={"User-Agent": "NarinResearchBot/0.1 (public pages only)"})
                with urlopen(request, timeout=15) as response:  # noqa: S310 - explicit user URLs
                    html = response.read()
                rows = self._parse_all(html, url)
                if rows:
                    result.rows.extend(rows)
                else:
                    result.errors.append(f"No supported vehicle JSON-LD at {url}")
            except (HTTPError, URLError, TimeoutError, ValueError) as exc:
                result.errors.append(f"{url}: {exc}")
        return result

    def _parse(self, html: bytes, url: str) -> dict | None:
        rows = self._parse_all(html, url)
        return rows[0] if rows else None

    def _parse_all(self, html: bytes, url: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        objects: list[dict] = []
        for tag in soup.select('script[type="application/ld+json"]'):
            try:
                value = json.loads(tag.string or "")
            except json.JSONDecodeError:
                continue
            objects.extend(value if isinstance(value, list) else [value])
        rows: list[dict] = []
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            if "@graph" in obj:
                objects.extend(x for x in obj["@graph"] if isinstance(x, dict))
            kind = obj.get("@type", "")
            kinds = {kind} if isinstance(kind, str) else set(kind)
            if not kinds.intersection({"Vehicle", "Car", "Product"}):
                continue
            offer = obj.get("offers", {})
            brand = obj.get("brand", {})
            brand = brand.get("name", "") if isinstance(brand, dict) else brand
            item_url = obj.get("url", url)
            name = str(obj.get("model") or obj.get("name", ""))
            model = self._model_name(name, str(brand or ""))
            rows.append({
                "source": self.source,
                "source_listing_id": obj.get("sku") or obj.get("identifier") or sha256(item_url.encode()).hexdigest()[:16],
                "make": brand,
                "model": model,
                "trim": obj.get("vehicleConfiguration", "base"),
                "year": obj.get("vehicleModelDate") or obj.get("productionDate"),
                "mileage_km": self._mileage(obj.get("mileageFromOdometer")),
                "body_condition": self._condition(obj.get("itemCondition")),
                "city": self._city(offer, obj.get("description", "")),
                "transmission": obj.get("vehicleTransmission", "unknown"),
                "fuel_type": obj.get("fuelType", "unknown"),
                "asking_price": self._price(offer),
                "listing_date": obj.get("datePosted", date.today().isoformat()),
                "url": item_url,
            })
        return rows

    @staticmethod
    def _mileage(value: object) -> object:
        return value.get("value") if isinstance(value, dict) else value

    @staticmethod
    def _city(offer: object, description: object = "") -> str:
        if not isinstance(offer, dict):
            area_name = ""
        else:
            area = offer.get("areaServed", {})
            area_name = area.get("name", "") if isinstance(area, dict) else str(area or "")
        if area_name:
            return area_name
        import re

        match = re.search(r"در شهر\s+([^،,.]+)", str(description))
        return match.group(1).strip() if match else "unknown"

    @staticmethod
    def _condition(value: object) -> str:
        text = str(value or "").casefold()
        # Schema.org UsedCondition means only "not new", not whether panels were painted.
        return "new" if "newcondition" in text and "usedcondition" not in text else "unknown"

    @staticmethod
    def _model_name(name: str, brand: str) -> str:
        model = name.replace(brand, "").strip(" ،,-") if brand else name
        return model or name

    def _price(self, offer: object) -> object:
        if not isinstance(offer, dict):
            return None
        price = offer.get("price")
        try:
            numeric = float(str(price).replace(",", ""))
        except (TypeError, ValueError):
            return price
        divisor = {"million_irr": 1.0, "irr": 1_000_000.0, "toman": 100_000.0}[self.price_unit]
        return numeric / divisor
