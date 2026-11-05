"""Time helpers. Every timestamp is stored in UTC as 'YYYY-MM-DDTHH:MM:SSZ'
and converted to the display time zone only when shown to a person."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
UTC = timezone.utc


def utcnow() -> datetime:
    return datetime.now(UTC)


def to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("Naive datetime: a time zone is required")
    return dt.astimezone(UTC).strftime(ISO_FORMAT)


def from_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(value, ISO_FORMAT).replace(tzinfo=UTC)


def localize(value: str | datetime | None, tz_name: str) -> datetime | None:
    if value is None or value == "":
        return None
    dt = from_iso(value) if isinstance(value, str) else value
    return dt.astimezone(ZoneInfo(tz_name))


def format_local(value: str | datetime | None, tz_name: str, with_zone: bool = True) -> str:
    local = localize(value, tz_name)
    if local is None:
        return ""
    text = local.strftime("%d %b %Y, %H:%M")
    return f"{text} {local.tzname()}" if with_zone else text


def local_day_bounds(day: date, tz_name: str) -> tuple[str, str]:
    """UTC bounds of one calendar day in the display time zone."""
    tz = ZoneInfo(tz_name)
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = start + timedelta(days=1) - timedelta(seconds=1)
    return to_iso(start), to_iso(end)


def humanize_age(value: str | datetime | None, now: datetime) -> str:
    dt = from_iso(value) if isinstance(value, str) else value
    if dt is None:
        return "never"
    seconds = int((now - dt).total_seconds())
    future = seconds < 0
    seconds = abs(seconds)
    if seconds < 60:
        text = "moments"
    elif seconds < 3600:
        text = f"{seconds // 60} min"
    elif seconds < 86400:
        hours, minutes = divmod(seconds // 60, 60)
        text = f"{hours} h {minutes} min" if minutes else f"{hours} h"
    else:
        days, rem = divmod(seconds, 86400)
        text = f"{days} d {rem // 3600} h" if rem // 3600 else f"{days} d"
    return f"in {text}" if future else f"{text} ago"
