"""Cron expressions for schedules: check them, find the next times, say them in words.

Five fields (minute hour day-of-month month day-of-week), evaluated in the
schedule's own IANA timezone and returned as UTC — recomputed from the zone
every time, so "9:00 in Asia/Kolkata" stays 9:00 across DST changes in zones
that have them.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter

from builder.config import get_builder_settings

_DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]


class ScheduleError(ValueError):
    """A cron expression or timezone a schedule can't use; the message is for people."""


def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ScheduleError(f'"{name}" isn\'t a timezone we know (use one like "Asia/Kolkata" or "UTC").') from exc


def _iter(cron: str, tz: str, after: datetime) -> croniter:
    return croniter(cron, after.astimezone(zone(tz)))


def validate(cron: str, tz: str) -> None:
    """Raise ScheduleError unless the schedule is usable (and not too frequent)."""
    cron = (cron or "").strip()
    if len(cron.split()) != 5:
        raise ScheduleError("A schedule needs 5 parts: minute hour day month weekday (e.g. \"0 9 * * 1-5\").")
    if not croniter.is_valid(cron):
        raise ScheduleError(f'"{cron}" isn\'t a valid schedule.')
    zone(tz)
    minimum = get_builder_settings().SCHEDULE_MIN_INTERVAL_MINUTES
    times = upcoming(cron, tz, count=6)
    if len(times) < 2:
        raise ScheduleError("This schedule never runs.")
    gap = min((b - a).total_seconds() for a, b in zip(times, times[1:]))
    if gap < minimum * 60:
        raise ScheduleError(f"Schedules can run at most every {minimum} minutes.")


def next_run(cron: str, tz: str, after: datetime) -> datetime:
    """The first time strictly after ``after``, in UTC."""
    return _iter(cron, tz, after).get_next(datetime).astimezone(timezone.utc)


def upcoming(cron: str, tz: str, *, count: int = 3, after: datetime | None = None) -> list[datetime]:
    it = _iter(cron, tz, after or datetime.now(timezone.utc))
    out: list[datetime] = []
    for _ in range(count):
        try:
            out.append(it.get_next(datetime).astimezone(timezone.utc))
        except Exception:  # noqa: BLE001 — e.g. "30 2 31 2 *" (never)
            break
    return out


def _clock(hour: str, minute: str) -> str:
    h, m = int(hour), int(minute)
    return f"{(h % 12) or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"


def describe(cron: str) -> str:
    """The common shapes in words; anything else falls back to the expression."""
    parts = (cron or "").split()
    if len(parts) != 5:
        return cron
    minute, hour, dom, month, dow = parts
    plain = lambda v: v.isdigit()  # noqa: E731
    if minute.startswith("*/") and hour == dom == month == dow == "*":
        return f"Every {minute[2:]} minutes"
    if plain(minute) and hour == "*" and dom == month == dow == "*":
        return f"Every hour at :{int(minute):02d}"
    if plain(minute) and hour.startswith("*/") and dom == month == dow == "*":
        return f"Every {hour[2:]} hours at :{int(minute):02d}"
    if plain(minute) and plain(hour) and month == "*":
        at = _clock(hour, minute)
        if dom == "*" and dow == "*":
            return f"Every day at {at}"
        if dom == "*" and dow in ("1-5", "MON-FRI", "mon-fri"):
            return f"Weekdays at {at}"
        if dom == "*" and dow in ("0,6", "6,0", "SAT,SUN", "sat,sun"):
            return f"Weekends at {at}"
        if dom == "*" and plain(dow) and int(dow) <= 7:
            return f"Every {_DAYS[int(dow) % 7]} at {at}"
        if plain(dom) and dow == "*":
            return f"Monthly on day {int(dom)} at {at}"
    return f"Cron: {cron}"


__all__ = ["ScheduleError", "validate", "next_run", "upcoming", "describe", "zone"]
