from services.collector_service import is_due, run_all
from services.scheduler_service import SchedulerService
from services.source_registry import sync_sources


def test_due_logic_respects_refresh_interval(conn, settings, clock):
    sync_sources(conn, settings, clock())
    source = conn.execute("SELECT * FROM sources WHERE code='DEMO-FEED'").fetchone()
    assert is_due(source, clock())
    run_all(conn, settings, clock, "scheduler")
    source = conn.execute("SELECT * FROM sources WHERE code='DEMO-FEED'").fetchone()
    assert not is_due(source, clock())
    clock.advance(minutes=settings.refresh_interval_minutes)
    assert is_due(source, clock())


def test_scheduler_tick_runs_only_due_sources(conn, settings, clock):
    sync_sources(conn, settings, clock())
    scheduler = SchedulerService(settings, clock)
    first = scheduler.tick()
    second = scheduler.tick()
    assert len(first["reports"]) == 1 and second["reports"] == []
    assert conn.execute("SELECT COUNT(*) FROM scraper_runs").fetchone()[0] == 1
    assert conn.execute("SELECT trigger FROM scraper_runs").fetchone()[0] == "scheduler"
