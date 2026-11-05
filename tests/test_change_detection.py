from scraper.change_detector import classify_changes, content_hash, diff_content
from tests.helpers import make_notice

TZ = "Asia/Kolkata"


def content(**kw):
    return make_notice(**kw).content()


def test_hash_ignores_route_order_and_whitespace():
    a = content(routes=["B", "A"], summary="x  y")
    b = content(routes=["A", "B"], summary="x y")
    assert content_hash(a) == content_hash(b)


def test_hash_changes_on_any_tracked_field():
    base = content_hash(content())
    for change in ({"summary": "other"}, {"area": "elsewhere"}, {"valid_to": None}, {"withdrawn": True}, {"routes": ["99"]}):
        assert content_hash(content(**change)) != base


def test_extension_and_shortening():
    old = content()
    longer = diff_content(old, content(valid_to="2026-10-28T09:00:00Z"), TZ)
    assert classify_changes(longer) == "extended"
    shorter = diff_content(old, content(valid_to="2026-10-26T10:00:00Z"), TZ)
    assert classify_changes(shorter) == "shortened"


def test_end_date_added_and_removed():
    assert diff_content(content(valid_to=None), content(), TZ)[0].kind == "end_set"
    removed = diff_content(content(), content(valid_to=None), TZ)
    assert classify_changes(removed) == "extended" and "open-ended" in removed[0].description


def test_route_changes_described():
    changes = diff_content(content(routes=["1", "2"]), content(routes=["2", "3"]), TZ)
    assert classify_changes(changes) == "routes_changed"
    assert "added 3" in changes[0].description and "removed 1" in changes[0].description


def test_withdrawn_takes_priority_and_summary_edit():
    changes = diff_content(content(), content(withdrawn=True, summary="new text"), TZ)
    assert classify_changes(changes) == "withdrawn"
    assert {c.field for c in changes} == {"withdrawn", "summary"}


def test_identical_content_has_no_changes():
    assert diff_content(content(), content(), TZ) == []
