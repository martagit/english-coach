from datetime import date

from english_coach import constructions as c
from english_coach.frontmatter import read_note
from english_coach.models import Analysis, MissedConstruction, NewConstruction, Win

D = date(2026, 10, 1)


def _analysis(**kw):
    base = dict(wins=[], focus_pattern=None, recurring=[], new_phrases=[],
                reused_phrases=[], snapshot=[])
    base.update(kw)
    return Analysis(**base)


def test_starter_list_is_valid():
    starter = c.load_starter()
    assert len(starter) >= 12
    names = [s["name"] for s in starter]
    assert len(set(names)) == len(names)
    for s in starter:
        assert s["rule"].strip() and s["example"].strip() and s["theme"].strip()
        assert s["priority"] in (1, 2, 3, 4, 5)


def test_seed_creates_notes_once_with_top_three_active(tmp_path):
    n = c.seed_constructions(tmp_path, introduced=D)
    notes = sorted((tmp_path / "Constructions").glob("*.md"))
    assert n == len(notes) == len(c.load_starter())
    statuses = [read_note(p)[0]["status"] for p in notes]
    assert statuses.count("active") == 3
    fm, body = read_note(tmp_path / "Constructions" / "be supposed to.md")
    assert fm["status"] == "active" and fm["construction"] == "be supposed to"
    assert fm["reuse_count"] == 0 and fm["missed_count"] == 0 and fm["tags"] == ["construction"]
    assert "**Rule:**" in body and "## You used it" in body and "## Try it next time" in body
    assert c.seed_constructions(tmp_path, introduced=D) == 0


def test_seed_does_not_resurrect_deleted_notes(tmp_path):
    c.seed_constructions(tmp_path, introduced=D)
    (tmp_path / "Constructions" / "unless.md").unlink()
    assert c.seed_constructions(tmp_path, introduced=D) == 0
    assert not (tmp_path / "Constructions" / "unless.md").exists()


def test_seed_respects_max_active(tmp_path):
    c.seed_constructions(tmp_path, introduced=D, max_active=1)
    statuses = [read_note(p)[0]["status"] for p in (tmp_path / "Constructions").glob("*.md")]
    assert statuses.count("active") == 1


def test_ensure_is_idempotent(tmp_path):
    p = c.ensure_construction_note(tmp_path, "unless", D, rule="r1")
    c.ensure_construction_note(tmp_path, "unless", D, rule="r2")
    assert "r1" in p.read_text(encoding="utf-8")


def test_body_round_trip():
    body = c.render_note_body("unless", "the rule", ["ex one"], [("I said it", "10-01")],
                              [("before x", "after y", "10-01")])
    p = c.parse_note_body(body)
    assert p == {"rule": "the rule", "examples": ["ex one"], "used": [("I said it", "10-01")],
                 "missed": [("before x", "after y", "10-01")]}


def test_evidence_is_appended_and_deduplicated(tmp_path):
    c.ensure_construction_note(tmp_path, "unless", D, rule="r")
    for _ in range(2):
        c.append_construction_evidence(tmp_path, "unless", ["Don't ping me unless it breaks"],
                                       [("if not x then y", "unless x, y")], "2026-10-01")
    p = c.parse_note_body(read_note(tmp_path / "Constructions" / "unless.md")[1])
    assert p["used"] == [("Don't ping me unless it breaks", "10-01")]
    assert p["missed"] == [("if not x then y", "unless x, y", "10-01")]


def test_evidence_for_unknown_note_is_ignored(tmp_path):
    c.append_construction_evidence(tmp_path, "nope", ["q"], [], "2026-10-01")
    assert not (tmp_path / "Constructions" / "nope.md").exists()


def test_apply_construction_notes(tmp_path):
    c.ensure_construction_note(tmp_path, "be supposed to", D, rule="r")
    a = _analysis(
        construction_wins=[Win("be supposed to", "Isn't it supposed to retry?")],
        missed_constructions=[MissedConstruction("be supposed to", "Why isn't it set?",
                                                 "Isn't it supposed to be set?")],
        new_constructions=[NewConstruction("end up + -ing", "result rule", "We ended up reverting.")])
    c.apply_construction_notes(tmp_path, a, D, "2026-10-01")
    p = c.parse_note_body(read_note(tmp_path / "Constructions" / "be supposed to.md")[1])
    assert p["used"][0][0] == "Isn't it supposed to retry?"
    assert p["missed"][0][:2] == ("Why isn't it set?", "Isn't it supposed to be set?")
    fm, _ = read_note(tmp_path / "Constructions" / "end up + -ing.md")
    assert fm["status"] == "backlog"


def test_read_constructions(tmp_path):
    c.ensure_construction_note(tmp_path, "unless", D, rule="the rule", status="active")
    c.ensure_construction_note(tmp_path, "as long as", D)
    info = {i.construction: i for i in c.read_constructions(tmp_path)}
    assert info["unless"].status == "active" and info["unless"].rule == "the rule"
    assert info["as long as"].rule == ""
    assert c.read_constructions(tmp_path / "missing") == []


def test_enrich_construction_notes_keeps_evidence_and_marks_enriched(tmp_path):
    c.ensure_construction_note(tmp_path, "unless", D, rule="old")
    c.append_construction_evidence(tmp_path, "unless", ["my quote"], [("b", "a")], "2026-10-01")
    seen = {}

    def enricher(items):
        seen["items"] = items
        return {"unless": {"rule": "new rule", "examples": ["e1", "e2", "e3"]}}

    assert c.enrich_construction_notes(tmp_path, enricher) == 1
    assert seen["items"] == [{"construction": "unless", "rule": "old", "your_quote": "my quote"}]
    fm, body = read_note(tmp_path / "Constructions" / "unless.md")
    p = c.parse_note_body(body)
    assert fm["enriched"] is True
    assert p["rule"] == "new rule" and p["examples"] == ["e1", "e2", "e3"]
    assert p["used"] == [("my quote", "10-01")] and p["missed"] == [("b", "a", "10-01")]
    assert c.enrich_construction_notes(tmp_path, lambda items: 1 / 0) == 0  # nothing left to do


def test_enricher_reply_with_ascii_dots_still_matches(tmp_path):
    c.ensure_construction_note(tmp_path, "What if we…?", D, rule="old")
    n = c.enrich_construction_notes(
        tmp_path, lambda items: {"What if we...?": {"rule": "new", "examples": ["e"]}})
    assert n == 1
    fm, body = read_note(tmp_path / "Constructions" / "What if we….md")
    assert fm["enriched"] is True and c.parse_note_body(body)["rule"] == "new"


def test_learner_notes_survive_evidence_and_enrichment(tmp_path):
    p = c.ensure_construction_note(tmp_path, "unless", D, rule="old")
    p.write_text(p.read_text(encoding="utf-8") + "\n## My notes\nremember the Slack thread\n",
                 encoding="utf-8")
    c.append_construction_evidence(tmp_path, "unless", ["q1"], [("b", "a")], "2026-10-01")
    c.enrich_construction_notes(tmp_path, lambda items: {"unless": {"rule": "new", "examples": ["e"]}})
    c.append_construction_evidence(tmp_path, "unless", ["q2"], [], "2026-10-02")
    body = read_note(p)[1]
    assert "## My notes\nremember the Slack thread" in body
    parsed = c.parse_note_body(body)
    assert parsed["rule"] == "new" and parsed["examples"] == ["e"]
    assert [q for q, _ in parsed["used"]] == ["q1", "q2"]
    assert parsed["missed"] == [("b", "a", "10-01")]
    assert "_(not yet)_" not in body and "_(nothing yet)_" not in body
