from datetime import date

import pytest

from timeutil import format_local, from_iso, humanize_age, local_day_bounds, to_iso
from tests.helpers import BASE_TIME


def test_storage_is_utc_and_display_is_ist():
    assert to_iso(BASE_TIME) == "2026-10-26T09:00:00Z"
    assert format_local("2026-10-26T09:00:00Z", "Asia/Kolkata") == "26 Oct 2026, 14:30 IST"


def test_naive_datetimes_are_rejected():
    with pytest.raises(ValueError):
        to_iso(BASE_TIME.replace(tzinfo=None))


def test_local_day_bounds_cross_utc_dates():
    start, end = local_day_bounds(date(2026, 10, 26), "Asia/Kolkata")
    assert start == "2026-10-25T18:30:00Z" and end == "2026-10-26T18:29:59Z"


def test_round_trip_and_humanize():
    assert from_iso(to_iso(BASE_TIME)) == BASE_TIME
    assert humanize_age("2026-10-26T08:55:00Z", BASE_TIME) == "5 min ago"
    assert humanize_age("2026-10-26T06:30:00Z", BASE_TIME) == "2 h 30 min ago"
    assert humanize_age(None, BASE_TIME) == "never"
