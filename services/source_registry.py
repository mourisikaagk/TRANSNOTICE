from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime

from config import Settings
from scraper import demo_source
from timeutil import to_iso

log = logging.getLogger(__name__)
DEMO_AGENCY_FALLBACK = {"code": "DEMO-DCT", "name": "Demo City Transit (sample data)"}


def _upsert_agency(conn, code: str, name: str, is_demo: bool) -> int:
    conn.execute(
        "INSERT INTO agencies (code, name, is_demo) VALUES (?, ?, ?) "
        "ON CONFLICT(code) DO UPDATE SET name = excluded.name, is_demo = excluded.is_demo",
        (code, name, int(is_demo)))
    return conn.execute("SELECT id FROM agencies WHERE code = ?", (code,)).fetchone()["id"]


def _upsert_source(conn, agency_id: int, entry: dict) -> None:
    conn.execute(
        """INSERT INTO sources (agency_id, code, name, source_type, url, enabled, complete_listing, timezone,
                                permission_status, refresh_minutes)
           VALUES (:agency_id, :code, :name, :source_type, :url, :enabled, :complete_listing, :timezone,
                   :permission_status, :refresh_minutes)
           ON CONFLICT(code) DO UPDATE SET agency_id = excluded.agency_id, name = excluded.name,
               source_type = excluded.source_type, url = excluded.url, enabled = excluded.enabled,
               complete_listing = excluded.complete_listing, timezone = excluded.timezone,
               permission_status = excluded.permission_status, refresh_minutes = excluded.refresh_minutes""",
        dict(entry, agency_id=agency_id))


def sync_sources(conn: sqlite3.Connection, settings: Settings, now: datetime) -> list[str]:
    """Create or update source rows. Live sources are enabled only when the config file marks
    them approved and names an approval document; otherwise they are stored disabled."""
    notes: list[str] = []
    agency_id = _upsert_agency(conn, DEMO_AGENCY_FALLBACK["code"], DEMO_AGENCY_FALLBACK["name"], True)
    _upsert_source(conn, agency_id, {
        "code": "DEMO-FEED", "name": "Demo advisory feed (sample data)", "source_type": "demo",
        "url": demo_source.DEMO_SOURCE_URL, "enabled": int(settings.enable_demo_source), "complete_listing": 1,
        "timezone": settings.display_timezone, "permission_status": "not_applicable_demo",
        "refresh_minutes": settings.refresh_interval_minutes})

    if settings.live_sources_file:
        try:
            entries = json.loads(settings.live_sources_file.read_text(encoding="utf-8"))["sources"]
        except (OSError, ValueError, KeyError) as exc:
            notes.append(f"Live source file could not be read: {type(exc).__name__}")
            entries = []
        for entry in entries:
            approved = entry.get("permission_status") == "approved" and bool(entry.get("approval_document"))
            wants_enabled = bool(entry.get("enabled"))
            if wants_enabled and not approved:
                notes.append(f"{entry.get('code')}: not enabled because permission is not approved/documented.")
            try:
                agency = _upsert_agency(conn, entry["agency_code"], entry["agency_name"], False)
                _upsert_source(conn, agency, {
                    "code": entry["code"], "name": entry["name"], "source_type": entry["type"], "url": entry["url"],
                    "enabled": int(wants_enabled and approved), "complete_listing": int(entry.get("complete_listing", False)),
                    "timezone": entry.get("timezone", settings.display_timezone),
                    "permission_status": entry.get("permission_status", "not_reviewed"),
                    "refresh_minutes": int(entry.get("refresh_minutes", 30))})
            except (KeyError, sqlite3.Error) as exc:
                notes.append(f"{entry.get('code', '?')}: invalid entry ({type(exc).__name__}).")
    for note in notes:
        log.warning(note)
    return notes


def seed_demo_subscription(conn: sqlite3.Connection, settings: Settings, now: datetime) -> None:
    if not settings.enable_demo_source:
        return
    if conn.execute("SELECT 1 FROM subscriptions LIMIT 1").fetchone() is None:
        conn.execute("INSERT INTO subscriptions (label, route_filter, channel, created_at) VALUES (?, ?, 'demo', ?)",
                     ("Demo subscriber: route 12A", "12A", to_iso(now)))
