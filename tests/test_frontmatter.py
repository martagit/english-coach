from datetime import date
from english_coach.frontmatter import parse_note, render_note, read_note, write_note


def test_parse_note_splits_frontmatter_and_body():
    text = "---\ndate: 2026-07-05\ncount: 3\n---\n\n# Body\ntext\n"
    fm, body = parse_note(text)
    assert fm["date"] == date(2026, 7, 5)
    assert fm["count"] == 3
    assert body.strip() == "# Body\ntext"


def test_parse_note_no_frontmatter_returns_empty_dict():
    fm, body = parse_note("just body\n")
    assert fm == {}
    assert body == "just body\n"


def test_render_note_roundtrips(tmp_path):
    fm = {"reuse_count": 4, "status": "adopted"}
    body = "meaning here"
    text = render_note(fm, body)
    fm2, body2 = parse_note(text)
    assert fm2 == fm
    assert body2.strip() == "meaning here"


def test_write_then_read_note(tmp_path):
    p = tmp_path / "Phrases" / "park it.md"
    write_note(p, {"reuse_count": 1}, "body")
    fm, body = read_note(p)
    assert fm["reuse_count"] == 1
    assert body.strip() == "body"
