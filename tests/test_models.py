# tests/test_models.py
from datetime import datetime, timezone, date
from english_coach.models import UserPrompt, Window, Analysis


def test_userprompt_holds_text_and_utc():
    p = UserPrompt(text="hello", timestamp_utc=datetime(2026, 7, 5, tzinfo=timezone.utc))
    assert p.text == "hello"
    assert p.timestamp_utc.tzinfo is timezone.utc


def test_window_is_empty_when_no_days():
    w = Window(
        start_utc=datetime(2026, 7, 5, tzinfo=timezone.utc),
        end_utc=datetime(2026, 7, 5, tzinfo=timezone.utc),
        days=[],
    )
    assert w.is_empty is True


def test_window_not_empty_with_days():
    w = Window(
        start_utc=datetime(2026, 7, 5, tzinfo=timezone.utc),
        end_utc=datetime(2026, 7, 6, tzinfo=timezone.utc),
        days=[date(2026, 7, 5)],
    )
    assert w.is_empty is False


def test_analysis_defaults_constructible():
    a = Analysis(wins=[], focus_pattern=None, recurring=[], new_phrases=[], reused_phrases=[], snapshot=[])
    assert a.wins == []
