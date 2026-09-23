from datetime import datetime, timezone, date
from english_coach.window import compute_window, note_basename


def _utc(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


def test_no_watermark_defaults_to_yesterday_only():
    # now = Mon 2026-07-06 05:00 UTC (07:00 Berlin). Yesterday = Sun 07-05.
    w = compute_window(now_utc=_utc(2026, 7, 6, 5), watermark=None, tz="Europe/Berlin")
    assert w.days == [date(2026, 7, 5)]
    assert not w.is_empty


def test_backfill_days_extends_start():
    w = compute_window(now_utc=_utc(2026, 7, 6, 5), watermark=None, tz="Europe/Berlin", backfill_days=3)
    assert w.days == [date(2026, 7, 3), date(2026, 7, 4), date(2026, 7, 5)]


def test_watermark_weekend_catchup():
    # Last covered end-of-Friday 07-03 (== 2026-07-03 21:59:59.999999 UTC-ish);
    # use start-of-Saturday UTC as the covered_through instant.
    wm = _utc(2026, 7, 3, 22)  # ~end of Fri 07-03 Berlin (CEST = UTC+2)
    w = compute_window(now_utc=_utc(2026, 7, 6, 5), watermark=wm, tz="Europe/Berlin")
    assert w.days == [date(2026, 7, 4), date(2026, 7, 5)]


def test_already_covered_is_empty():
    # Watermark already at end of yesterday (Sun 07-05 -> 07-05 21:59:59.999999 CEST).
    wm = _utc(2026, 7, 5, 22)
    w = compute_window(now_utc=_utc(2026, 7, 6, 5), watermark=wm, tz="Europe/Berlin")
    assert w.is_empty


def test_override_from_to():
    w = compute_window(
        now_utc=_utc(2026, 7, 6, 5), watermark=None, tz="Europe/Berlin",
        override_from=date(2026, 6, 30), override_to=date(2026, 7, 2),
    )
    assert w.days == [date(2026, 6, 30), date(2026, 7, 1), date(2026, 7, 2)]


def test_note_basename_single_and_span():
    assert note_basename([date(2026, 7, 5)]) == "2026-07-05"
    assert note_basename([date(2026, 7, 3), date(2026, 7, 4), date(2026, 7, 5)]) == "2026-07-03_to_07-05"


def test_default_excludes_today():
    # watermark at end of yesterday (07-05); now is 07-06 → nothing to do (today excluded)
    w = compute_window(now_utc=_utc(2026, 7, 6, 16), watermark=_utc(2026, 7, 5, 22), tz="Europe/Berlin")
    assert w.is_empty


def test_include_today_extends_window_to_now():
    now = _utc(2026, 7, 6, 16)  # 18:00 Berlin
    w = compute_window(now_utc=now, watermark=_utc(2026, 7, 5, 22),
                       tz="Europe/Berlin", include_today=True)
    assert date(2026, 7, 6) in w.days
    assert w.end_utc == now
    assert not w.is_empty
