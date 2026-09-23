from datetime import date
from english_coach.models import Analysis, FocusPattern, BeforeAfter, Recurring, NewPhrase, Window
from english_coach.vault import (
    ensure_phrase_note, ensure_pattern_note, append_pattern_examples,
    seed_vault, write_quiet_note, apply_analysis_notes,
    read_phrase_entries, write_enriched_phrase_note, enrich_phrase_notes,
)
from english_coach.frontmatter import read_note
from datetime import datetime, timezone


def test_ensure_phrase_note_creates_with_frontmatter(tmp_path):
    p = ensure_phrase_note(tmp_path, "park it", introduced=date(2026, 6, 30),
                           meaning="defer", example="let's park it")
    fm, body = read_note(p)
    assert fm["introduced"] == date(2026, 6, 30)
    assert fm["status"] == "backlog"
    assert fm["reuse_count"] == 0
    assert fm["phrase"] == "park it"
    assert "defer" in body


def test_ensure_phrase_note_does_not_overwrite(tmp_path):
    ensure_phrase_note(tmp_path, "park it", introduced=date(2026, 6, 30), meaning="first")
    ensure_phrase_note(tmp_path, "park it", introduced=date(2026, 7, 1), meaning="second")
    fm, body = read_note(tmp_path / "Phrases" / "park it.md")
    assert fm["introduced"] == date(2026, 6, 30)  # unchanged
    assert "first" in body


def test_ensure_pattern_note_and_append(tmp_path):
    ensure_pattern_note(tmp_path, "Articles", description="a/an/the")
    append_pattern_examples(tmp_path, "Articles", [("run mcp server", "run the MCP server")], "2026-07-05")
    _, body = read_note(tmp_path / "Patterns" / "Articles.md")
    assert "✗ run mcp server → ✓ run the MCP server" in body
    assert "07-05" in body  # short date tag


def test_seed_vault_creates_patterns_and_phrases(tmp_path):
    seed_vault(tmp_path, introduced=date(2026, 6, 30))
    assert (tmp_path / "Patterns" / "Articles.md").exists()
    assert (tmp_path / "Phrases" / "park it.md").exists()
    assert (tmp_path / "Phrases" / "is it worth the churn.md").exists()  # sanitized


def test_write_quiet_note(tmp_path):
    w = Window(start_utc=datetime(2026, 7, 4, tzinfo=timezone.utc),
               end_utc=datetime(2026, 7, 6, tzinfo=timezone.utc),
               days=[date(2026, 7, 4), date(2026, 7, 5)])
    p = write_quiet_note(tmp_path, w)
    fm, body = read_note(p)
    assert fm["prompt_count"] == 0
    assert "quiet" in body.lower()


def test_apply_analysis_notes_creates_new_phrase(tmp_path):
    a = Analysis(wins=[], focus_pattern=FocusPattern("Articles", "use the",
                 [BeforeAfter("run mcp server", "run the MCP server")]),
                 recurring=[Recurring("Question formation", "why we need?", "why do we need it?")],
                 new_phrases=[NewPhrase("worth the churn", "worth the disruption", "is it worth the churn?")],
                 reused_phrases=[], snapshot=[])
    apply_analysis_notes(tmp_path, a, introduced=date(2026, 7, 5), day_label="2026-07-05")
    assert (tmp_path / "Phrases" / "worth the churn.md").exists()
    _, articles = read_note(tmp_path / "Patterns" / "Articles.md")
    assert "run the MCP server" in articles


def test_append_pattern_examples_idempotent(tmp_path):
    ensure_pattern_note(tmp_path, "Articles", "desc")
    append_pattern_examples(tmp_path, "Articles", [("a", "the a")], "2026-07-05")
    append_pattern_examples(tmp_path, "Articles", [("a", "the a")], "2026-07-06")
    _, body = read_note(tmp_path / "Patterns" / "Articles.md")
    assert body.count("✗ a → ✓ the a") == 1  # deduped by pair, even across days


def test_render_daily_body_escapes_pipes_in_tables():
    from english_coach.vault import render_daily_body
    a = Analysis(wins=[], focus_pattern=FocusPattern("Articles", "x",
                 [BeforeAfter("a || b", "the a | b")]),
                 recurring=[], new_phrases=[], reused_phrases=[], snapshot=["s"])
    body = render_daily_body(a)
    assert "a \\|\\| b" in body


def test_read_phrase_entries_detects_quote_and_unenriched(tmp_path):
    ensure_phrase_note(tmp_path, "park it", introduced=date(2026, 6, 30),
                       meaning="m", example="let's park it")
    entries = read_phrase_entries(tmp_path)
    e = next(x for x in entries if x["phrase"] == "park it")
    assert e["your_quote"] == "let's park it"
    assert e["enriched"] is False


def test_write_enriched_phrase_note_format_and_frontmatter(tmp_path):
    ensure_phrase_note(tmp_path, "park it", introduced=date(2026, 6, 30))
    write_enriched_phrase_note(tmp_path, "park it", "park it", "set aside for later",
                               ["Let's park it.", "Park the caching question."],
                               your_quote="let's park it")
    fm, body = read_note(tmp_path / "Phrases" / "park it.md")
    assert "**Definition:** set aside for later" in body
    assert "- Let's park it." in body
    assert '*(you said)* "let\'s park it"' in body
    assert fm["phrase"] == "park it"  # frontmatter preserved


def test_enrich_phrase_notes_fills_only_missing(tmp_path):
    ensure_phrase_note(tmp_path, "park it", introduced=date(2026, 6, 30))
    ensure_phrase_note(tmp_path, "hoist", introduced=date(2026, 6, 30))
    write_enriched_phrase_note(tmp_path, "hoist", "hoist", "lift out", ["x"], None)  # already enriched
    seen = {}

    def enricher(items):
        seen["phrases"] = [i["phrase"] for i in items]
        return {i["phrase"]: {"definition": "d", "examples": ["e1", "e2"]} for i in items}

    n = enrich_phrase_notes(tmp_path, enricher)
    assert n == 1
    assert seen["phrases"] == ["park it"]  # hoist skipped (already has a Definition)
    _, body = read_note(tmp_path / "Phrases" / "park it.md")
    assert "**Definition:** d" in body


def test_enrich_phrase_notes_force_redoes_all(tmp_path):
    ensure_phrase_note(tmp_path, "park it", introduced=date(2026, 6, 30))
    write_enriched_phrase_note(tmp_path, "park it", "park it", "old", ["old ex"], None)

    def enricher(items):
        return {i["phrase"]: {"definition": "new", "examples": ["new ex"]} for i in items}

    n = enrich_phrase_notes(tmp_path, enricher, force=True)
    assert n == 1
    _, body = read_note(tmp_path / "Phrases" / "park it.md")
    assert "**Definition:** new" in body


def test_collect_win_quotes_from_daily_notes(tmp_path):
    from english_coach.vault import collect_win_quotes, write_daily_note
    from english_coach.models import Analysis, Win, Window as _W
    a = Analysis(wins=[Win("park it", "Let's park it for now.")],
                 focus_pattern=None, recurring=[], new_phrases=[],
                 reused_phrases=["park it"], snapshot=[])
    w = _W(start_utc=datetime(2026, 7, 5, tzinfo=timezone.utc),
           end_utc=datetime(2026, 7, 6, tzinfo=timezone.utc), days=[date(2026, 7, 5)])
    write_daily_note(tmp_path, w, 1, a)
    q = collect_win_quotes(tmp_path)
    assert q["park it"] == "Let's park it for now."


def test_enrich_pattern_notes_migrates_old_table_and_sets_rule(tmp_path):
    from english_coach.vault import enrich_pattern_notes
    from english_coach.frontmatter import write_note
    # Old dated-table format note (pre-upgrade shape)
    old = ("# Articles\n\nold description\n\n## Examples\n\n### 2026-07-05\n\n"
           "| before | after |\n| --- | --- |\n| run mcp server | run the MCP server |\n")
    write_note(tmp_path / "Patterns" / "Articles.md", {"pattern": "Articles", "tags": ["pattern"]}, old)

    def enricher(items):
        assert items[0]["pattern"] == "Articles"
        assert ("run mcp server", "run the MCP server") in items[0]["examples"]  # parsed from old table
        return {"Articles": {"rule": "Use 'the' before a specific singular noun."}}

    n = enrich_pattern_notes(tmp_path, enricher)
    assert n == 1
    fm, body = read_note(tmp_path / "Patterns" / "Articles.md")
    assert fm["enriched"] is True
    assert "**Rule:** Use 'the' before a specific singular noun." in body
    assert "✗ run mcp server → ✓ run the MCP server" in body  # migrated to study-card list
    assert "| before | after |" not in body  # old table gone


def test_enrich_pattern_notes_skips_already_enriched(tmp_path):
    from english_coach.vault import enrich_pattern_notes
    from english_coach.frontmatter import write_note
    write_note(tmp_path / "Patterns" / "Articles.md",
               {"pattern": "Articles", "tags": ["pattern"], "enriched": True},
               "# Articles\n\n**Rule:** existing\n\n## Before → after\n_(no examples yet)_\n")
    called = {"n": 0}

    def enricher(items):
        called["n"] += 1
        return {}

    n = enrich_pattern_notes(tmp_path, enricher)
    assert n == 0
    assert called["n"] == 0  # nothing to do → enricher not called
