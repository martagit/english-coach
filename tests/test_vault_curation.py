from datetime import date
from english_coach.vault import ensure_phrase_note, read_curation_inventory, apply_curation
from english_coach.frontmatter import read_note, write_note


def _make(tmp_path, phrase, status=None, **extra):
    ensure_phrase_note(tmp_path, phrase, introduced=date(2026, 7, 1))
    if status or extra:
        p = tmp_path / "Phrases" / f"{phrase}.md"
        fm, body = read_note(p)
        if status:
            fm["status"] = status
        fm.update(extra)
        write_note(p, fm, body)


def test_inventory_lists_non_adopted_with_fields(tmp_path):
    _make(tmp_path, "park it", status="active", priority=1, theme="hedging",
          last_used=date(2026, 7, 5))
    _make(tmp_path, "hoist")
    _make(tmp_path, "done deal", status="adopted")
    inv = read_curation_inventory(tmp_path)
    names = [i["note_name"] for i in inv]
    assert "done deal" not in names  # adopted excluded
    park = next(i for i in inv if i["note_name"] == "park it")
    assert park["phrase"] == "park it"
    assert park["status"] == "active"
    assert park["priority"] == 1
    assert park["theme"] == "hedging"
    assert park["introduced"] == date(2026, 7, 1)
    assert park["last_used"] == date(2026, 7, 5)
    hoist = next(i for i in inv if i["note_name"] == "hoist")
    assert hoist["status"] == "backlog"
    assert hoist["priority"] is None and hoist["theme"] is None


def test_inventory_empty_vault(tmp_path):
    assert read_curation_inventory(tmp_path) == []


def test_apply_curation_writes_metadata_only(tmp_path):
    _make(tmp_path, "park it")
    p = tmp_path / "Phrases" / "park it.md"
    body_before = read_note(p)[1]
    n = apply_curation(tmp_path, {"park it": {"status": "active", "priority": 2, "theme": "hedging"}})
    assert n == 1
    fm, body = read_note(p)
    assert fm["status"] == "active" and fm["priority"] == 2 and fm["theme"] == "hedging"
    assert fm["phrase"] == "park it" and fm["reuse_count"] == 0  # untouched keys survive
    assert body == body_before  # body never rewritten


def test_apply_curation_skips_adopted_and_missing(tmp_path):
    _make(tmp_path, "done deal", status="adopted")
    n = apply_curation(tmp_path, {
        "done deal": {"status": "backlog", "priority": 5, "theme": "x"},
        "no such note": {"status": "active", "priority": 1, "theme": "y"},
    })
    assert n == 0
    fm, _ = read_note(tmp_path / "Phrases" / "done deal.md")
    assert fm["status"] == "adopted"


def test_apply_curation_counts_only_real_changes(tmp_path):
    _make(tmp_path, "park it", status="active", priority=1, theme="hedging")
    n = apply_curation(tmp_path, {"park it": {"status": "active", "priority": 1, "theme": "hedging"}})
    assert n == 0  # idempotent: same values -> no write, no count
