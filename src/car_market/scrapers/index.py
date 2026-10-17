from __future__ import annotations

from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from .base import BaseScraper, ScrapeResult
from .jsonld import JsonLdVehicleScraper


class PublicIndexScraper(BaseScraper):
    """Read one public index and, only if needed, a bounded set of detail pages."""

    def __init__(
        self,
        index_url: str,
        source: str,
        detail_path_prefix: str,
        max_details: int = 24,
        delay_seconds: float = 1.5,
        price_unit: str = "million_irr",
    ):
        self.index_url = index_url
        self.source = source
        self.detail_path_prefix = detail_path_prefix
        self.max_details = max(0, min(max_details, 100))
        self.delay_seconds = delay_seconds
        self.price_unit = price_unit

    def collect(self) -> ScrapeResult:
        try:
            request = Request(
                self.index_url,
                headers={"User-Agent": "NarinResearchBot/0.1 (public pages only)"},
            )
            with urlopen(request, timeout=20) as response:  # noqa: S310 - explicit configured URL
                html = response.read()
        except (HTTPError, URLError, TimeoutError) as exc:
            return ScrapeResult(errors=[f"{self.index_url}: {exc}"])

        parser = JsonLdVehicleScraper([], self.source, self.delay_seconds, self.price_unit)
        rows = parser._parse_all(html, self.index_url)
        if rows:
            return ScrapeResult(rows=rows)

        origin = urlparse(self.index_url)
        soup = BeautifulSoup(html, "html.parser")
        links: list[str] = []
        for tag in soup.select("a[href]"):
            url = urljoin(self.index_url, tag.get("href", ""))
            parsed = urlparse(url)
            if parsed.netloc == origin.netloc and parsed.path.startswith(self.detail_path_prefix) and url not in links:
                links.append(url)
            if len(links) >= self.max_details:
                break
        if not links:
            return ScrapeResult(errors=[f"No structured listings or matching detail links at {self.index_url}"])
        return JsonLdVehicleScraper(links, self.source, self.delay_seconds, self.price_unit).collect()
