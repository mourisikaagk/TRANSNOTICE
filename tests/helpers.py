from datetime import datetime, timedelta, timezone

from scraper.parser import ParsedNotice
from timeutil import to_iso

BASE_TIME = datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, start=BASE_TIME):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)
        return self.now


def iso(hours=0, base=BASE_TIME):
    return to_iso(base + timedelta(hours=hours))


def make_notice(external_id="N-1", **overrides):
    data = dict(external_id=external_id, title="Bridge closed", notice_type="Planned Maintenance",
                summary="Use the service road.", area="Lake Road", routes=["12A"],
                source_url="https://example.org/n/1", published_at=iso(-5), valid_from=iso(-2), valid_to=iso(24))
    data.update(overrides)
    return ParsedNotice(**data)


def make_source(conn, code="TEST-SRC", source_type="html", complete_listing=1, demo=False):
    conn.execute("INSERT OR IGNORE INTO agencies (code, name, is_demo) VALUES ('TEST', 'Test Agency', ?)", (int(demo),))
    agency = conn.execute("SELECT id FROM agencies WHERE code='TEST'").fetchone()["id"]
    conn.execute("""INSERT INTO sources (agency_id, code, name, source_type, url, complete_listing, timezone, refresh_minutes)
                    VALUES (?, ?, 'Test source', ?, 'https://example.org/advisories', ?, 'Asia/Kolkata', 15)""",
                 (agency, code, source_type, complete_listing))
    return conn.execute("SELECT * FROM sources WHERE code=?", (code,)).fetchone()
