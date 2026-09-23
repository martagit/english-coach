from __future__ import annotations

from datetime import datetime, timedelta, date, time, timezone
from zoneinfo import ZoneInfo

from english_coach.models import Window


def _day_bounds_utc(d: date, zone: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(d, time.min, zone).astimezone(timezone.utc)
    end = datetime.combine(d, time.max, zone).astimezone(timezone.utc)
    return start, end


def compute_window(
    now_utc: datetime,
    watermark: datetime | None,
    tz: str,
    backfill_days: int = 1,
    override_from: date | None = None,
    override_to: date | None = None,
    include_today: bool = False,
) -> Window:
    zone = ZoneInfo(tz)

    if override_from and override_to:
        start_utc, _ = _day_bounds_utc(override_from, zone)
        _, end_utc = _day_bounds_utc(override_to, zone)
        end_date = override_to
    else:
        today = now_utc.astimezone(zone).date()
        if include_today:
            # Cover up to the current moment, so today's (partial) prompts count.
            end_date = today
            end_utc = now_utc
        else:
            # Only complete days: end at the end of yesterday.
            end_date = today - timedelta(days=1)
            _, end_utc = _day_bounds_utc(end_date, zone)
        if watermark is not None:
            start_utc = watermark
        else:
            first = end_date - timedelta(days=backfill_days - 1)
            start_utc, _ = _day_bounds_utc(first, zone)

    days: list[date] = []
    if start_utc < end_utc:
        d = end_date
        while True:
            d_start, d_end = _day_bounds_utc(d, zone)
            if d_end <= start_utc:
                break
            if d_start < end_utc:
                days.append(d)
            d -= timedelta(days=1)
        days.reverse()

    return Window(start_utc=start_utc, end_utc=end_utc, days=days)


def note_basename(days: list[date]) -> str:
    if len(days) <= 1:
        return days[0].isoformat()
    return f"{days[0].isoformat()}_to_{days[-1].strftime('%m-%d')}"
