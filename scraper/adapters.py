from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping

from config import Settings
from scraper import demo_source
from scraper.fetcher import FetchError, Fetcher
from scraper.parser import ParsedNotice, parse_notices_html, parse_rss


@dataclass
class CollectResult:
    notices: list[ParsedNotice] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skipped_items: int = 0
    http_status: int | None = None
    attempts: int = 1


class SourceAdapter(ABC):
    def __init__(self, source: Mapping, settings: Settings, fetcher: Fetcher | None = None):
        self.source = source
        self.settings = settings
        self.fetcher = fetcher

    @abstractmethod
    def collect(self, now: datetime) -> CollectResult: ...

    def _finish(self, parsed, response=None) -> CollectResult:
        for notice in parsed.notices:
            if not notice.source_url:
                notice.source_url = self.source["url"]
        return CollectResult(
            notices=parsed.notices, warnings=parsed.warnings, skipped_items=parsed.skipped_items,
            http_status=response.status_code if response else None,
            attempts=response.attempts if response else 1,
        )


class DemoAdapter(SourceAdapter):
    def collect(self, now: datetime) -> CollectResult:
        feed = demo_source.load_feed(self.settings, now)
        if feed.get("simulate_failure"):
            raise FetchError("Simulated source outage (demo scenario).", 503, 1)
        html = demo_source.render_html(feed, self.source["timezone"])
        parsed = parse_notices_html(html, self.source["timezone"], base_url=demo_source.DEMO_SOURCE_URL)
        return self._finish(parsed)


class HtmlAdapter(SourceAdapter):
    def collect(self, now: datetime) -> CollectResult:
        response = self.fetcher.get(self.source["url"])
        parsed = parse_notices_html(response.text, self.source["timezone"], base_url=self.source["url"])
        return self._finish(parsed, response)


class RssAdapter(SourceAdapter):
    def collect(self, now: datetime) -> CollectResult:
        response = self.fetcher.get(self.source["url"])
        parsed = parse_rss(response.text, self.source["timezone"], base_url=self.source["url"])
        return self._finish(parsed, response)


ADAPTERS = {"demo": DemoAdapter, "html": HtmlAdapter, "rss": RssAdapter}


def build_adapter(source: Mapping, settings: Settings, fetcher: Fetcher | None = None) -> SourceAdapter:
    try:
        adapter_class = ADAPTERS[source["source_type"]]
    except KeyError as exc:
        raise ValueError(f"Unknown source type: {source['source_type']}") from exc
    return adapter_class(source, settings, fetcher)
