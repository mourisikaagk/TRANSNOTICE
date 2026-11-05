import sqlite3

import pytest

from database.db import MIGRATIONS_DIR, apply_migrations, connect, transaction
from services.ingest_service import ingest_notices
from services.notice_service import NoticeFilters, compute_status, list_notices
from tests.helpers import iso, make_notice, make_source


def ingest(conn, source, items, clock, complete=True):
    with transaction(conn):
        return ingest_notices(conn, source, items, clock(), complete)


def test_migrations_are_idempotent_and_match_schema_file(tmp_path):
    conn = connect(tmp_path / "a.db")
    assert apply_migrations(conn) == ["001_initial", "002_accounts_and_locations"]
    assert apply_migrations(conn) == []
    fresh = connect(tmp_path / "b.db")
    fresh.executescript((MIGRATIONS_DIR.parent / "schema.sql").read_text())
    names = lambda c: {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type IN ('table','index') AND name NOT LIKE 'sqlite_%'")}
    assert names(conn) - {"schema_migrations"} == names(fresh)


def test_duplicate_notices_are_prevented(conn, clock):
    source = make_source(conn)
    for _ in range(3):
        ingest(conn, source, [make_notice()], clock)
        clock.advance(minutes=15)
    assert conn.execute("SELECT COUNT(*) FROM notices").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM notice_revisions").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("""INSERT INTO notices (source_id, external_id, title, notice_type, content_hash, first_observed_at,
                        last_confirmed_at, last_changed_at) VALUES (?, 'N-1', 't', 'x', 'h', 'a', 'a', 'a')""", (source["id"],))


def test_multiple_routes_stored_and_filterable(conn, clock, settings):
    source = make_source(conn)
    ingest(conn, source, [make_notice(routes=["12A", "12B", "45"]), make_notice("N-2", routes=["99"])], clock)
    assert conn.execute("SELECT COUNT(*) FROM notice_routes").fetchone()[0] == 4
    for route in ("12A", "12B", "45"):
        found = list_notices(conn, NoticeFilters(route=route), clock(), settings)
        assert [n["external_id"] for n in found] == ["N-1"]
        assert found[0]["routes"] == ["12A", "12B", "45"]


def test_missing_end_date_is_stored_as_null_and_stays_active(conn, clock, settings):
    source = make_source(conn)
    ingest(conn, source, [make_notice(valid_to=None)], clock)
    row = conn.execute("SELECT * FROM notices").fetchone()
    assert row["valid_to"] is None
    clock.advance(days=30)
    assert compute_status(row, clock(), freshness_minutes=10**7).display == "active"


def test_expired_and_upcoming_status(conn, clock):
    source = make_source(conn)
    ingest(conn, source, [make_notice("E", valid_from=iso(-48), valid_to=iso(-1)),
                          make_notice("U", valid_from=iso(5), valid_to=iso(20)),
                          make_notice("A")], clock)
    status = {r["external_id"]: compute_status(r, clock(), 360).display for r in conn.execute("SELECT * FROM notices")}
    assert status == {"E": "expired", "U": "upcoming", "A": "active"}


def test_extension_updates_same_notice_and_keeps_history(conn, clock):
    source = make_source(conn)
    ingest(conn, source, [make_notice()], clock)
    notice_id = conn.execute("SELECT id FROM notices").fetchone()[0]
    clock.advance(minutes=15)
    result = ingest(conn, source, [make_notice(valid_to=iso(48))], clock)
    assert result.revised == 1 and result.new == 0
    assert conn.execute("SELECT id FROM notices").fetchone()[0] == notice_id
    revs = conn.execute("SELECT revision_no, change_type FROM notice_revisions ORDER BY revision_no").fetchall()
    assert [(r[0], r[1]) for r in revs] == [(1, "new"), (2, "extended")]


def test_route_association_change_creates_revision(conn, clock):
    source = make_source(conn)
    ingest(conn, source, [make_notice(routes=["1"])], clock)
    ingest(conn, source, [make_notice(routes=["1", "2"])], clock)
    assert conn.execute("SELECT change_type FROM notice_revisions WHERE revision_no=2").fetchone()[0] == "routes_changed"


def test_explicit_withdrawal_and_reinstatement(conn, clock):
    source = make_source(conn)
    ingest(conn, source, [make_notice()], clock)
    result = ingest(conn, source, [make_notice(withdrawn=True)], clock)
    assert result.withdrawn == 1
    assert conn.execute("SELECT withdrawn_at FROM notices").fetchone()[0] is not None
    ingest(conn, source, [make_notice()], clock)
    assert conn.execute("SELECT withdrawn_at FROM notices").fetchone()[0] is None
    assert conn.execute("SELECT change_type FROM notice_revisions ORDER BY revision_no DESC").fetchone()[0] == "reinstated"


def test_notice_missing_from_complete_listing_is_withdrawn(conn, clock):
    source = make_source(conn)
    ingest(conn, source, [make_notice("A"), make_notice("B")], clock)
    clock.advance(minutes=15)
    result = ingest(conn, source, [make_notice("A")], clock)
    assert result.withdrawn == 1
    row = conn.execute("SELECT withdrawn_at FROM notices WHERE external_id='B'").fetchone()
    assert row[0] is not None


def test_partial_listing_never_withdraws(conn, clock):
    source = make_source(conn, complete_listing=0)
    ingest(conn, source, [make_notice("A"), make_notice("B")], clock, complete=False)
    ingest(conn, source, [make_notice("A")], clock, complete=False)
    assert conn.execute("SELECT COUNT(*) FROM notices WHERE withdrawn_at IS NOT NULL").fetchone()[0] == 0


def test_expired_notice_missing_from_source_is_not_withdrawn(conn, clock):
    source = make_source(conn)
    ingest(conn, source, [make_notice("OLD", valid_from=iso(-48), valid_to=iso(-1)), make_notice("A")], clock)
    ingest(conn, source, [make_notice("A")], clock)
    assert conn.execute("SELECT withdrawn_at FROM notices WHERE external_id='OLD'").fetchone()[0] is None


def test_unchanged_notice_only_refreshes_confirmation_time(conn, clock):
    source = make_source(conn)
    ingest(conn, source, [make_notice()], clock)
    first = conn.execute("SELECT last_confirmed_at, last_changed_at FROM notices").fetchone()
    clock.advance(minutes=30)
    ingest(conn, source, [make_notice()], clock)
    second = conn.execute("SELECT last_confirmed_at, last_changed_at FROM notices").fetchone()
    assert second["last_confirmed_at"] > first["last_confirmed_at"]
    assert second["last_changed_at"] == first["last_changed_at"]


def test_foreign_keys_enforced(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO notice_routes (notice_id, route_id) VALUES (999, 'X')")


def test_upgrade_from_version_1_keeps_existing_data(tmp_path):
    conn = connect(tmp_path / "old.db")
    conn.executescript((MIGRATIONS_DIR / "001_initial.sql").read_text())
    conn.execute("CREATE TABLE schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
    conn.execute("INSERT INTO schema_migrations (version) VALUES ('001_initial')")
    source = make_source(conn)
    conn.execute("""INSERT INTO notices (source_id, external_id, title, notice_type, content_hash, first_observed_at,
                    last_confirmed_at, last_changed_at) VALUES (?, 'OLD-1', 'Bridge closed', 'Delay', 'h', 'a', 'a', 'a')""",
                 (source["id"],))
    conn.execute("""INSERT INTO notice_revisions (notice_id, revision_no, content_hash, change_type, change_summary,
                    changes_json, snapshot_json, observed_at) VALUES (1, 1, 'h', 'new', 'New', '[]', '{}', 'a')""")
    assert apply_migrations(conn) == ["002_accounts_and_locations"]
    row = conn.execute("SELECT title, latitude, longitude FROM notices").fetchone()
    assert row["title"] == "Bridge closed" and row["latitude"] is None and row["longitude"] is None
    assert conn.execute("SELECT COUNT(*) FROM notice_revisions").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE notices SET latitude = 120")
