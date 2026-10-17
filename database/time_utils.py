"""UTC serialization and local-day boundaries shared by repositories."""

from datetime import datetime, timedelta, timezone


def utc_now_string() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def local_day_bounds(offset_minutes: int, now=None):
    tz = timezone(timedelta(minutes=offset_minutes))
    now = now or datetime.now(timezone.utc)
    start = now.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return tuple(t.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") for t in (start, end))
