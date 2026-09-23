from __future__ import annotations

import re
from zoneinfo import ZoneInfo

_TIME_RE = re.compile(r"^([0-1]?[0-9]|2[0-3]):([0-5][0-9])$")


def normalize_time(s: str) -> str:
    """Parse "H:MM" or "HH:MM" (00-23 : 00-59) and return "HH:MM"."""
    match = _TIME_RE.match(s.strip()) if isinstance(s, str) else None
    if not match:
        raise ValueError("time must be HH:MM, e.g. 07:00")
    hh, mm = match.groups()
    return f"{int(hh):02d}:{mm}"


def validate_timezone(tz: str) -> str:
    """Return `tz` if it is a valid IANA timezone name, else raise ValueError."""
    try:
        ZoneInfo(tz)
    except Exception as exc:
        raise ValueError(
            f"unknown timezone {tz!r} (use an IANA name like Europe/Warsaw)") from exc
    return tz
