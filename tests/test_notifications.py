from services.collector_service import run_all
from services.notification_service import deliver_pending, queue_notifications
from services.source_registry import seed_demo_subscription, sync_sources
from services.ingest_service import ingest_notices
from database.db import transaction
from scraper import demo_source
from tests.helpers import make_notice, make_source


def prepare(conn, settings, clock):
    sync_sources(conn, settings, clock())
    seed_demo_subscription(conn, settings, clock())


def test_notification_created_once_per_subscription_and_revision(conn, settings, clock):
    prepare(conn, settings, clock)
    run_all(conn, settings, clock, "cli")
    total = conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
    assert total == 1  # only DEMO-001 uses route 12A
    revisions = [r[0] for r in conn.execute("SELECT id FROM notice_revisions")]
    assert queue_notifications(conn, revisions, settings, clock()) == 0
    run_all(conn, settings, clock, "cli")
    assert conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0] == total


def test_demo_notifications_are_logged_not_claimed_delivered(conn, settings, clock):
    prepare(conn, settings, clock)
    run_all(conn, settings, clock, "cli")
    row = conn.execute("SELECT * FROM notifications").fetchone()
    assert row["status"] == "demo_logged" and row["sent_at"] is None and row["alerted_at"]
    assert row["subject"].startswith("[DEMO]") and "not real transport information" in row["body"]


def test_each_revision_alerts_once(conn, settings, clock):
    prepare(conn, settings, clock)
    run_all(conn, settings, clock, "cli")
    demo_source.apply_scenario(settings, "extend_outage", clock())
    clock.advance(minutes=15)
    run_all(conn, settings, clock, "cli")
    run_all(conn, settings, clock, "cli")
    assert conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0] == 2


def test_route_filter_and_pause(conn, settings, clock):
    source = make_source(conn)
    conn.execute("INSERT INTO subscriptions (label, route_filter, channel, created_at) VALUES ('r99', '99', 'demo', ?)",
                 ("2026-01-01T00:00:00Z",))
    conn.execute("INSERT INTO subscriptions (label, route_filter, channel, active, created_at) VALUES ('paused', NULL, 'demo', 0, ?)",
                 ("2026-01-01T00:00:00Z",))
    with transaction(conn):
        outcome = ingest_notices(conn, source, [make_notice(routes=["12A"])], clock(), True)
    assert queue_notifications(conn, outcome.revision_ids, settings, clock()) == 0


def test_email_failure_is_recorded_and_retried(conn, settings, clock):
    from dataclasses import replace
    mail = replace(settings, smtp_host="smtp.invalid", mail_from="a@b.example")
    source = make_source(conn)
    conn.execute("INSERT INTO subscriptions (label, channel, email, created_at) VALUES ('mail', 'email', 'x@y.example', '2026-01-01T00:00:00Z')")
    with transaction(conn):
        outcome = ingest_notices(conn, source, [make_notice()], clock(), True)
    queue_notifications(conn, outcome.revision_ids, mail, clock())

    def failing(*args):
        raise OSError("refused")
    assert deliver_pending(conn, mail, clock(), failing)["failed"] == 1
    row = conn.execute("SELECT * FROM notifications").fetchone()
    assert row["status"] == "failed" and row["sent_at"] is None and row["attempts"] == 1
    sent = []
    assert deliver_pending(conn, mail, clock(), lambda *a: sent.append(a))["smtp_accepted"] == 1
    assert len(sent) == 1
    assert deliver_pending(conn, mail, clock(), lambda *a: sent.append(a)) == {"demo_logged": 0, "smtp_accepted": 0, "failed": 0, "skipped": 0}
    assert len(sent) == 1


def test_email_not_configured_is_skipped_honestly(conn, settings, clock):
    source = make_source(conn)
    conn.execute("INSERT INTO subscriptions (label, channel, email, created_at) VALUES ('mail', 'email', 'x@y.example', '2026-01-01T00:00:00Z')")
    with transaction(conn):
        outcome = ingest_notices(conn, source, [make_notice()], clock(), True)
    queue_notifications(conn, outcome.revision_ids, settings, clock())
    deliver_pending(conn, settings, clock())
    row = conn.execute("SELECT status, error FROM notifications").fetchone()
    assert row["status"] == "skipped" and "not configured" in row["error"]
