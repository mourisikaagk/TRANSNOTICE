from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping, Sequence

from database.db import savepoint
from scraper.change_detector import (FieldChange, canonical_content, classify_changes, content_hash,
                                     diff_content, summarize_changes)
from scraper.parser import ParsedNotice
from timeutil import to_iso


@dataclass
class IngestResult:
    new: int = 0
    revised: int = 0
    withdrawn: int = 0
    unchanged: int = 0
    errors: list[str] = field(default_factory=list)
    revision_ids: list[int] = field(default_factory=list)


def load_content(conn: sqlite3.Connection, row: Mapping) -> dict:
    routes = [r["route_id"] for r in conn.execute(
        "SELECT route_id FROM notice_routes WHERE notice_id = ? ORDER BY route_id", (row["id"],))]
    content = {k: row[k] for k in ("title", "notice_type", "summary", "area", "source_url",
                                   "published_at", "valid_from", "valid_to")}
    content.update(routes=routes, withdrawn=row["withdrawn_at"] is not None)
    return canonical_content(content)


def _add_revision(conn, notice_id: int, digest: str, change_type: str, summary: str,
                  changes: Sequence[FieldChange], snapshot: Mapping, now_iso: str) -> int:
    next_no = conn.execute("SELECT COALESCE(MAX(revision_no), 0) + 1 FROM notice_revisions WHERE notice_id = ?",
                           (notice_id,)).fetchone()[0]
    cur = conn.execute(
        """INSERT INTO notice_revisions (notice_id, revision_no, content_hash, change_type, change_summary,
                                         changes_json, snapshot_json, observed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (notice_id, next_no, digest, change_type, summary,
         json.dumps([c.as_dict() for c in changes]), json.dumps(snapshot, sort_keys=True), now_iso),
    )
    return cur.lastrowid


def _audit(conn, notice_id: int, source_id: int, event: str, detail: str, now_iso: str) -> None:
    conn.execute("INSERT INTO audit_events (notice_id, source_id, event_type, detail, created_at) VALUES (?, ?, ?, ?, ?)",
                 (notice_id, source_id, event, detail, now_iso))


def _replace_routes(conn, notice_id: int, routes: Sequence[str]) -> None:
    conn.execute("DELETE FROM notice_routes WHERE notice_id = ?", (notice_id,))
    conn.executemany("INSERT INTO notice_routes (notice_id, route_id) VALUES (?, ?)", [(notice_id, r) for r in routes])


def _create(conn, source_id: int, item: ParsedNotice, now_iso: str) -> int:
    content = canonical_content(item.content())
    digest = content_hash(content)
    cur = conn.execute(
        """INSERT INTO notices (source_id, external_id, title, notice_type, summary, area, source_url, published_at,
                                valid_from, valid_to, withdrawn_at, content_hash, first_observed_at,
                                last_confirmed_at, last_changed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (source_id, item.external_id, content["title"], content["notice_type"], content["summary"], content["area"],
         content["source_url"], content["published_at"], content["valid_from"], content["valid_to"],
         now_iso if content["withdrawn"] else None, digest, now_iso, now_iso, now_iso),
    )
    notice_id = cur.lastrowid
    _replace_routes(conn, notice_id, content["routes"])
    revision_id = _add_revision(conn, notice_id, digest, "new", f"New notice: {content['title']}.", [], content, now_iso)
    _audit(conn, notice_id, source_id, "created", item.external_id, now_iso)
    return revision_id


def _apply_update(conn, existing: Mapping, new_content: dict, changes: list[FieldChange], now_iso: str,
                  summary: str | None = None) -> int:
    digest = content_hash(new_content)
    was_withdrawn = existing["withdrawn_at"] is not None
    withdrawn_at = existing["withdrawn_at"]
    if new_content["withdrawn"] and not was_withdrawn:
        withdrawn_at = now_iso
    elif not new_content["withdrawn"]:
        withdrawn_at = None
    conn.execute(
        """UPDATE notices SET title=?, notice_type=?, summary=?, area=?, source_url=?, published_at=?, valid_from=?,
                  valid_to=?, withdrawn_at=?, content_hash=?, last_confirmed_at=?, last_changed_at=? WHERE id=?""",
        (new_content["title"], new_content["notice_type"], new_content["summary"], new_content["area"],
         new_content["source_url"], new_content["published_at"], new_content["valid_from"], new_content["valid_to"],
         withdrawn_at, digest, now_iso, now_iso, existing["id"]),
    )
    _replace_routes(conn, existing["id"], new_content["routes"])
    change_type = classify_changes(changes)
    revision_id = _add_revision(conn, existing["id"], digest, change_type, summary or summarize_changes(changes),
                                changes, new_content, now_iso)
    _audit(conn, existing["id"], existing["source_id"], change_type, summary or summarize_changes(changes), now_iso)
    return revision_id


def ingest_notices(conn: sqlite3.Connection, source: Mapping, items: Sequence[ParsedNotice], now: datetime,
                   complete_listing: bool) -> IngestResult:
    """Idempotent upsert. The caller wraps this in a transaction. A notice that is
    unchanged only has last_confirmed_at refreshed: no revision, no alert."""
    result = IngestResult()
    now_iso = to_iso(now)
    tz_name = source["timezone"]
    seen: set[str] = set()

    for item in items:
        if item.external_id in seen:
            result.errors.append(f"{item.external_id}: duplicate id in one fetch; first copy kept.")
            continue
        seen.add(item.external_id)
        try:
            with savepoint(conn, "notice_sp"):
                existing = conn.execute("SELECT * FROM notices WHERE source_id = ? AND external_id = ?",
                                        (source["id"], item.external_id)).fetchone()
                if existing is None:
                    result.revision_ids.append(_create(conn, source["id"], item, now_iso))
                    result.new += 1
                    continue
                new_content = canonical_content(item.content())
                if existing["content_hash"] == content_hash(new_content):
                    conn.execute("UPDATE notices SET last_confirmed_at = ? WHERE id = ?", (now_iso, existing["id"]))
                    result.unchanged += 1
                    continue
                changes = diff_content(load_content(conn, existing), new_content, tz_name)
                if not changes:
                    conn.execute("UPDATE notices SET content_hash = ?, last_confirmed_at = ? WHERE id = ?",
                                 (content_hash(new_content), now_iso, existing["id"]))
                    result.unchanged += 1
                    continue
                result.revision_ids.append(_apply_update(conn, existing, new_content, changes, now_iso))
                if new_content["withdrawn"] and existing["withdrawn_at"] is None:
                    result.withdrawn += 1
                else:
                    result.revised += 1
        except sqlite3.Error as exc:
            result.errors.append(f"{item.external_id}: could not be saved ({type(exc).__name__}).")

    for item in items:
        conn.execute(
            """UPDATE notices SET latitude = ?, longitude = ?
               WHERE source_id = ? AND external_id = ? AND (latitude IS NOT ? OR longitude IS NOT ?)""",
            (item.latitude, item.longitude, source["id"], item.external_id, item.latitude, item.longitude))

    if complete_listing:
        _withdraw_missing(conn, source, seen, now_iso, tz_name, result)
    return result


def _withdraw_missing(conn, source, seen: set[str], now_iso: str, tz_name: str, result: IngestResult) -> None:
    rows = conn.execute(
        """SELECT * FROM notices WHERE source_id = ? AND withdrawn_at IS NULL
           AND (valid_to IS NULL OR valid_to >= ?)""", (source["id"], now_iso)).fetchall()
    for row in rows:
        if row["external_id"] in seen:
            continue
        old = load_content(conn, row)
        new = dict(old, withdrawn=True)
        changes = diff_content(old, new, tz_name)
        result.revision_ids.append(_apply_update(
            conn, row, new, changes, now_iso, summary="Withdrawn: the notice is no longer listed by the source."))
        # A notice that vanished was not confirmed by this fetch.
        conn.execute("UPDATE notices SET last_confirmed_at = ? WHERE id = ?", (row["last_confirmed_at"], row["id"]))
        result.withdrawn += 1
