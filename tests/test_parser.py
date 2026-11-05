from scraper.parser import (classify_notice_type, normalize_route_ids, parse_datetime, parse_notices_html, parse_rss)

TZ = "Asia/Kolkata"


def test_successful_extraction(fixtures_dir):
    result = parse_notices_html((fixtures_dir / "valid_advisories.html").read_text(), TZ, "https://example.org/")
    first = result.notices[0]
    assert [n.external_id for n in result.notices] == ["T-100", "T-101"]
    assert first.title == "Bridge works on Lake Road"
    assert first.summary == "Buses use the service road."
    assert first.routes == ["12A", "12B"]
    assert first.notice_type == "Planned Maintenance"
    assert first.published_at == "2026-10-20T03:30:00Z"
    assert first.valid_from == "2026-10-20T18:30:00Z"
    assert first.source_url == "https://example.org/notices/T-100"
    assert first.withdrawn is False


def test_date_only_end_means_end_of_local_day(fixtures_dir):
    result = parse_notices_html((fixtures_dir / "valid_advisories.html").read_text(), TZ)
    assert result.notices[0].valid_to == "2026-10-30T18:29:59Z"


def test_withdrawn_status_and_unsafe_link(fixtures_dir):
    second = parse_notices_html((fixtures_dir / "valid_advisories.html").read_text(), TZ).notices[1]
    assert second.withdrawn is True
    assert second.source_url is None
    assert second.valid_to is None


def test_missing_fields_are_reported_not_invented(fixtures_dir):
    result = parse_notices_html((fixtures_dir / "missing_fields.html").read_text(), TZ)
    ids = [n.external_id for n in result.notices]
    assert ids == ["F-1", "F-2"]
    assert result.skipped_items == 1
    empty = result.notices[0]
    assert empty.title == "Untitled notice F-1"
    assert empty.routes == [] and empty.valid_to is None and empty.published_at is None
    bad = result.notices[1]
    assert bad.valid_to is None  # end before start is ignored, not repaired
    assert bad.published_at is None
    assert any("could not read published_at" in w for w in result.warnings)
    assert any("end time is before start" in w for w in result.warnings)


def test_malformed_html_does_not_crash(fixtures_dir):
    result = parse_notices_html((fixtures_dir / "malformed.html").read_text(), TZ)
    assert len(result.notices) >= 1
    assert result.notices[0].external_id == "M-1"


def test_empty_or_unrelated_page_returns_warning():
    for html in ("", "<html><body><p>Maintenance page</p></body></html>"):
        result = parse_notices_html(html, TZ)
        assert result.notices == [] and result.warnings


def test_rss_parsing(fixtures_dir):
    result = parse_rss((fixtures_dir / "feed.xml").read_text(), TZ)
    assert len(result.notices) == 1 and result.skipped_items == 1
    item = result.notices[0]
    assert item.routes == ["4", "4A"] and item.summary == "Buses are diverted."
    assert item.notice_type == "Diversion" and item.valid_to is None
    assert parse_rss("<rss><broken", TZ).warnings


def test_rss_rejects_entity_bombs():
    bomb = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;">]><rss><channel><item><guid>&b;</guid></item></channel></rss>'
    assert parse_rss(bomb, TZ).notices == []


def test_helpers():
    assert normalize_route_ids(["12a, 12B", "9"]) == ["12A", "12B", "9"]
    assert normalize_route_ids(["<x>"]) == []
    assert classify_notice_type("Route cancelled today") == "Cancellation"
    assert classify_notice_type("hello") == "Other"
    assert parse_datetime("garbage", TZ) is None and parse_datetime("", TZ) is None
