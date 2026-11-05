from __future__ import annotations

import logging
import smtplib
import sqlite3
from datetime import datetime
from email.message import EmailMessage
from typing import Callable, Sequence

from config import Settings
from timeutil import format_local, to_iso

log = logging.getLogger(__name__)

CHANGE_LABELS = {
    "new": "New notice", "revised": "Notice updated", "extended": "Validity extended",
    "shortened": "Validity shortened", "routes_changed": "Routes changed",
    "withdrawn": "Notice withdrawn", "reinstated": "Notice reinstated",
}


def send_email(settings: Settings, to_address: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = settings.mail_from, to_address, subject
    message.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
        if settings.smtp_use_tls:
            server.starttls()
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(message)


def _compose(conn: sqlite3.Connection, revision: sqlite3.Row, settings: Settings) -> tuple[str, str]:
    notice = conn.execute(
        """SELECT n.*, a.name AS agency_name, a.is_demo FROM notices n
           JOIN sources s ON s.id = n.source_id JOIN agencies a ON a.id = s.agency_id WHERE n.id = ?""",
        (revision["notice_id"],)).fetchone()
    routes = ", ".join(r["route_id"] for r in conn.execute(
        "SELECT route_id FROM notice_routes WHERE notice_id = ? ORDER BY route_id", (notice["id"],)))
    tz = settings.display_timezone
    label = CHANGE_LABELS.get(revision["change_type"], "Notice updated")
    prefix = "[DEMO] " if notice["is_demo"] else ""
    subject = f"{prefix}{label}: {notice['title']}"
    ends = format_local(notice["valid_to"], tz) or "no end time announced"
    body = "\n".join([
        f"{label} from {notice['agency_name']}", "",
        f"Notice: {notice['title']}", f"Routes: {routes or 'not stated'}", f"Area: {notice['area'] or 'not stated'}",
        f"Valid until: {ends}", f"What changed: {revision['change_summary']}",
        f"Source: {notice['source_url'] or 'not provided'}",
        f"Recorded at: {format_local(revision['observed_at'], tz)}",
        *(["", "This is a demonstration notice. It is not real transport information."] if notice["is_demo"] else []),
    ])
    return subject, body


def queue_notifications(conn: sqlite3.Connection, revision_ids: Sequence[int], settings: Settings,
                        now: datetime) -> int:
    """One row per (subscription, revision). The UNIQUE constraint makes repeats harmless."""
    created = 0
    now_iso = to_iso(now)
    for revision_id in revision_ids:
        revision = conn.execute("SELECT * FROM notice_revisions WHERE id = ?", (revision_id,)).fetchone()
        if revision is None:
            continue
        subscribers = conn.execute(
            """SELECT s.id FROM subscriptions s WHERE s.active = 1 AND s.created_at <= ?
               AND (s.route_filter IS NULL OR EXISTS (
                    SELECT 1 FROM notice_routes r WHERE r.notice_id = ? AND r.route_id = s.route_filter))""",
            (revision["observed_at"], revision["notice_id"])).fetchall()
        if not subscribers:
            continue
        subject, body = _compose(conn, revision, settings)
        for sub in subscribers:
            cur = conn.execute(
                """INSERT OR IGNORE INTO notifications (subscription_id, notice_id, revision_id, subject, body, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (sub["id"], revision["notice_id"], revision_id, subject, body, now_iso))
            created += cur.rowcount
    return created


def deliver_pending(conn: sqlite3.Connection, settings: Settings, now: datetime,
                    mailer: Callable[..., None] = send_email) -> dict:
    """Demo notifications are only logged. E-mail is marked 'smtp_accepted' when the mail server accepts it;
    final delivery to an inbox cannot be confirmed over SMTP, so it is never claimed."""
    stats = {"demo_logged": 0, "smtp_accepted": 0, "failed": 0, "skipped": 0}
    now_iso = to_iso(now)
    rows = conn.execute(
        """SELECT nt.*, s.channel, s.email FROM notifications nt JOIN subscriptions s ON s.id = nt.subscription_id
           WHERE nt.status = 'pending' OR (nt.status = 'failed' AND nt.attempts < ?) ORDER BY nt.id""",
        (settings.max_notification_attempts,)).fetchall()
    for row in rows:
        attempts = row["attempts"] + 1
        if row["channel"] == "demo":
            conn.execute("UPDATE notifications SET status='demo_logged', attempts=?, alerted_at=?, error=NULL WHERE id=?",
                         (attempts, now_iso, row["id"]))
            stats["demo_logged"] += 1
        elif not settings.email_enabled:
            conn.execute("UPDATE notifications SET status='skipped', attempts=?, error=? WHERE id=?",
                         (attempts, "E-mail delivery is not configured.", row["id"]))
            stats["skipped"] += 1
        else:
            try:
                mailer(settings, row["email"], row["subject"], row["body"])
            except (OSError, smtplib.SMTPException) as exc:
                log.warning("E-mail for notification %s failed: %s", row["id"], type(exc).__name__)
                conn.execute("UPDATE notifications SET status='failed', attempts=?, error=? WHERE id=?",
                             (attempts, f"Mail server error: {type(exc).__name__}", row["id"]))
                stats["failed"] += 1
            else:
                conn.execute("UPDATE notifications SET status='smtp_accepted', attempts=?, alerted_at=?, sent_at=?, error=NULL WHERE id=?",
                             (attempts, now_iso, now_iso, row["id"]))
                stats["smtp_accepted"] += 1
    return stats
