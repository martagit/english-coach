from __future__ import annotations

import re
from pathlib import Path
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
            f"unknown timezone {tz!r} (use an IANA name like Europe/London)") from exc
    return tz


def validate_vault_path(raw: str) -> Path:
    """Expand and resolve a vault folder answer, and make sure it can be created.

    Rejects the "~name" form: Python expands it to *another user's* home folder
    (e.g. "~english-coach-vault" -> C:/Users/english-coach-vault), which is never
    what a user typing a vault name means.
    """
    text = (raw or "").strip()
    if not text:
        raise ValueError("vault folder cannot be empty")
    if text.startswith("~") and len(text) > 1 and text[1] not in "/\\":
        raise ValueError(f"{text!r} would point to another user's home folder; "
                         f"did you mean ~/{text[1:]}?")
    vault = Path(text).expanduser().resolve()
    try:
        vault.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError(f"cannot create vault folder {vault}: {exc.strerror or exc}") from exc
    return vault
