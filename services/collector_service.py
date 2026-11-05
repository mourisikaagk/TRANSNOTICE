from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from config import Settings
from database.db import transaction
from scraper.adapters import build_adapter
from scraper.fetcher import FetchError, Fetcher
from services import notice_service, notification_service
from services.ingest_service import ingest_notices
from timeutil import from_iso, to_iso

log = logging.getLogger(__name__)
RUN_LOCK = threading.Lock()


class CollectionError(Exception):
    pass


@dataclass
class RunReport:
    source_code: str
    status: str
    new: int = 0
    revised: int = 0
    withdrawn: int = 0
    unchanged: int = 0
    warnings: int = 0
    error: str | None = None
    run_id: int | None = None


def _short(message: str, limit: int = 300) -> str:
    return " ".join(message.split())[:limit]


def run_source(conn: sqlite3.Connection, source: sqlite3.Row, settings: Settings, clock: Callable[[], datetime],
               trigger: str, fetcher: Fetcher | None = None) -> RunReport:
    started = clock()
    run_id = conn.execute(
        "INSERT INTO scraper_runs (source_id, trigger, started_at, status) VALUES (?, ?, ?, 'running')",
        (source["id"], trigger, to_iso(started))).lastrowid
    conn.execute("UPDATE sources SET last_attempt_at = ? WHERE id = ?", (to_iso(started), source["id"]))
    report = RunReport(source["code"], "success", run_id=run_id)
    http_status = attempts = None
    items_found = 0
    try:
        if source["source_type"] != "demo" and fetcher is None:
            fetcher = Fetcher(settings)
        result = build_adapter(source, settings, fetcher).collect(started)
        http_status, attempts, items_found = result.http_status, result.attempts, len(result.notices)
        has_existing = conn.execute(
            "SELECT 1 FROM notices WHERE source_id = ? AND withdrawn_at IS NULL LIMIT 1", (source["id"],)).fetchone()
        if not result.notices and has_existing:
            raise CollectionError("Source returned no notices; keeping existing data (layout may have changed).")
        complete = bool(source["complete_listing"]) and result.skipped_items == 0
        finished = clock()
        with transaction(conn):
            outcome = ingest_notices(conn, source, result.notices, finished, complete)
            conn.execute("UPDATE sources SET last_success_at = ?, last_status = 'success', last_error = NULL WHERE id = ?",
                         (to_iso(finished), source["id"]))
        notification_service.queue_notifications(conn, outcome.revision_ids, settings, finished)
        report.new, report.revised, report.withdrawn, report.unchanged = (
            outcome.new, outcome.revised, outcome.withdrawn, outcome.unchanged)
        report.warnings = len(result.warnings) + len(outcome.errors)
        for warning in (result.warnings + outcome.errors)[:20]:
            log.warning("[%s] %s", source["code"], warning)
    except (FetchError, CollectionError) as exc:
        report.status, report.error = "failed", _short(str(exc))
        http_status = getattr(exc, "status_code", None)
        attempts = getattr(exc, "attempts", None)
    except Exception as exc:  # unexpected bug: record it, never crash the scheduler
        log.exception("Unexpected error while collecting %s", source["code"])
        report.status, report.error = "failed", f"Unexpected error: {type(exc).__name__}"

    finished = clock()
    if report.status == "failed":
        log.error("[%s] collection failed: %s", source["code"], report.error)
        conn.execute("UPDATE sources SET last_status = 'failed', last_error = ? WHERE id = ?", (report.error, source["id"]))
    conn.execute(
        """UPDATE scraper_runs SET finished_at=?, status=?, http_status=?, attempts=?, items_found=?, new_count=?,
                  revised_count=?, withdrawn_count=?, unchanged_count=?, warning_count=?, error_message=? WHERE id=?""",
        (to_iso(finished), report.status, http_status, attempts, items_found, report.new, report.revised,
         report.withdrawn, report.unchanged, report.warnings, report.error, run_id))
    return report


def is_due(source: sqlite3.Row, now: datetime) -> bool:
    last = from_iso(source["last_attempt_at"])
    return last is None or (now - last).total_seconds() >= source["refresh_minutes"] * 60


def run_all(conn: sqlite3.Connection, settings: Settings, clock: Callable[[], datetime], trigger: str,
            only_due: bool = False, fetcher: Fetcher | None = None) -> dict:
    if not RUN_LOCK.acquire(blocking=False):
        return {"status": "busy", "reports": []}
    try:
        now = clock()
        sources = conn.execute("SELECT * FROM sources WHERE enabled = 1 ORDER BY id").fetchall()
        reports = [run_source(conn, s, settings, clock, trigger, fetcher)
                   for s in sources if not only_due or is_due(s, now)]
        notice_service.record_expiry_events(conn, clock())
        delivery = notification_service.deliver_pending(conn, settings, clock())
        failed = [r for r in reports if r.status == "failed"]
        return {"status": "failed" if reports and len(failed) == len(reports) else "partial" if failed else "success",
                "reports": reports, "delivery": delivery}
    finally:
        RUN_LOCK.release()
