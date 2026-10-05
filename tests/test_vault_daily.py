from datetime import datetime, timezone, date
from english_coach.models import Window, Analysis, Win, FocusPattern, BeforeAfter, Recurring, NewPhrase
from english_coach.vault import note_name, render_daily_body, write_daily_note
from english_coach.frontmatter import read_note
from english_coach.fix_markup import render_fix


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
    fix = render_fix("if not green then wait", "wait unless it's green")
    assert "| construction | fix |" in body
    assert f"| [[unless]] | {fix} |" in body
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


def test_render_daily_body_uses_fix_columns():
    body = render_daily_body(_analysis())
    assert f"| fix |\n| --- |\n| {render_fix('run mcp server', 'run the MCP server')} |" in body
    assert "| pattern | fix |" in body
    assert f"| [[Question formation]] | {render_fix('Why we need here?', 'Why do we need it here?')} |" in body


OLD_DAILY = """## Focus pattern
**[[Articles]]** — use the

| before | after |
| --- | --- |
| run mcp server | run the MCP server |

## Recurring patterns
| pattern | before | after |
| --- | --- | --- |
| [[Question formation]] | Why we need here? | Why do we need it here? |

## Try this construction
| construction | you wrote | try |
| --- | --- | --- |
| [[unless]] | if not green then wait | wait unless it's green |

## Snapshot
- | not a table | row |"""


def test_reformat_daily_body_converts_all_three_tables_once():
    from english_coach.vault import reformat_daily_body
    out = reformat_daily_body(OLD_DAILY)
    assert f"| fix |\n| --- |\n| {render_fix('run mcp server', 'run the MCP server')} |" in out
    assert (f"| pattern | fix |\n| --- | --- |\n"
            f"| [[Question formation]] | {render_fix('Why we need here?', 'Why do we need it here?')} |") in out
    assert "| construction | fix |" in out
    assert "**[[Articles]]** — use the" in out and "- | not a table | row |" in out
    assert reformat_daily_body(out) == out


def test_reformat_daily_body_converts_aligned_tables():
    from english_coach.vault import reformat_daily_body
    body = ("## Recurring patterns\n| pattern           | before      | after |\n"
            "| ----------------- | ----------- | ----- |\n"
            "| [[Missing words]]      | do we seed to DB?    | do we seed into the DB? |")
    out = reformat_daily_body(body)
    assert f"| [[Missing words]] | {render_fix('do we seed to DB?', 'do we seed into the DB?')} |" in out


def test_reformat_daily_body_keeps_escaped_pipes():
    from english_coach.vault import reformat_daily_body
    from english_coach.fix_markup import parse_fix
    body = "## Recurring patterns\n| pattern | before | after |\n| --- | --- | --- |\n| [[X]] | a \| b c | a or b c |"
    row = reformat_daily_body(body).splitlines()[-1]
    cell = row.split(" | ", 1)[1].rsplit(" |", 1)[0]
    assert parse_fix(cell.replace("\|", "|")) == ("a | b c", "a or b c")
