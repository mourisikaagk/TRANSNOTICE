"""Demo source: a local JSON 'feed' rendered to HTML and parsed by the same parser
used for real pages. All data here is fictional and clearly labelled."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

from config import Settings
from timeutil import from_iso, to_iso

DEMO_SOURCE_URL = "https://demo.invalid/advisories"
FEED_VERSION = 2


def _offset(now: datetime, hours: float | None) -> str | None:
    return None if hours is None else to_iso(now + timedelta(hours=hours))


def build_feed(settings: Settings, now: datetime) -> dict:
    template = json.loads(Path(settings.sample_data_path).read_text(encoding="utf-8"))
    center = template.get("map_center", [0.0, 0.0])
    notices = []
    for item in template["notices"]:
        notices.append({
            "id": item["id"], "type": item["type"], "routes": item["routes"],
            "title": item["title"], "area": item["area"], "summary": item["summary"],
            "status": item.get("status", "Active"),
            "lat": round(center[0] + item["dlat"], 5) if "dlat" in item else None,
            "lon": round(center[1] + item["dlon"], 5) if "dlon" in item else None,
            "published_at": _offset(now, -item["published_hours_ago"]),
            "valid_from": _offset(now, item["starts_in_hours"]),
            "valid_to": _offset(now, item["ends_in_hours"]),
        })
    return {"version": FEED_VERSION, "agency": template["agency"], "simulate_failure": False, "generated_at": to_iso(now), "notices": notices}


def save_feed(settings: Settings, feed: dict) -> None:
    path = Path(settings.demo_feed_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(feed, indent=2), encoding="utf-8")


def load_feed(settings: Settings, now: datetime) -> dict:
    path = Path(settings.demo_feed_path)
    feed = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    if feed is None or not isinstance(feed.get("notices"), list):
        feed = build_feed(settings, now)
        save_feed(settings, feed)
    elif feed.get("version") != FEED_VERSION:
        feed = _upgrade_feed(settings, feed, now)
        save_feed(settings, feed)
    return feed


def _upgrade_feed(settings: Settings, feed: dict, now: datetime) -> dict:
    """Add the fields introduced by a newer feed version without touching times or scenario edits,
    so an upgrade never looks like a change to the notices themselves."""
    positions = {n["id"]: (n["lat"], n["lon"]) for n in build_feed(settings, now)["notices"]}
    for notice in feed["notices"]:
        lat, lon = positions.get(notice["id"], (None, None))
        notice.setdefault("lat", lat)
        notice.setdefault("lon", lon)
    feed["version"] = FEED_VERSION
    return feed


def render_html(feed: dict, tz_name: str) -> str:
    tz = ZoneInfo(tz_name)

    def time_tag(css: str, value: str | None) -> str:
        if not value:
            return ""
        local = from_iso(value).astimezone(tz).isoformat(timespec="minutes")
        return f'<time class="{css}" datetime="{local}">{escape(local)}</time>'

    parts = ["<!doctype html><html><body><main>"]
    for n in feed["notices"]:
        routes = "".join(f"<li>{escape(r)}</li>" for r in n["routes"])
        parts.append(
            f'<article class="advisory" data-notice-id="{escape(n["id"])}"{_geo_attrs(n)}>'
            f'<h2 class="advisory-title">{escape(n["title"])}</h2>'
            f'<span class="advisory-type">{escape(n["type"])}</span>'
            f'<ul class="advisory-routes">{routes}</ul>'
            f'<p class="advisory-area">{escape(n["area"])}</p>'
            f'<p class="advisory-summary">{escape(n["summary"])}</p>'
            f'{time_tag("advisory-published", n.get("published_at"))}'
            f'{time_tag("advisory-valid-from", n.get("valid_from"))}'
            f'{time_tag("advisory-valid-to", n.get("valid_to"))}'
            f'<span class="advisory-status">{escape(n.get("status", "Active"))}</span>'
            f'<a class="advisory-link" href="{DEMO_SOURCE_URL}#{escape(n["id"])}">Demo notice page</a>'
            "</article>"
        )
    parts.append("</main></body></html>")
    return "".join(parts)


def _geo_attrs(n: dict) -> str:
    if n.get("lat") is None or n.get("lon") is None:
        return ""
    return f' data-lat="{n["lat"]}" data-lon="{n["lon"]}"'


def _find(feed: dict, notice_id: str) -> dict | None:
    return next((n for n in feed["notices"] if n["id"] == notice_id), None)


def apply_scenario(settings: Settings, name: str, now: datetime) -> str:
    feed = load_feed(settings, now)
    message = ""
    if name == "reset":
        feed = build_feed(settings, now)
        message = "Demo feed reset to the original sample notices."
    elif name == "extend_outage":
        n = _find(feed, "DEMO-001")
        base = from_iso(n["valid_to"]) if n and n.get("valid_to") else None
        if base is None:
            return "DEMO-001 has no end time to extend."
        n["valid_to"] = to_iso(base + timedelta(hours=24))
        message = "Extended the Riverside Bridge outage (DEMO-001) by 24 hours."
    elif name == "shorten_notice":
        n = _find(feed, "DEMO-002")
        base = from_iso(n["valid_to"]) if n and n.get("valid_to") else None
        if base is None:
            return "DEMO-002 has no end time to shorten."
        n["valid_to"] = to_iso(base - timedelta(hours=12))
        message = "Shortened the Market Road diversion (DEMO-002) by 12 hours."
    elif name == "revise_summary":
        n = _find(feed, "DEMO-003")
        n["summary"] = "UPDATE: Repair crews are on site. Expect delays of up to 25 minutes."
        message = "Revised the summary of DEMO-003."
    elif name == "add_route":
        n = _find(feed, "DEMO-002")
        if "45Y" not in n["routes"]:
            n["routes"].append("45Y")
        message = "Added route 45Y to DEMO-002."
    elif name == "add_no_end_date":
        if not _find(feed, "DEMO-099"):
            anchor = _find(feed, "DEMO-001") or {}
            has_geo = anchor.get("lat") is not None
            feed["notices"].append({
                "id": "DEMO-099", "type": "Diversion", "routes": ["31"],
                "title": "Route 31 temporary diversion, no end date", "area": "East Station Approach",
                "summary": "Route 31 is diverted via Mill Lane. No end date has been announced.",
                "status": "Active", "published_at": to_iso(now),
                "lat": round(anchor["lat"] + 0.015, 5) if has_geo else None,
                "lon": round(anchor["lon"] + 0.02, 5) if has_geo else None,
                "valid_from": to_iso(now), "valid_to": None,
            })
        message = "Added advisory DEMO-099 without an end date."
    elif name == "withdraw_notice":
        n = _find(feed, "DEMO-005")
        n["status"] = "Withdrawn"
        message = "Marked DEMO-005 as withdrawn by the source."
    elif name == "fail_on":
        feed["simulate_failure"] = True
        message = "Source failure simulation is ON. Refreshes will fail."
    elif name == "fail_off":
        feed["simulate_failure"] = False
        message = "Source failure simulation is OFF."
    else:
        raise ValueError(f"Unknown scenario: {name}")
    save_feed(settings, feed)
    return message


SCENARIOS = (
    ("extend_outage", "Extend outage by 24 h"),
    ("shorten_notice", "Shorten diversion by 12 h"),
    ("revise_summary", "Revise a summary"),
    ("add_route", "Add a route to a notice"),
    ("add_no_end_date", "Add advisory with no end date"),
    ("withdraw_notice", "Withdraw a notice"),
    ("fail_on", "Simulate source failure"),
    ("fail_off", "Restore source"),
    ("reset", "Reset demo data"),
)
