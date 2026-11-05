import json

from scraper import demo_source
from scraper.fetcher import FetchError
from services import collector_service, notification_service
from services.collector_service import run_all, run_source
from services.notice_service import NoticeFilters, compute_status, get_stats, list_notices
from services.source_registry import seed_demo_subscription, sync_sources
from timeutil import to_iso


def setup_demo(conn, settings, clock):
    sync_sources(conn, settings, clock())
    seed_demo_subscription(conn, settings, clock())
    return conn.execute("SELECT * FROM sources WHERE code='DEMO-FEED'").fetchone()


def counts(conn):
    q = lambda t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    return q("notices"), q("notice_revisions"), q("notifications")


def test_first_run_collects_demo_notices(conn, settings, clock):
    setup_demo(conn, settings, clock)
    outcome = run_all(conn, settings, clock, "cli")
    assert outcome["status"] == "success" and outcome["reports"][0].new == 6
    assert conn.execute("SELECT COUNT(*) FROM notices").fetchone()[0] == 6


def test_repeated_runs_create_no_duplicates_or_alerts(conn, settings, clock):
    setup_demo(conn, settings, clock)
    run_all(conn, settings, clock, "cli")
    baseline = counts(conn)
    for _ in range(3):
        clock.advance(minutes=15)
        outcome = run_all(conn, settings, clock, "cli")
        assert outcome["reports"][0].new == 0 and outcome["reports"][0].revised == 0
    assert counts(conn) == baseline
    assert conn.execute("SELECT COUNT(*) FROM scraper_runs").fetchone()[0] == 4


def test_mentor_extends_outage_by_24_hours(conn, settings, clock):
    setup_demo(conn, settings, clock)
    run_all(conn, settings, clock, "cli")
    before = conn.execute("SELECT id, valid_to FROM notices WHERE external_id='DEMO-001'").fetchone()
    demo_source.apply_scenario(settings, "extend_outage", clock())
    clock.advance(minutes=15)
    run_all(conn, settings, clock, "cli")
    after = conn.execute("SELECT id, valid_to FROM notices WHERE external_id='DEMO-001'").fetchone()
    assert after["id"] == before["id"] and after["valid_to"] > before["valid_to"]
    types = [r[0] for r in conn.execute("SELECT change_type FROM notice_revisions WHERE notice_id=? ORDER BY revision_no", (after["id"],))]
    assert types == ["new", "extended"]
    notes = conn.execute("SELECT COUNT(*) FROM notifications WHERE notice_id=?", (after["id"],)).fetchone()[0]
    assert notes == 2  # one for the new notice, one for the extension (subscriber follows route 12A)


def test_advisory_without_end_date_does_not_crash(conn, settings, clock):
    setup_demo(conn, settings, clock)
    demo_source.apply_scenario(settings, "add_no_end_date", clock())
    run_all(conn, settings, clock, "cli")
    row = conn.execute("SELECT * FROM notices WHERE external_id='DEMO-099'").fetchone()
    assert row["valid_to"] is None
    assert compute_status(row, clock(), 360).display == "active"


def test_failed_fetch_does_not_refresh_old_data(conn, settings, clock):
    source = setup_demo(conn, settings, clock)
    run_all(conn, settings, clock, "cli")
    verified = conn.execute("SELECT MIN(last_confirmed_at) FROM notices").fetchone()[0]
    success_at = conn.execute("SELECT last_success_at FROM sources WHERE id=?", (source["id"],)).fetchone()[0]
    demo_source.apply_scenario(settings, "fail_on", clock())
    clock.advance(minutes=20)
    outcome = run_all(conn, settings, clock, "cli")
    assert outcome["status"] == "failed"
    assert conn.execute("SELECT MIN(last_confirmed_at) FROM notices").fetchone()[0] == verified
    row = conn.execute("SELECT * FROM sources WHERE id=?", (source["id"],)).fetchone()
    assert row["last_success_at"] == success_at and row["last_status"] == "failed" and "Simulated" in row["last_error"]
    assert conn.execute("SELECT COUNT(*) FROM notices WHERE withdrawn_at IS NOT NULL").fetchone()[0] == 0
    stats = get_stats(conn, clock(), settings)
    assert stats["any_source_failing"] and stats["last_verified_at"] == success_at


def test_old_notices_become_stale_not_live(conn, settings, clock):
    setup_demo(conn, settings, clock)
    run_all(conn, settings, clock, "cli")
    demo_source.apply_scenario(settings, "fail_on", clock())
    clock.advance(minutes=settings.freshness_minutes + 5)
    run_all(conn, settings, clock, "cli")
    found = list_notices(conn, NoticeFilters(status="stale"), clock(), settings)
    assert found and all(n["is_stale"] for n in found)
    assert not list_notices(conn, NoticeFilters(status="active"), clock(), settings)
    assert {n["lifecycle"] for n in found} <= {"active", "upcoming"}
    demo_source.apply_scenario(settings, "fail_off", clock())
    run_all(conn, settings, clock, "cli")
    assert list_notices(conn, NoticeFilters(status="active"), clock(), settings)


def test_empty_result_is_treated_as_failure_not_mass_withdrawal(conn, settings, clock, monkeypatch):
    source = setup_demo(conn, settings, clock)
    run_all(conn, settings, clock, "cli")
    feed = json.loads(settings.demo_feed_path.read_text())
    feed["notices"] = []
    settings.demo_feed_path.write_text(json.dumps(feed))
    report = run_source(conn, source, settings, clock, "cli")
    assert report.status == "failed" and "no notices" in report.error
    assert conn.execute("SELECT COUNT(*) FROM notices WHERE withdrawn_at IS NOT NULL").fetchone()[0] == 0


def test_withdraw_scenario_and_expiry_event_logged_once(conn, settings, clock):
    setup_demo(conn, settings, clock)
    run_all(conn, settings, clock, "cli")
    demo_source.apply_scenario(settings, "withdraw_notice", clock())
    run_all(conn, settings, clock, "cli")
    assert conn.execute("SELECT withdrawn_at IS NOT NULL FROM notices WHERE external_id='DEMO-005'").fetchone()[0]
    expired_events = lambda: conn.execute("SELECT COUNT(*) FROM audit_events WHERE event_type='expired'").fetchone()[0]
    first = expired_events()
    assert first >= 1  # DEMO-004 already ended
    run_all(conn, settings, clock, "cli")
    assert expired_events() == first


def test_unexpected_exception_is_recorded_not_raised(conn, settings, clock, monkeypatch):
    source = setup_demo(conn, settings, clock)
    monkeypatch.setattr(collector_service, "build_adapter", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    report = run_source(conn, source, settings, clock, "cli")
    assert report.status == "failed" and "RuntimeError" in report.error


def test_unapproved_live_source_is_not_enabled(conn, settings, clock, tmp_path):
    from dataclasses import replace
    cfg = tmp_path / "live.json"
    cfg.write_text(json.dumps({"sources": [{"code": "X", "agency_code": "XA", "agency_name": "X Agency", "name": "X",
                                            "type": "rss", "url": "https://example.org/feed", "enabled": True,
                                            "permission_status": "pending"}]}))
    notes = sync_sources(conn, replace(settings, live_sources_file=cfg), clock())
    assert any("not enabled" in n for n in notes)
    assert conn.execute("SELECT enabled FROM sources WHERE code='X'").fetchone()[0] == 0
