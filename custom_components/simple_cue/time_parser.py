"""Natural language datetime parser for Simple Cue.

Supported expressions
---------------------
Relative offsets:
  "in 2 hours"  /  "in 30 minutes"  /  "in 3 days"

Day anchors + time:
  "today at 5am"         "today at 17:30"
  "tomorrow at 5am"      "5am tomorrow"
  "monday at 9am"        (next occurrence; rolls to +7 days if already past)
  "next monday at 9am"   (always the coming Monday, never today)

Time-only shorthands:
  "noon"   →  12:00 today (or tomorrow if already past)
  "midnight" → 00:00 tomorrow (always future)

Time formats accepted wherever a time is expected:
  5am  /  5pm  /  5:30am  /  17:00  /  noon  /  midnight

All times are interpreted in the HA-configured local timezone.
ISO-8601 strings are intentionally NOT handled here — the caller tries
dt_util.parse_datetime() first and only falls through to this parser.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from homeassistant.util import dt as dt_util

# ---------------------------------------------------------------------------
# Weekday table
# ---------------------------------------------------------------------------

_WEEKDAYS: dict[str, int] = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
_WEEKDAY_RE = "|".join(_WEEKDAYS)

# ---------------------------------------------------------------------------
# Time parsing
# ---------------------------------------------------------------------------

_TIME_AMPM_RE = re.compile(
    r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)$"
)
_TIME_24H_RE = re.compile(
    r"^(\d{1,2}):(\d{2})$"
)


def _parse_time(text: str) -> tuple[int, int] | None:
    """Return (hour, minute) from a time string, or None on failure."""
    t = text.strip().lower()

    if t == "noon":
        return (12, 0)
    if t == "midnight":
        return (0, 0)

    m = _TIME_AMPM_RE.match(t)
    if m:
        h = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) else 0
        ampm = m.group(3)
        if ampm == "pm" and h != 12:
            h += 12
        elif ampm == "am" and h == 12:
            h = 0
        if 0 <= h <= 23 and 0 <= minute <= 59:
            return (h, minute)
        return None

    m = _TIME_24H_RE.match(t)
    if m:
        h, minute = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= minute <= 59:
            return (h, minute)

    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse_fuzzy_datetime(text: str) -> datetime | None:
    """Parse a natural language datetime expression.

    Returns a timezone-aware datetime (local HA timezone) or None if the
    expression is not recognised.
    """
    raw = text.strip()
    t = raw.lower()
    now = dt_util.now()  # local timezone

    # -- "in X minutes / hours / days" --------------------------------------
    m = re.match(r"^in\s+(\d+)\s+(minutes?|hours?|days?)$", t)
    if m:
        n = int(m.group(1))
        unit = m.group(2).rstrip("s")
        if unit == "minute":
            return now + timedelta(minutes=n)
        if unit == "hour":
            return now + timedelta(hours=n)
        if unit == "day":
            return now + timedelta(days=n)

    # -- "noon" / "midnight" (standalone) -----------------------------------
    if t == "noon":
        candidate = now.replace(hour=12, minute=0, second=0, microsecond=0)
        return candidate if candidate > now else candidate + timedelta(days=1)

    if t == "midnight":
        # "midnight" by itself means the coming midnight (start of tomorrow)
        return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

    # -- Patterns with a date anchor + time ---------------------------------
    date_tag: str | None = None
    time_str: str | None = None

    # "tomorrow at <time>" or "<time> tomorrow"
    m = re.match(r"^tomorrow\s+at\s+(.+)$", t) or re.match(r"^(.+?)\s+tomorrow$", t)
    if m:
        date_tag = "tomorrow"
        time_str = m.group(1).strip()

    # "today at <time>" or "<time> today"
    if date_tag is None:
        m = re.match(r"^today\s+at\s+(.+)$", t) or re.match(r"^(.+?)\s+today$", t)
        if m:
            date_tag = "today"
            time_str = m.group(1).strip()

    # "next <weekday> at <time>" or "next <weekday>" (midnight implied)
    if date_tag is None:
        m = re.match(rf"^next\s+({_WEEKDAY_RE})\s+at\s+(.+)$", t)
        if m:
            date_tag = f"next_{m.group(1)}"
            time_str = m.group(2).strip()
        else:
            m = re.match(rf"^next\s+({_WEEKDAY_RE})$", t)
            if m:
                date_tag = f"next_{m.group(1)}"
                time_str = None

    # "<weekday> at <time>" or bare "<weekday>" (midnight implied)
    if date_tag is None:
        m = re.match(rf"^({_WEEKDAY_RE})\s+at\s+(.+)$", t)
        if m:
            date_tag = m.group(1)
            time_str = m.group(2).strip()
        else:
            m = re.match(rf"^({_WEEKDAY_RE})$", t)
            if m:
                date_tag = m.group(1)
                time_str = None

    # "at <time>" — next occurrence of that clock time (today or tomorrow if past)
    if date_tag is None:
        m = re.match(r"^at\s+(.+)$", t)
        if m:
            date_tag = "at_time"
            time_str = m.group(1).strip()

    # Bare time string (e.g. "9pm", "17:30") — next occurrence today or tomorrow
    if date_tag is None:
        if _parse_time(t) is not None:
            date_tag = "at_time"
            time_str = t

    if date_tag is None:
        return None

    # Resolve time portion (default to 00:00 if omitted)
    if time_str is None:
        hour, minute = 0, 0
    else:
        parsed = _parse_time(time_str)
        if parsed is None:
            return None
        hour, minute = parsed

    # Build the base datetime at the resolved time on today's date
    base = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if date_tag == "today":
        return base

    if date_tag == "tomorrow":
        return base + timedelta(days=1)

    if date_tag == "at_time":
        # Next occurrence: today if still in the future, otherwise tomorrow
        return base if base > now else base + timedelta(days=1)

    # Weekday resolution
    weekday_name = date_tag.removeprefix("next_")
    target_wd = _WEEKDAYS.get(weekday_name)
    if target_wd is None:
        return None

    days_ahead = (target_wd - now.weekday()) % 7

    if date_tag.startswith("next_"):
        # "next monday" always jumps at least to the coming Monday
        if days_ahead == 0:
            days_ahead = 7
    else:
        # bare "monday" — use next occurrence; if today and time already passed, +7
        if days_ahead == 0 and base <= now:
            days_ahead = 7

    return base + timedelta(days=days_ahead)
