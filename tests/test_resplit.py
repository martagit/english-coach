from english_coach import resplit
from english_coach.frontmatter import write_note
from english_coach.vault import append_pattern_examples_tagged, ensure_pattern_note

MW = [("change anything the framework", "change anything in the framework", "09-16"),
      ("get familiar with a new spec", "get familiar with the new spec", "09-24"),
      ("It total, 85k records", "In total, 85k records", "09-23")]


def _vault(tmp_path):
    ensure_pattern_note(tmp_path, "Missing words", "add the small words")
    append_pattern_examples_tagged(tmp_path, "Missing words", MW)
    ensure_pattern_note(tmp_path, "Articles", "use the")
    append_pattern_examples_tagged(tmp_path, "Articles", [("use mcp", "use the MCP", "09-01")])
    return tmp_path


GOOD = {"Missing words": {"change anything the framework": "Verb + preposition",
                          "get familiar with a new spec": "Articles",
                          "It total, 85k records": None}}


def test_plan_splits_note_and_sends_all_notes_to_resplitter(tmp_path):
    seen = []
    plan = resplit.plan_resplit(_vault(tmp_path), lambda items: seen.extend(items) or GOOD)
    assert {i["pattern"] for i in seen} == {"Missing words", "Articles"}
    mw = next(i for i in seen if i["pattern"] == "Missing words")
    assert mw["rule"] == "add the small words" and len(mw["examples"]) == 3
    assert plan.kept == ["Articles"] and plan.skipped == []
    (s,) = plan.splits
    assert s.pattern == "Missing words" and s.path.name == "Missing words.md"
    assert [(m.before, m.tag, m.target) for m in s.moves] == [
        ("change anything the framework", "09-16", "Verb + preposition"),
        ("get familiar with a new spec", "09-24", "Articles"),
        ("It total, 85k records", "09-23", None)]


def test_plan_matches_before_with_different_whitespace(tmp_path):
    raw = {"Missing words": {"change  anything the\nframework": "Verb + preposition",
                             "get familiar with a new spec": "Articles",
                             "It total, 85k records": None}}
    plan = resplit.plan_resplit(_vault(tmp_path), lambda items: raw)
    assert len(plan.splits) == 1


def test_plan_canonicalises_target_case_to_existing_note(tmp_path):
    raw = {"Missing words": {**GOOD["Missing words"], "get familiar with a new spec": " articles "}}
    plan = resplit.plan_resplit(_vault(tmp_path), lambda items: raw)
    assert plan.splits[0].moves[1].target == "Articles"


def test_plan_skips_incomplete_or_invalid_plans(tmp_path):
    v = _vault(tmp_path)
    incomplete = {"Missing words": {"change anything the framework": "Verb + preposition"}}
    plan = resplit.plan_resplit(v, lambda items: incomplete)
    assert plan.splits == [] and plan.skipped == [("Missing words", "incomplete plan")]

    for bad in ("Missing words", "", 7):
        raw = {"Missing words": {**GOOD["Missing words"], "It total, 85k records": bad}}
        plan = resplit.plan_resplit(v, lambda items: raw)
        assert plan.splits == [] and plan.skipped[0][0] == "Missing words"


def test_plan_rejects_target_that_is_itself_being_split(tmp_path):
    v = _vault(tmp_path)
    raw = {**GOOD, "Articles": {"use mcp": "Determiners"}}
    raw["Missing words"] = {**GOOD["Missing words"], "get familiar with a new spec": "Articles"}
    plan = resplit.plan_resplit(v, lambda items: raw)
    assert [s.pattern for s in plan.splits] == ["Articles"]
    assert plan.skipped == [("Missing words", "target is itself being split: Articles")]


def test_plan_unknown_and_omitted_notes(tmp_path):
    plan = resplit.plan_resplit(_vault(tmp_path), lambda items: {"Ghost": {"x": "y"}})
    assert plan.splits == [] and plan.skipped == []
    assert sorted(plan.kept) == ["Articles", "Missing words"]


def test_plan_empty_vault_does_not_call_resplitter(tmp_path):
    plan = resplit.plan_resplit(tmp_path, lambda items: 1 / 0)
    assert plan.splits == [] and plan.kept == [] and plan.skipped == []


def test_plan_skips_note_without_examples(tmp_path):
    ensure_pattern_note(tmp_path, "Empty")
    plan = resplit.plan_resplit(tmp_path, lambda items: {"Empty": {}})
    assert plan.skipped == [("Empty", "no examples")]


def test_format_plan_shows_targets_new_existing_and_drop(tmp_path):
    v = _vault(tmp_path)
    plan = resplit.plan_resplit(v, lambda items: GOOD)
    text = resplit.format_plan(plan, v)
    assert "Missing words → split" in text
    assert '"change anything the framework" → Verb + preposition (new)' in text
    assert '"get familiar with a new spec" → Articles (existing)' in text
    assert '"It total, 85k records" → drop' in text
    assert "Keep: Articles" in text


def test_format_plan_truncates_long_before_and_lists_skipped(tmp_path):
    long = "x" * 80
    ensure_pattern_note(tmp_path, "Broad")
    append_pattern_examples_tagged(tmp_path, "Broad", [(long, "y", "09-01")])
    plan = resplit.ResplitPlan(
        splits=[resplit.NoteSplit("Broad", tmp_path / "Patterns" / "Broad.md",
                                  [resplit.Move(long, "y", "09-01", None)])],
        kept=[], skipped=[("Other", "incomplete plan")])
    text = resplit.format_plan(plan, tmp_path)
    assert '"' + "x" * 57 + '…" → drop' in text
    assert "Skipped: Other (incomplete plan)" in text
