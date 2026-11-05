from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, time
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

from timeutil import UTC, to_iso

ROUTE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,11}$")
WITHDRAWN_WORDS = ("withdrawn", "rescinded", "retracted", "superseded")

NOTICE_TYPES = (
    ("Cancellation", ("cancel", "suspend", "no service")),
    ("Diversion", ("divert", "diversion", "reroute", "re-route")),
    ("Stop Closure", ("stop clos", "stop relocat", "stop moved", "stop shift")),
    ("Planned Maintenance", ("maintenance", "repair", "works", "closure", "closed")),
    ("Delay", ("delay", "late running", "disruption")),
    ("Route Change", ("route change", "timetable", "schedule change", "new route")),
)

DATE_FORMATS = (
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%d %b %Y %H:%M",
    "%d %B %Y %H:%M",
    "%d/%m/%Y %H:%M",
    "%d-%m-%Y %H:%M",
)
DATE_ONLY_FORMATS = ("%Y-%m-%d", "%d %b %Y", "%d %B %Y", "%d/%m/%Y", "%d-%m-%Y")


@dataclass
class ParsedNotice:
    external_id: str
    title: str
    notice_type: str = "Other"
    summary: str | None = None
    area: str | None = None
    routes: list[str] = field(default_factory=list)
    source_url: str | None = None
    published_at: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    withdrawn: bool = False
    latitude: float | None = None
    longitude: float | None = None

    def content(self) -> dict:
        return {
            "title": self.title,
            "notice_type": self.notice_type,
            "summary": self.summary,
            "area": self.area,
            "routes": sorted(set(self.routes)),
            "source_url": self.source_url,
            "published_at": self.published_at,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "withdrawn": bool(self.withdrawn),
        }


@dataclass
class ParseResult:
    notices: list[ParsedNotice] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skipped_items: int = 0


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", value).strip()
    return text or None


def normalize_route_ids(values) -> list[str]:
    routes: set[str] = set()
    for value in values or []:
        for token in re.split(r"[,;/\s]+", str(value).upper()):
            token = token.strip()
            if token and ROUTE_PATTERN.match(token):
                routes.add(token)
    return sorted(routes)


def classify_notice_type(text: str | None) -> str:
    lowered = (text or "").lower()
    for label, keywords in NOTICE_TYPES:
        if any(word in lowered for word in keywords):
            return label
    return "Other"


def parse_datetime(text: str | None, tz_name: str, end_of_day: bool = False) -> str | None:
    """Return a UTC ISO string, or None when the text is empty or not understood.
    Values without an offset are read in tz_name. Date-only values mean the
    start of that day, or the end of that day when end_of_day is True."""
    text = clean_text(text)
    if not text:
        return None
    tz = ZoneInfo(tz_name)
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if len(text) <= 10 and dt.time() == time.min:
            return _date_only(dt.date(), tz, end_of_day)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        return to_iso(dt)
    except ValueError:
        pass
    for fmt in DATE_FORMATS:
        try:
            return to_iso(datetime.strptime(text, fmt).replace(tzinfo=tz))
        except ValueError:
            continue
    for fmt in DATE_ONLY_FORMATS:
        try:
            return _date_only(datetime.strptime(text, fmt).date(), tz, end_of_day)
        except ValueError:
            continue
    return None


def _date_only(day, tz, end_of_day: bool) -> str:
    clock = time(23, 59, 59) if end_of_day else time.min
    return to_iso(datetime.combine(day, clock, tzinfo=tz))


def _coordinate(raw, low: float, high: float) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if low <= value <= high else None


def _safe_url(href: str | None, base_url: str | None) -> str | None:
    if not href:
        return None
    url = urljoin(base_url or "", href.strip())
    return url if urlparse(url).scheme in {"http", "https"} else None


def _time_value(element) -> str | None:
    if element is None:
        return None
    return clean_text(element.get("datetime") or element.get_text())


def parse_notices_html(html: str, tz_name: str, base_url: str | None = None) -> ParseResult:
    result = ParseResult()
    soup = BeautifulSoup(html or "", "html.parser")
    items = soup.select("article.advisory")
    if not items:
        result.warnings.append("No advisory elements found; the page layout may have changed.")
        return result

    for position, item in enumerate(items, start=1):
        external_id = clean_text(item.get("data-notice-id"))
        if not external_id:
            result.warnings.append(f"Item {position}: missing notice id; skipped.")
            result.skipped_items += 1
            continue

        title = clean_text(_text(item, ".advisory-title"))
        if not title:
            title = f"Untitled notice {external_id}"
            result.warnings.append(f"{external_id}: missing title.")

        route_values = [li.get_text() for li in item.select(".advisory-routes li")]
        routes = normalize_route_ids(route_values)
        if not routes:
            result.warnings.append(f"{external_id}: no valid route ids found.")

        summary = clean_text(_text(item, ".advisory-summary"))
        area = clean_text(_text(item, ".advisory-area"))
        type_text = clean_text(_text(item, ".advisory-type"))
        notice_type = type_text.title() if type_text else classify_notice_type(f"{title} {summary}")

        dates: dict[str, str | None] = {}
        for key, selector, eod in (
            ("published_at", ".advisory-published", False),
            ("valid_from", ".advisory-valid-from", False),
            ("valid_to", ".advisory-valid-to", True),
        ):
            raw = _time_value(item.select_one(selector))
            dates[key] = parse_datetime(raw, tz_name, end_of_day=eod)
            if raw and dates[key] is None:
                result.warnings.append(f"{external_id}: could not read {key} value '{raw}'.")

        if dates["valid_from"] and dates["valid_to"] and dates["valid_to"] < dates["valid_from"]:
            result.warnings.append(f"{external_id}: end time is before start time; end time ignored.")
            dates["valid_to"] = None

        latitude = _coordinate(item.get("data-lat"), -90, 90)
        longitude = _coordinate(item.get("data-lon"), -180, 180)
        if (item.get("data-lat") or item.get("data-lon")) and (latitude is None or longitude is None):
            result.warnings.append(f"{external_id}: invalid coordinates ignored.")
            latitude = longitude = None

        status_text = (clean_text(_text(item, ".advisory-status")) or "").lower()
        link = item.select_one("a.advisory-link")
        result.notices.append(
            ParsedNotice(
                external_id=external_id,
                title=title,
                notice_type=notice_type,
                summary=summary,
                area=area,
                routes=routes,
                source_url=_safe_url(link.get("href") if link else None, base_url),
                withdrawn=any(word in status_text for word in WITHDRAWN_WORDS),
                latitude=latitude,
                longitude=longitude,
                **dates,
            )
        )
    return result


def _text(item, selector: str) -> str | None:
    element = item.select_one(selector)
    return element.get_text(" ") if element else None


def parse_rss(xml_text: str, tz_name: str, base_url: str | None = None) -> ParseResult:
    result = ParseResult()
    try:
        root = SafeET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    except (SafeET.ParseError, DefusedXmlException) as exc:
        result.warnings.append(f"RSS feed could not be parsed: {exc}")
        return result

    for position, item in enumerate(root.iter("item"), start=1):
        guid = clean_text(item.findtext("guid")) or clean_text(item.findtext("link"))
        if not guid:
            result.warnings.append(f"Item {position}: missing guid/link; skipped.")
            result.skipped_items += 1
            continue
        title = clean_text(item.findtext("title")) or f"Untitled notice {guid}"
        description = clean_text(BeautifulSoup(item.findtext("description") or "", "html.parser").get_text(" "))
        published = None
        pub_raw = clean_text(item.findtext("pubDate"))
        if pub_raw:
            try:
                parsed = parsedate_to_datetime(pub_raw)
                published = to_iso(parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC))
            except (TypeError, ValueError):
                result.warnings.append(f"{guid}: could not read pubDate '{pub_raw}'.")
        categories = [c.text or "" for c in item.findall("category")]
        route_values = [c.split(":", 1)[1] for c in categories if c.lower().startswith("route:")]
        routes = normalize_route_ids(route_values)
        if not routes:
            result.warnings.append(f"{guid}: no route categories found.")
        result.notices.append(
            ParsedNotice(
                external_id=guid,
                title=title,
                notice_type=classify_notice_type(f"{title} {description}"),
                summary=description,
                routes=routes,
                source_url=_safe_url(item.findtext("link"), base_url),
                published_at=published,
            )
        )
    return result
