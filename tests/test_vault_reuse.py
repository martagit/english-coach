from datetime import date
from english_coach.vault import (
    ensure_phrase_note, write_daily_note, recompute_reuse, read_phrasebook, write_dashboard,
)
from english_coach.models import Window, Analysis
from english_coach.frontmatter import read_note, write_note
from datetime import datetime, timezone


def _empty_analysis(reused):
    return Analysis(wins=[], focus_pattern=None, recurring=[], new_phrases=[],
                    reused_phrases=reused, snapshot=[])


def _win(day):
    return Window(start_utc=datetime(2026, 7, day, tzinfo=timezone.utc),
                  end_utc=datetime(2026, 7, day + 1, tzinfo=timezone.utc),
                  days=[date(2026, 7, day)])


def test_recompute_reuse_counts_and_status(tmp_path):
    ensure_phrase_note(tmp_path, "park it", introduced=date(2026, 6, 30))
    for d in (3, 4, 5):
        write_daily_note(tmp_path, _win(d), prompt_count=1, analysis=_empty_analysis(["park it"]))
    recompute_reuse(tmp_path, adopted_threshold=3)
    fm, _ = read_note(tmp_path / "Phrases" / "park it.md")
    assert fm["reuse_count"] == 3
    assert fm["status"] == "adopted"
    assert fm["last_used"] == date(2026, 7, 5)


def test_recompute_is_idempotent(tmp_path):
    ensure_phrase_note(tmp_path, "park it", introduced=date(2026, 6, 30))
    write_daily_note(tmp_path, _win(5), prompt_count=1, analysis=_empty_analysis(["park it"]))
    recompute_reuse(tmp_path)
    recompute_reuse(tmp_path)  # second run must not double-count
    fm, _ = read_note(tmp_path / "Phrases" / "park it.md")
    assert fm["reuse_count"] == 1


def test_unused_phrase_stays_backlog_zero(tmp_path):
    ensure_phrase_note(tmp_path, "hoist", introduced=date(2026, 6, 30))
    recompute_reuse(tmp_path)
    fm, _ = read_note(tmp_path / "Phrases" / "hoist.md")
    assert fm["reuse_count"] == 0
    assert fm["status"] == "backlog"


def test_read_phrasebook(tmp_path):
    ensure_phrase_note(tmp_path, "park it", introduced=date(2026, 6, 30))
    book = read_phrasebook(tmp_path)
    assert any(p.phrase == "park it" and p.status == "backlog" for p in book)


def test_write_dashboard_has_lifecycle_sections(tmp_path):
    p = write_dashboard(tmp_path)
    assert p == tmp_path / "English Coaching.md"
    text = p.read_text(encoding="utf-8")
    assert "```dataview" in text
    assert 'FROM "Phrases"' in text
    assert "## Currently practicing" in text
    assert 'status = "active"' in text
    assert "## By theme" in text
    assert "GROUP BY theme" in text
    assert "## Backlog" in text
    assert 'status = "backlog"' in text
    assert "## Adopted" in text
    assert "## Recent days" in text


def test_recompute_preserves_active_status(tmp_path):
    ensure_phrase_note(tmp_path, "park it", introduced=date(2026, 6, 30))
    p = tmp_path / "Phrases" / "park it.md"
    fm, body = read_note(p)
    fm["status"] = "active"
    write_note(p, fm, body)
    recompute_reuse(tmp_path)
    fm, _ = read_note(p)
    assert fm["status"] == "active"  # curator's assignment survives


def test_recompute_never_demotes_adopted(tmp_path):
    ensure_phrase_note(tmp_path, "park it", introduced=date(2026, 6, 30))
    p = tmp_path / "Phrases" / "park it.md"
    fm, body = read_note(p)
    fm["status"] = "adopted"
    write_note(p, fm, body)
    recompute_reuse(tmp_path)  # zero reuses counted from Daily/
    fm, _ = read_note(p)
    assert fm["status"] == "adopted"


def test_recompute_migrates_legacy_learning_to_backlog(tmp_path):
    ensure_phrase_note(tmp_path, "hoist", introduced=date(2026, 6, 30))
    p = tmp_path / "Phrases" / "hoist.md"
    fm, body = read_note(p)
    fm["status"] = "learning"
    write_note(p, fm, body)
    recompute_reuse(tmp_path)
    fm, _ = read_note(p)
    assert fm["status"] == "backlog"
