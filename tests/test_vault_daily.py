from datetime import datetime, timezone, date
from english_coach.models import Window, Analysis, Win, FocusPattern, BeforeAfter, Recurring, NewPhrase
from english_coach.vault import note_name, render_daily_body, write_daily_note
from english_coach.frontmatter import read_note


def _analysis():
    return Analysis(
        wins=[Win(phrase="park it", quote="let's park it for now")],
        focus_pattern=FocusPattern(pattern="Articles", explanation="use the",
                                   examples=[BeforeAfter(before="run mcp server", after="run the MCP server")]),
        recurring=[Recurring(pattern="Question formation", before="Why we need here?", after="Why do we need it here?")],
        new_phrases=[NewPhrase(phrase="worth the churn", meaning="worth the disruption", example="is it worth the churn?")],
        reused_phrases=["park it"],
        snapshot=["Articles still the main gap.", "Good idiom reuse."],
    )


def test_note_name_strips_invalid_chars():
    assert note_name("is it worth the churn?") == "is it worth the churn"


def test_render_daily_body_has_sections_and_wikilinks():
    body = render_daily_body(_analysis())
    assert "## Wins" in body
    assert "## Focus pattern" in body
    assert "## Recurring patterns" in body
    assert "## New phrases" in body
    assert "## Snapshot" in body
    assert "[[park it]]" in body
    assert "[[Articles]]" in body


def test_write_daily_note_single_day(tmp_path):
    w = Window(start_utc=datetime(2026, 7, 5, tzinfo=timezone.utc),
               end_utc=datetime(2026, 7, 6, tzinfo=timezone.utc), days=[date(2026, 7, 5)])
    path = write_daily_note(tmp_path, w, prompt_count=7, analysis=_analysis())
    assert path == tmp_path / "Daily" / "2026-07-05.md"
    fm, _ = read_note(path)
    assert fm["from"] == date(2026, 7, 5)
    assert fm["to"] == date(2026, 7, 5)
    assert fm["prompt_count"] == 7
    assert fm["reused"] == ["park it"]


def test_write_daily_note_span(tmp_path):
    w = Window(start_utc=datetime(2026, 7, 3, tzinfo=timezone.utc),
               end_utc=datetime(2026, 7, 6, tzinfo=timezone.utc),
               days=[date(2026, 7, 3), date(2026, 7, 4), date(2026, 7, 5)])
    path = write_daily_note(tmp_path, w, prompt_count=3, analysis=_analysis())
    assert path.name == "2026-07-03_to_07-05.md"


from english_coach.models import MissedConstruction, NewConstruction


def _with_constructions():
    a = _analysis()
    return Analysis(**{**a.__dict__,
                       "construction_wins": [Win("be supposed to", "Isn't it supposed to retry?"),
                                             Win("be supposed to", "It's supposed to be cached.")],
                       "missed_constructions": [MissedConstruction("unless", "if not green then wait",
                                                                   "wait unless it's green")],
                       "new_constructions": [NewConstruction("end up + -ing", "result", "We ended up reverting.")]})


def test_render_daily_body_construction_sections():
    body = render_daily_body(_with_constructions())
    assert "## Constructions used" in body
    assert '- [[be supposed to]] — "Isn\'t it supposed to retry?"' in body
    assert "## Try this construction" in body
    assert "| [[unless]] | if not green then wait | wait unless it's green |" in body
    assert "## New constructions" in body and "[[end up + -ing]]" in body
    assert body.index("## New phrases") < body.index("## Constructions used") < body.index("## Snapshot")


def test_render_daily_body_without_constructions_says_none():
    body = render_daily_body(_analysis())
    assert "## Constructions used\n- (none this time)" in body
    assert "## Try this construction\n(none this time)" in body
    assert "## New constructions" not in body


def test_daily_frontmatter_lists_constructions(tmp_path):
    w = Window(start_utc=datetime(2026, 7, 5, tzinfo=timezone.utc),
               end_utc=datetime(2026, 7, 6, tzinfo=timezone.utc), days=[date(2026, 7, 5)])
    fm, _ = read_note(write_daily_note(tmp_path, w, prompt_count=1, analysis=_with_constructions()))
    assert fm["constructions_used"] == ["be supposed to"]
    assert fm["constructions_missed"] == ["unless"]
