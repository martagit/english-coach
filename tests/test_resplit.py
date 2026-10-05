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

    for bad in ("", 7):
        raw = {"Missing words": {**GOOD["Missing words"], "It total, 85k records": bad}}
        plan = resplit.plan_resplit(v, lambda items: raw)
        assert plan.splits == [] and plan.skipped[0][0] == "Missing words"


def test_plan_rejects_target_that_is_being_emptied(tmp_path):
    v = _vault(tmp_path)
    raw = {**GOOD, "Articles": {"use mcp": "Determiners"}}
    raw["Missing words"] = {**GOOD["Missing words"], "get familiar with a new spec": "Articles"}
    plan = resplit.plan_resplit(v, lambda items: raw)
    assert [s.pattern for s in plan.splits] == ["Articles"]
    assert plan.skipped == [("Missing words", "target is being emptied: Articles")]


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


from english_coach.frontmatter import read_note

DAILY = """## Wins
- [[park it]] — "see [[Missing words]] later"

## Focus pattern
**[[Missing words]]** — add the small words

| before | after |
| --- | --- |
| change anything the framework | change anything in the framework |
| get familiar with a new spec | get familiar with the new spec |
| Did I change anything the code | Did I change anything in the code |

## Recurring patterns
| pattern | before | after |
| --- | --- | --- |
| [[Articles]] | use mcp | use the MCP |
| [[Missing words]] | get familiar with a new spec | get familiar with the new spec |
| [[Missing words]] | It total, 85k records | In total, 85k records |
| [[Missing words]] | something never planned | x |

## Snapshot
- ok"""

MOVES = {"Missing words": {"change anything the framework": "Verb + preposition",
                           "Did I change anything the code": "Verb + preposition",
                           "get familiar with a new spec": "Articles",
                           "It total, 85k records": None}}


def _daily(tmp_path, body=DAILY, name="2026-09-24.md"):
    path = tmp_path / "Daily" / name
    write_note(path, {"from": "2026-09-24", "to": "2026-09-24", "prompt_count": 3}, body)
    return path


def test_rewrite_relinks_rows_and_focus_line(tmp_path):
    path = _daily(tmp_path)
    assert resplit.rewrite_daily_links(tmp_path, MOVES) == 1
    fm, body = read_note(path)
    assert fm == {"from": "2026-09-24", "to": "2026-09-24", "prompt_count": 3}
    assert "**[[Verb + preposition]]** — add the small words" in body   # 2 of 3 focus rows
    assert "| [[Articles]] | get familiar with a new spec |" in body
    assert "| Missing words | It total, 85k records |" in body           # dropped → plain
    assert "| Missing words | something never planned |" in body        # unmatched → plain
    assert "| [[Articles]] | use mcp | use the MCP |" in body


def test_rewrite_leaves_other_sections_alone(tmp_path):
    body = DAILY.replace("**[[Missing words]]**", "**[[Articles]]**")
    path = _daily(tmp_path, body)
    resplit.rewrite_daily_links(tmp_path, MOVES)
    _, out = read_note(path)
    assert '- [[park it]] — "see [[Missing words]] later"' in out
    assert "**[[Articles]]** — add the small words" in out


def test_rewrite_focus_tie_picks_first_in_table_and_none_maps_to_plain(tmp_path):
    tie = {"Missing words": {"change anything the framework": "Verb + preposition",
                             "get familiar with a new spec": "Articles",
                             "Did I change anything the code": None}}
    path = _daily(tmp_path)
    resplit.rewrite_daily_links(tmp_path, tie)
    assert "**[[Verb + preposition]]**" in read_note(path)[1]

    path2 = _daily(tmp_path, name="2026-09-25.md")
    resplit.rewrite_daily_links(tmp_path, {"Missing words": {}})
    assert "**Missing words** — add the small words" in read_note(path2)[1]


def test_rewrite_matches_escaped_pipe_cell(tmp_path):
    body = ("## Recurring patterns\n| pattern | before | after |\n| --- | --- | --- |\n"
            "| [[Missing words]] | a \| b  c | a or b c |")
    path = _daily(tmp_path, body)
    resplit.rewrite_daily_links(tmp_path, {"Missing words": {"a | b c": "Linking clauses"}})
    assert "| [[Linking clauses]] | a \| b  c |" in read_note(path)[1]


def test_rewrite_untouched_notes_are_not_written(tmp_path):
    path = _daily(tmp_path, "## Snapshot\n- ok")
    before = path.read_text(encoding="utf-8")
    assert resplit.rewrite_daily_links(tmp_path, MOVES) == 0
    assert path.read_text(encoding="utf-8") == before
    assert resplit.rewrite_daily_links(tmp_path / "nowhere", MOVES) == 0


def test_apply_moves_examples_deletes_note_relinks_and_enriches(tmp_path):
    v = _vault(tmp_path)
    write_note(v / "Patterns" / "Articles.md",
               {**read_note(v / "Patterns" / "Articles.md")[0], "enriched": True},
               read_note(v / "Patterns" / "Articles.md")[1])
    daily = _daily(v)
    plan = resplit.plan_resplit(v, lambda items: GOOD)
    asked = []

    def enricher(items):
        asked.extend(i["pattern"] for i in items)
        return {"Verb + preposition": {"rule": "Use in/into for containers."}}

    res = resplit.apply_resplit(v, plan, enricher)
    assert (res.notes_split, res.moved, res.dropped, res.created, res.dailies, res.enriched) == (1, 2, 1, 1, 1, 1)
    assert not (v / "Patterns" / "Missing words.md").exists()
    assert asked == ["Verb + preposition"]                      # Articles already enriched
    _, vp = read_note(v / "Patterns" / "Verb + preposition.md")
    assert "**Rule:** Use in/into for containers." in vp
    assert "✓ change anything in the framework  · _09-16_" in vp
    _, art = read_note(v / "Patterns" / "Articles.md")
    assert "**Rule:** use the" in art and "· _09-24_" in art and "use mcp" in art
    assert "It total" not in art and "It total" not in vp
    assert "| [[Articles]] | get familiar with a new spec |" in read_note(daily)[1]


def test_apply_leaves_skipped_and_kept_notes_alone(tmp_path):
    v = _vault(tmp_path)
    before = {p.name: p.read_text(encoding="utf-8") for p in (v / "Patterns").glob("*.md")}
    plan = resplit.plan_resplit(v, lambda items: {"Missing words": {}})   # incomplete → skipped
    res = resplit.apply_resplit(v, plan, lambda items: 1 / 0)
    assert res == resplit.ResplitResult()
    assert {p.name: p.read_text(encoding="utf-8") for p in (v / "Patterns").glob("*.md")} == before


def test_apply_with_empty_plan_writes_nothing(tmp_path):
    v = _vault(tmp_path)
    daily = _daily(v)
    snapshot = daily.read_text(encoding="utf-8")
    res = resplit.apply_resplit(v, resplit.plan_resplit(v, lambda items: {}), lambda items: 1 / 0)
    assert res == resplit.ResplitResult()
    assert (v / "Patterns" / "Missing words.md").exists()
    assert daily.read_text(encoding="utf-8") == snapshot


def test_apply_moves_broad_note_to_obsidian_trash_with_its_content(tmp_path):
    v = _vault(tmp_path)
    original = (v / "Patterns" / "Missing words.md").read_text(encoding="utf-8") + "\nMy own notes\n"
    (v / "Patterns" / "Missing words.md").write_text(original, encoding="utf-8")
    (v / ".trash").mkdir()
    (v / ".trash" / "Missing words.md").write_text("older", encoding="utf-8")
    resplit.apply_resplit(v, resplit.plan_resplit(v, lambda items: GOOD), lambda items: {})
    assert not (v / "Patterns" / "Missing words.md").exists()
    assert (v / ".trash" / "Missing words.md").read_text(encoding="utf-8") == "older"
    assert (v / ".trash" / "Missing words 1.md").read_text(encoding="utf-8") == original


def test_apply_keeps_broad_note_when_daily_rewrite_fails(tmp_path, monkeypatch):
    import pytest
    v = _vault(tmp_path)
    plan = resplit.plan_resplit(v, lambda items: GOOD)

    def boom(*a, **k):
        raise OSError("locked")

    monkeypatch.setattr(resplit, "rewrite_daily_links", boom)
    with pytest.raises(OSError):
        resplit.apply_resplit(v, plan, lambda items: {})
    assert (v / "Patterns" / "Missing words.md").exists()      # still there: re-run can finish
    assert (v / "Patterns" / "Verb + preposition.md").exists()  # targets written first


def test_apply_relinks_daily_notes_of_a_renamed_note(tmp_path):
    v = _vault(tmp_path)
    (v / "Patterns" / "Missing words.md").rename(v / "Patterns" / "Omissions.md")
    daily = _daily(v, DAILY.replace("[[Missing words]]", "[[Omissions]]"))
    resplit.apply_resplit(v, resplit.plan_resplit(v, lambda items: GOOD), lambda items: {})
    body = read_note(daily)[1]
    assert "[[Omissions]]" not in body.split("## Recurring patterns")[1]
    assert "| [[Articles]] | get familiar with a new spec |" in body


def _vault_with_misfit(tmp_path):
    v = _vault(tmp_path)
    append_pattern_examples_tagged(v, "Articles", [("a misfit here", "a misfit fixed", "09-02")])
    return v


PARTIAL = {"Articles": {"use mcp": "Articles", "a misfit here": "Verb + preposition"},
           "Missing words": {**GOOD["Missing words"]}}


def test_plan_lets_examples_stay_and_targets_partly_split_note(tmp_path):
    v = _vault_with_misfit(tmp_path)
    plan = resplit.plan_resplit(v, lambda items: PARTIAL)
    assert plan.skipped == []
    art = next(s for s in plan.splits if s.pattern == "Articles")
    assert [m.target for m in art.moves] == ["Articles", "Verb + preposition"]
    text = resplit.format_plan(plan, v)
    assert "Articles → split (1 stays)" in text
    assert '"use mcp"' not in text                         # staying examples aren't listed
    assert '"get familiar with a new spec" → Articles (existing)' in text


def test_plan_where_every_example_stays_is_kept(tmp_path):
    v = _vault(tmp_path)
    plan = resplit.plan_resplit(v, lambda items: {"Articles": {"use mcp": "articles"}})
    assert plan.splits == [] and "Articles" in plan.kept


def test_apply_trims_partly_split_note_and_backs_it_up(tmp_path):
    v = _vault_with_misfit(tmp_path)
    original = (v / "Patterns" / "Articles.md").read_text(encoding="utf-8")
    daily = _daily(v, DAILY.replace(
        "| [[Articles]] | use mcp | use the MCP |",
        "| [[Articles]] | use mcp | use the MCP |\n| [[Articles]] | a misfit here | a misfit fixed |"))
    res = resplit.apply_resplit(v, resplit.plan_resplit(v, lambda items: PARTIAL), lambda items: {})
    fm, art = read_note(v / "Patterns" / "Articles.md")
    assert fm["pattern"] == "Articles" and "**Rule:** use the" in art
    assert "use mcp" in art and "get familiar with a new spec" in art and "a misfit" not in art
    assert (v / ".trash" / "Articles.md").read_text(encoding="utf-8") == original
    assert not (v / "Patterns" / "Missing words.md").exists()
    assert "a misfit here" in read_note(v / "Patterns" / "Verb + preposition.md")[1]
    body = read_note(daily)[1]
    assert "| [[Articles]] | use mcp |" in body
    assert "| [[Verb + preposition]] | a misfit here |" in body
    assert (res.notes_split, res.moved, res.dropped) == (2, 3, 1)


def test_rewrite_matches_column_aligned_table_rows(tmp_path):
    body = ("## Recurring patterns\n| pattern           | before   | after |\n| --- | --- | --- |\n"
            "| [[Missing words]]      | do we seed anything directly to DB?    | into the DB |")
    path = _daily(tmp_path, body)
    resplit.rewrite_daily_links(tmp_path, {"Missing words": {"do we seed anything directly to DB?": "Prepositions"}})
    assert "| [[Prepositions]]      | do we seed" in read_note(path)[1]
