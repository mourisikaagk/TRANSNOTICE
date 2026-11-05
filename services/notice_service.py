from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Mapping

from config import Settings
from timeutil import from_iso, humanize_age, local_day_bounds, to_iso

STATUS_ORDER = {"active": 0, "upcoming": 1, "stale": 2, "expired": 3, "withdrawn": 4}
STATUSES = tuple(STATUS_ORDER)


@dataclass(frozen=True)
class StatusInfo:
    lifecycle: str
    display: str
    is_stale: bool


def compute_status(row: Mapping, now: datetime, freshness_minutes: int) -> StatusInfo:
    """Lifecycle comes from the announced window; 'stale' overrides active/upcoming
    when the notice has not been confirmed recently, so old data is never shown as live."""
    if row["withdrawn_at"]:
        return StatusInfo("withdrawn", "withdrawn", False)
    now_iso = to_iso(now)
    if row["valid_from"] and now_iso < row["valid_from"]:
        lifecycle = "upcoming"
    elif row["valid_to"] and now_iso > row["valid_to"]:
        return StatusInfo("expired", "expired", False)
    else:
        lifecycle = "active"
    confirmed = from_iso(row["last_confirmed_at"])
    stale = confirmed is None or (now - confirmed).total_seconds() > freshness_minutes * 60
    return StatusInfo(lifecycle, "stale" if stale else lifecycle, stale)


@dataclass
class NoticeFilters:
    q: str = ""
    route: str = ""
    agency: str = ""
    notice_type: str = ""
    status: str = ""
    service_date: str = ""
    routes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def from_args(cls, args: Mapping) -> "NoticeFilters":
        f = cls()
        f.q = (args.get("q") or "").strip()[:100]
        f.route = (args.get("route") or "").strip().upper()[:12]
        f.agency = (args.get("agency") or "").strip()[:40]
        f.notice_type = (args.get("type") or "").strip()[:40]
        status = (args.get("status") or "").strip().lower()
        if status and status not in STATUSES:
            f.warnings.append(f"Unknown status '{status[:20]}' was ignored.")
            status = ""
        f.status = status
        raw_date = (args.get("date") or "").strip()
        if raw_date:
            try:
                date.fromisoformat(raw_date)
                f.service_date = raw_date
            except ValueError:
                f.warnings.append("The service date was not a valid date and was ignored.")
        return f

    def active_count(self) -> int:
        return sum(bool(v) for v in (self.q, self.route, self.agency, self.notice_type, self.status, self.service_date))


def _like(text: str) -> str:
    escaped = text.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


NOTICE_SELECT = """
SELECT n.*, a.name AS agency_name, a.code AS agency_code, a.is_demo AS is_demo,
       s.name AS source_name, s.last_success_at AS source_last_success_at,
       s.last_attempt_at AS source_last_attempt_at, s.last_status AS source_last_status,
       (SELECT COUNT(*) FROM notice_revisions rv WHERE rv.notice_id = n.id) AS revision_count
FROM notices n
JOIN sources s ON s.id = n.source_id
JOIN agencies a ON a.id = s.agency_id
"""


def _routes_for(conn: sqlite3.Connection, notice_ids: list[int]) -> dict[int, list[str]]:
    routes: dict[int, list[str]] = {i: [] for i in notice_ids}
    if not notice_ids:
        return routes
    marks = ",".join("?" * len(notice_ids))
    for row in conn.execute(
        f"SELECT notice_id, route_id FROM notice_routes WHERE notice_id IN ({marks}) ORDER BY route_id", notice_ids
    ):
        routes[row["notice_id"]].append(row["route_id"])
    return routes


def _decorate(row: sqlite3.Row, routes: list[str], now: datetime, settings: Settings) -> dict:
    notice = dict(row)
    info = compute_status(notice, now, settings.freshness_minutes)
    notice.update(
        routes=routes, status=info.display, lifecycle=info.lifecycle, is_stale=info.is_stale,
        has_end_date=bool(notice["valid_to"]),
        confirmed_ago=humanize_age(notice["last_confirmed_at"], now),
    )
    return notice


def list_notices(conn: sqlite3.Connection, filters: NoticeFilters, now: datetime, settings: Settings,
                 limit: int = 300) -> list[dict]:
    where, params = ["1 = 1"], {}
    if filters.q:
        params["q"] = _like(filters.q)
        where.append(
            r"""(LOWER(n.title) LIKE :q ESCAPE '\' OR LOWER(IFNULL(n.summary, '')) LIKE :q ESCAPE '\'
              OR LOWER(IFNULL(n.area, '')) LIKE :q ESCAPE '\' OR LOWER(a.name) LIKE :q ESCAPE '\'
              OR LOWER(n.external_id) LIKE :q ESCAPE '\'
              OR EXISTS (SELECT 1 FROM notice_routes r WHERE r.notice_id = n.id
                         AND LOWER(r.route_id) LIKE :q ESCAPE '\'))"""
        )
    if filters.route:
        params["route"] = filters.route
        where.append("EXISTS (SELECT 1 FROM notice_routes r WHERE r.notice_id = n.id AND r.route_id = :route)")
    if filters.routes:
        names = {f"mr{i}": r for i, r in enumerate(filters.routes)}
        params.update(names)
        marks = ", ".join(f":{k}" for k in names)
        where.append(f"EXISTS (SELECT 1 FROM notice_routes r WHERE r.notice_id = n.id AND r.route_id IN ({marks}))")
    if filters.agency:
        params["agency"] = filters.agency
        where.append("a.code = :agency")
    if filters.notice_type:
        params["ntype"] = filters.notice_type
        where.append("n.notice_type = :ntype")
    if filters.service_date:
        start, end = local_day_bounds(date.fromisoformat(filters.service_date), settings.display_timezone)
        params.update(day_start=start, day_end=end)
        where.append("(n.valid_from IS NULL OR n.valid_from <= :day_end) AND (n.valid_to IS NULL OR n.valid_to >= :day_start)")

    rows = conn.execute(f"{NOTICE_SELECT} WHERE {' AND '.join(where)} ORDER BY n.last_changed_at DESC, n.id", params).fetchall()
    routes = _routes_for(conn, [r["id"] for r in rows])
    notices = [_decorate(r, routes[r["id"]], now, settings) for r in rows]
    if filters.status:
        notices = [n for n in notices if n["status"] == filters.status]
    notices.sort(key=lambda n: STATUS_ORDER[n["status"]])
    return notices[:limit]


def get_notice(conn: sqlite3.Connection, notice_id: int, now: datetime, settings: Settings) -> dict | None:
    row = conn.execute(f"{NOTICE_SELECT} WHERE n.id = ?", (notice_id,)).fetchone()
    if row is None:
        return None
    notice = _decorate(row, _routes_for(conn, [notice_id])[notice_id], now, settings)
    revisions = []
    for rev in conn.execute("SELECT * FROM notice_revisions WHERE notice_id = ? ORDER BY revision_no DESC", (notice_id,)):
        item = dict(rev)
        item["changes"] = json.loads(item["changes_json"])
        revisions.append(item)
    notice["revisions"] = revisions
    notice["events"] = [dict(r) for r in conn.execute(
        "SELECT event_type, detail, created_at FROM audit_events WHERE notice_id = ? ORDER BY id DESC LIMIT 20", (notice_id,))]
    return notice


def get_stats(conn: sqlite3.Connection, now: datetime, settings: Settings) -> dict:
    counts = {status: 0 for status in STATUSES}
    for row in conn.execute("SELECT valid_from, valid_to, withdrawn_at, last_confirmed_at FROM notices"):
        counts[compute_status(row, now, settings.freshness_minutes).display] += 1
    sources = [dict(r) for r in conn.execute(
        """SELECT s.id, s.code, s.name, s.last_attempt_at, s.last_success_at, s.last_status, s.last_error,
                  a.is_demo AS is_demo FROM sources s JOIN agencies a ON a.id = s.agency_id
           WHERE s.enabled = 1 ORDER BY s.id""")]
    successes = [s["last_success_at"] for s in sources if s["last_success_at"]]
    change = conn.execute("SELECT MAX(last_changed_at) AS m, COUNT(*) AS c FROM notices").fetchone()
    return {
        "counts": counts,
        "total": sum(counts.values()),
        "sources": sources,
        "last_verified_at": max(successes) if successes else None,
        "any_source_failing": any(s["last_status"] == "failed" for s in sources),
        "demo_mode": any(s["is_demo"] for s in sources),
        "change_token": f"{change['m'] or ''}|{change['c']}",
    }


def filter_options(conn: sqlite3.Connection) -> dict:
    return {
        "routes": [r["route_id"] for r in conn.execute("SELECT DISTINCT route_id FROM notice_routes ORDER BY route_id")],
        "types": [r["notice_type"] for r in conn.execute("SELECT DISTINCT notice_type FROM notices ORDER BY notice_type")],
        "agencies": [dict(r) for r in conn.execute("SELECT code, name FROM agencies ORDER BY name")],
    }


def record_expiry_events(conn: sqlite3.Connection, now: datetime) -> int:
    """Write one audit event per notice end time that has passed (never creates revisions or alerts)."""
    now_iso = to_iso(now)
    cur = conn.execute(
        """INSERT INTO audit_events (notice_id, source_id, event_type, detail, created_at)
           SELECT n.id, n.source_id, 'expired', n.valid_to, ?
           FROM notices n
           WHERE n.withdrawn_at IS NULL AND n.valid_to IS NOT NULL AND n.valid_to < ?
             AND NOT EXISTS (SELECT 1 FROM audit_events e
                             WHERE e.notice_id = n.id AND e.event_type = 'expired' AND e.detail = n.valid_to)""",
        (now_iso, now_iso),
    )
    return cur.rowcount


def recent_changes(conn: sqlite3.Connection, now: datetime, limit: int = 6) -> list[dict]:
    rows = conn.execute(
        """SELECT rv.notice_id, rv.change_type, rv.change_summary, rv.observed_at, rv.revision_no, n.title
           FROM notice_revisions rv JOIN notices n ON n.id = rv.notice_id
           ORDER BY rv.observed_at DESC, rv.id DESC LIMIT ?""", (limit,)).fetchall()
    return [dict(r, ago=humanize_age(r["observed_at"], now)) for r in rows]


def build_diagram(notices: list[dict], width: int = 900, row_height: int = 74) -> dict:
    """Schematic service-status diagram: one line per route, one node per notice.
    Node positions are evenly spaced and carry no geographic meaning."""
    live = [n for n in notices if n["status"] in ("active", "upcoming", "stale")]
    by_route: dict[str, list[dict]] = {}
    for notice in live:
        for route in notice["routes"]:
            by_route.setdefault(route, []).append(notice)
    left, right = 120, width - 40
    rows = []
    for index, route in enumerate(sorted(by_route)):
        items = by_route[route]
        gap = (right - left) / (len(items) + 1)
        nodes = [{
            "x": round(left + gap * (i + 1)), "id": n["id"], "status": n["status"],
            "label": (n["area"] or n["title"])[:26], "title": n["title"],
        } for i, n in enumerate(items)]
        rows.append({"route": route, "y": 40 + index * row_height, "nodes": nodes})
    return {"width": width, "height": 40 + max(len(rows), 1) * row_height, "rows": rows, "left": left, "right": right}
