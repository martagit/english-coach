# Specific Pattern Names Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the analyzer from coining catch-all pattern names like "Missing words", and add `english-coach enrich --resplit [--apply]`, which splits existing broad pattern notes into one-rule notes and re-links old daily notes.

**Architecture:** A shared `PATTERN_NAMING_RULE` string in `analyzer.py` goes into both the daily analysis prompt and a new batched audit prompt (`build_pattern_resplit_prompt` / `resplit_patterns`). A new module `english_coach/resplit.py` owns the re-split: `plan_resplit` (read notes → audit → validated plan), `format_plan` (preview), `rewrite_daily_links` and `apply_resplit` (writes). `vault.py` gains one helper, `append_pattern_examples_tagged`, so moved examples keep their original date tag. `cli.py` wires up the flags.

**Tech Stack:** Python ≥3.11, pytest, PyYAML frontmatter, `uv`.

**Spec:** `docs/superpowers/specs/2026-10-05-specific-pattern-names-design.md`

Deviation from the spec: the re-split code lives in a new `english_coach/resplit.py` instead of `vault.py` (already 612 lines), following the `constructions.py` precedent. Behaviour is unchanged.

## Global Constraints

- Run tests with `uv run --offline pytest -q` from `C:\Tools\english-coach-public`. Baseline: 297 passed, 3 skipped.
- Nothing is written to the vault by `enrich --resplit` without `--apply`.
- Moved examples keep their original date tag; no example of a split note is ever lost: a note whose plan doesn't cover every example is left untouched and reported.
- `target: null` means drop. A target equal to the note's own name, or to another note being split, invalidates that note's plan (note skipped).
- Dropped or unmatched daily-note rows become plain text, not links. Daily-note frontmatter is never changed.
- Every prompt the coach sends must start with one of `COACH_PROMPT_PREFIXES` (the resplit prompt starts with `PATTERN_PREAMBLE`).
- Prompts use `Profile`; no hard-coded "Polish" or ".NET" (`test_prompts_use_profile_not_hardcoded_learner`).
- `--resplit` runs on its own; it is not part of the default "enrich everything" run.
- Commit after every task; message ends with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. **The model re-types a `before` with different spacing or an escaped pipe** (`a \| b`). Matching must normalise whitespace and `\|` on both sides, otherwise every split looks "incomplete". Tested in Task 4 (`test_plan_matches_before_with_different_whitespace`) and Task 5 (`test_rewrite_matches_escaped_pipe_cell`).
2. **The model sends a target that differs from an existing note only by case** ("articles" vs `Articles`). It must land in the existing note, not create a near-duplicate (on Linux the filesystem would happily create both). Tested in Task 4 (`test_plan_canonicalises_target_case_to_existing_note`).
3. **The model omits a note, or returns notes that don't exist.** An omitted note counts as kept; unknown names are ignored. Tested in Task 4 (`test_plan_unknown_and_omitted_notes`).
4. **A daily note links the broad note in an unrelated section** (e.g. a focus line for a *different* pattern, or a Wins bullet). Only the Focus pattern line for the removed note and Recurring patterns rows change. Tested in Task 5 (`test_rewrite_leaves_other_sections_alone`).
5. **Running `--resplit --apply` twice.** The second run should be a no-op once the audit says "keep" (no deletes, no daily rewrites). Tested in Task 6 (`test_apply_with_empty_plan_writes_nothing`).

---

### Task 1: Naming rule in the analysis prompt

**Files:**
- Modify: `english_coach/analyzer.py` (add constant above `system_prompt`; replace the naming paragraph in `build_analysis_prompt`, currently lines 99-102)
- Test: `tests/test_analyzer.py`

**Interfaces:**
- Produces: `analyzer.PATTERN_NAMING_RULE: str` (used by Task 2).

- [ ] **Step 1: Write the failing test** (append to `tests/test_analyzer.py`)

```python
def test_prompt_names_patterns_by_rule_not_symptom():
    from english_coach.analyzer import PATTERN_NAMING_RULE
    text = build_analysis_prompt([UserPrompt("x y z", None)], [],
                                 known_patterns=[("Articles", "a/an/the usage")])
    assert PATTERN_NAMING_RULE in text
    assert "one sentence of advice must fix every example" in PATTERN_NAMING_RULE
    for bad in ("Missing words", "Word choice", "Grammar", "Wrong word", "Typos"):
        assert f'"{bad}"' in PATTERN_NAMING_RULE
    assert "only when the example truly fits that pattern's rule" in text
    assert "Typos and one-off vocabulary slips are not patterns" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --offline pytest tests/test_analyzer.py::test_prompt_names_patterns_by_rule_not_symptom -q`
Expected: FAIL with `ImportError: cannot import name 'PATTERN_NAMING_RULE'`

- [ ] **Step 3: Implement**

In `english_coach/analyzer.py`, above `def system_prompt(`:

```python
PATTERN_NAMING_RULE = (
    "Name the grammar rule, not the symptom: one sentence of advice must fix every example "
    "filed under the name (good: \"Articles\", \"Verb + preposition\", \"Relative pronouns\", "
    "\"Linking clauses\"; too broad: \"Missing words\", \"Word choice\", \"Grammar\", "
    "\"Wrong word\", \"Typos\")."
)
```

In `build_analysis_prompt`, replace these lines:

```python
        "For every 'pattern' field (in focus_pattern and recurring), use the EXACT short name "
        "from the 'Known recurring patterns' list above when it applies — copied verbatim, NOT "
        "expanded or paraphrased into a sentence. Only coin a new short 2-4 word name (e.g. "
        "\"Articles\", \"Question formation\") if the issue is genuinely not in that list. Put "
        "the detailed guidance in 'explanation', never in the name.\n"
```

with:

```python
        "For every 'pattern' field (in focus_pattern and recurring), use the EXACT short name "
        "from the 'Known recurring patterns' list above — copied verbatim, NOT expanded or "
        "paraphrased into a sentence — but only when the example truly fits that pattern's "
        "rule. Otherwise coin a new short 2-4 word name. "
        f"{PATTERN_NAMING_RULE} Put the detailed guidance in 'explanation', never in the "
        "name. Typos and one-off vocabulary slips are not patterns: leave them out of "
        "focus_pattern and recurring.\n"
```

- [ ] **Step 4: Run the analyzer tests**

Run: `uv run --offline pytest tests/test_analyzer.py tests/test_transcripts.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add english_coach/analyzer.py tests/test_analyzer.py
git commit -m "feat: name patterns by rule, not symptom"
```

---

### Task 2: Re-split audit prompt and parser

**Files:**
- Modify: `english_coach/analyzer.py` (add after `enrich_patterns`)
- Test: `tests/test_analyzer.py`, `tests/test_transcripts.py`

**Interfaces:**
- Consumes: `PATTERN_NAMING_RULE` (Task 1), `PATTERN_PREAMBLE`, `extract_json_object`, `run_claude_cli`.
- Produces:
  - `build_pattern_resplit_prompt(items: list[dict], profile: Profile = Profile()) -> str`, where `items` is `[{"pattern": str, "rule": str, "examples": [(before, after), ...]}]`
  - `resplit_patterns(items: list[dict], runner=None, profile: Profile = Profile()) -> dict[str, dict[str, object]]`, which returns `{pattern: {normalised_before: target}}` for **split** notes only. `target` is passed through raw (str, None or junk); Task 4 validates it. `normalised_before` is `" ".join(before.split())`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_analyzer.py`)

```python
def test_resplit_prompt_lists_every_note_and_example():
    from english_coach.analyzer import build_pattern_resplit_prompt, PATTERN_NAMING_RULE
    from english_coach.coach_prompts import COACH_PROMPT_PREFIXES
    from english_coach.profile import Profile
    items = [{"pattern": "Missing words", "rule": "add small words",
              "examples": [(f"before {i}", f"after {i}") for i in range(12)]},
             {"pattern": "Articles", "rule": "", "examples": []}]
    text = build_pattern_resplit_prompt(items, profile=Profile("German", "QA engineer"))
    assert text.startswith(COACH_PROMPT_PREFIXES)
    assert "a German-native QA engineer" in text
    assert PATTERN_NAMING_RULE in text
    assert "- Missing words" in text and "- Articles" in text
    assert '"before 11"' in text  # no cap: every example needs a target
    assert "add small words" in text


def test_resplit_patterns_parses_split_notes_only():
    from english_coach.analyzer import resplit_patterns
    reply = json.dumps({"notes": [
        {"pattern": "Articles", "action": "keep"},
        {"pattern": "Missing words", "action": "split", "examples": [
            {"before": "change  anything the framework", "target": "Verb + preposition"},
            {"before": "It total", "target": None},
            {"target": "x"},          # no before → ignored
            "junk",                   # not a dict → ignored
        ]},
        {"action": "split"},          # no pattern → ignored
    ]})
    out = resplit_patterns([{"pattern": "Missing words", "rule": "", "examples": []}],
                           runner=lambda p: reply)
    assert out == {"Missing words": {"change anything the framework": "Verb + preposition",
                                     "It total": None}}


def test_resplit_patterns_retries_once_and_empty_input():
    from english_coach.analyzer import resplit_patterns
    calls = []

    def runner(p):
        calls.append(p)
        return "sorry" if len(calls) == 1 else '{"notes": []}'

    assert resplit_patterns([{"pattern": "A", "rule": "", "examples": []}], runner=runner) == {}
    assert len(calls) == 2 and calls[1].endswith("Return ONLY the JSON object. No other text.")
    assert resplit_patterns([], runner=lambda p: 1 / 0) == {}
```

In `tests/test_transcripts.py::test_coach_own_prompts_are_skipped_even_from_another_cwd`, add to the imports `build_pattern_resplit_prompt` (from `english_coach.analyzer`) and add this entry to the `own` list:

```python
        build_pattern_resplit_prompt([{"pattern": "Articles", "rule": "", "examples": []}],
                                     profile=prof),
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --offline pytest tests/test_analyzer.py -k resplit tests/test_transcripts.py -q`
Expected: FAIL with `ImportError: cannot import name 'build_pattern_resplit_prompt'`

- [ ] **Step 3: Implement** (in `english_coach/analyzer.py`, after `enrich_patterns`)

```python
def build_pattern_resplit_prompt(items: list[dict], profile: Profile = Profile()) -> str:
    """items: [{"pattern": str, "rule": str, "examples": [(before, after), ...]}]."""
    blocks = []
    for it in items:
        exs = "\n".join(f'    - "{b}"  ->  "{a}"' for b, a in it.get("examples", [])) or "    (none)"
        blocks.append(f"- {it['pattern']}\n  rule: {it.get('rule', '') or '(none)'}\n  examples:\n{exs}")
    listing = "\n".join(blocks)
    return (
        f"{PATTERN_PREAMBLE} to {profile.learner()} and keep their mistake notes tidy.\n\n"
        f"Audit the grammar pattern notes below. {PATTERN_NAMING_RULE}\n"
        "For EACH note answer \"keep\" if all its examples share one rule. Otherwise answer "
        "\"split\" and give EVERY example a target: the name of another note below when the "
        "example truly fits its rule, a new short 2-4 word rule name, or null to drop it "
        "(typos and one-off vocabulary slips are not patterns). A split note's own name is "
        "never a target.\n\n"
        f"Notes:\n{listing}\n\n"
        "Output ONLY a single JSON object of exactly this shape — no prose, no markdown fences:\n"
        '{"notes":[{"pattern":"<note name verbatim>","action":"keep"},'
        '{"pattern":"<note name verbatim>","action":"split","examples":'
        '[{"before":"<before text verbatim>","target":"<pattern name or null>"}]}]}\n'
        "Include EVERY note; copy names and 'before' texts verbatim so they can be matched back."
    )


def resplit_patterns(items: list[dict], runner=None, profile: Profile = Profile()) -> dict:
    """Return {pattern: {before: target-or-None}} for the notes the model wants split.
    One batched call; targets are passed through unvalidated."""
    if not items:
        return {}
    runner = runner or (lambda p: run_claude_cli(p))
    prompt = build_pattern_resplit_prompt(items, profile)
    text = runner(prompt)
    try:
        payload = extract_json_object(text)
    except (ValueError, json.JSONDecodeError):
        text = runner(prompt + "\n\nReturn ONLY the JSON object. No other text.")
        payload = extract_json_object(text)
    out: dict = {}
    for n in payload.get("notes") or []:
        if not (isinstance(n, dict) and n.get("action") == "split"
                and isinstance(n.get("pattern"), str)):
            continue
        out[n["pattern"]] = {" ".join(ex["before"].split()): ex.get("target")
                             for ex in n.get("examples") or []
                             if isinstance(ex, dict) and isinstance(ex.get("before"), str)}
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --offline pytest tests/test_analyzer.py tests/test_transcripts.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add english_coach/analyzer.py tests/test_analyzer.py tests/test_transcripts.py
git commit -m "feat: batched audit prompt for re-splitting pattern notes"
```

---

### Task 3: Append pattern examples with their own date tags

**Files:**
- Modify: `english_coach/vault.py` (`append_pattern_examples`, around line 219)
- Test: `tests/test_vault_notes.py`

**Interfaces:**
- Produces: `vault.append_pattern_examples_tagged(vault: Path, pattern: str, rows: list[tuple[str, str, str]]) -> None`, where rows are `(before, after, tag)`. It dedupes by `(before, after)` against the note's existing examples and keeps the note's Rule. `append_pattern_examples` keeps its signature and delegates to it.

- [ ] **Step 1: Write the failing test** (append to `tests/test_vault_notes.py`)

```python
def test_append_pattern_examples_tagged_keeps_given_tags_and_dedupes(tmp_path):
    from english_coach.vault import append_pattern_examples_tagged
    ensure_pattern_note(tmp_path, "Articles", description="use the")
    append_pattern_examples(tmp_path, "Articles", [("run mcp server", "run the MCP server")], "2026-07-05")
    append_pattern_examples_tagged(tmp_path, "Articles", [
        ("run mcp server", "run the MCP server", "09-30"),   # duplicate → ignored
        ("check occurrence's status", "check the occurrence's status", "2026-09-16_to_09-22"),
    ])
    _, body = read_note(tmp_path / "Patterns" / "Articles.md")
    assert "**Rule:** use the" in body
    assert body.count("run mcp server") == 1 and "_07-05_" in body
    assert "✓ check the occurrence's status  · _2026-09-16_to_09-22_" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --offline pytest tests/test_vault_notes.py::test_append_pattern_examples_tagged_keeps_given_tags_and_dedupes -q`
Expected: FAIL with `ImportError: cannot import name 'append_pattern_examples_tagged'`

- [ ] **Step 3: Implement.** Replace the whole `append_pattern_examples` function in `english_coach/vault.py` with:

```python
def append_pattern_examples(vault: Path, pattern: str,
                            rows: list[tuple[str, str]], day_label: str) -> None:
    tag = _short_date(day_label)
    append_pattern_examples_tagged(vault, pattern, [(b, a, tag) for b, a in rows])


def append_pattern_examples_tagged(vault: Path, pattern: str,
                                   rows: list[tuple[str, str, str]]) -> None:
    """Add (before, after, date_tag) examples, skipping ones the note already has."""
    if not rows:
        return
    path = Path(vault) / "Patterns" / f"{note_name(pattern)}.md"
    fm, body = read_note(path)
    pairs = _parse_pattern_examples(body)
    seen = {(b, a) for b, a, _ in pairs}
    changed = False
    for b, a, t in rows:
        b, a = b.strip(), a.strip()
        if (b, a) not in seen:
            seen.add((b, a))
            pairs.append((b, a, t))
            changed = True
    if changed:
        write_note(path, fm, _render_pattern_note(pattern, _extract_rule(body), pairs))
```

- [ ] **Step 4: Run the vault tests**

Run: `uv run --offline pytest tests/test_vault_notes.py tests/test_vault_daily.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add english_coach/vault.py tests/test_vault_notes.py
git commit -m "refactor: append pattern examples with explicit date tags"
```

---

### Task 4: Build and validate a re-split plan, plus the preview

**Files:**
- Create: `english_coach/resplit.py`
- Test: `tests/test_resplit.py` (new)

**Interfaces:**
- Consumes: `vault.note_name`, `vault._extract_rule`, `vault._parse_pattern_examples`, `frontmatter.read_note`. `resplitter` has the shape of `analyzer.resplit_patterns` with `runner`/`profile` bound: `items -> {pattern: {normalised_before: target}}`.
- Produces (used by Tasks 5-7):

```python
@dataclass(frozen=True)
class Move:
    before: str
    after: str
    tag: str
    target: str | None          # None = drop

@dataclass(frozen=True)
class NoteSplit:
    pattern: str
    path: Path
    moves: list[Move]

@dataclass
class ResplitPlan:
    splits: list[NoteSplit]
    kept: list[str]
    skipped: list[tuple[str, str]]       # (pattern, reason)

def plan_resplit(vault: Path, resplitter) -> ResplitPlan
def format_plan(plan: ResplitPlan, vault: Path) -> str
def _norm(text: str) -> str              # unescape "\|", collapse whitespace
```

- [ ] **Step 1: Write the failing tests** (create `tests/test_resplit.py`)

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --offline pytest tests/test_resplit.py -q`
Expected: FAIL with `ImportError: cannot import name 'resplit'`

- [ ] **Step 3: Implement** (create `english_coach/resplit.py`)

```python
"""Split broad pattern notes ("Missing words") into one-rule notes.

plan_resplit asks the model to audit every pattern note and validates the answer;
apply_resplit moves the examples, deletes the broad notes and re-links old daily notes.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from english_coach.frontmatter import read_note
from english_coach.vault import _extract_rule, _parse_pattern_examples, note_name


@dataclass(frozen=True)
class Move:
    before: str
    after: str
    tag: str
    target: str | None  # None = drop


@dataclass(frozen=True)
class NoteSplit:
    pattern: str
    path: Path
    moves: list[Move]


@dataclass
class ResplitPlan:
    splits: list[NoteSplit]
    kept: list[str]
    skipped: list[tuple[str, str]]  # (pattern, reason)


def _norm(text: str) -> str:
    return " ".join(str(text).replace("\\|", "|").split())


def _key(name: str) -> str:
    return note_name(name).casefold()


def _read_notes(vault: Path) -> list[tuple[str, Path, str, list[tuple[str, str, str]]]]:
    folder = Path(vault) / "Patterns"
    if not folder.is_dir():
        return []
    out = []
    for path in sorted(folder.glob("*.md")):
        fm, body = read_note(path)
        out.append((fm.get("pattern") or path.stem, path, _extract_rule(body),
                    _parse_pattern_examples(body)))
    return out


def plan_resplit(vault: Path, resplitter) -> ResplitPlan:
    """`resplitter` takes [{"pattern","rule","examples":[(before, after)]}] and returns
    {pattern: {normalised_before: target-or-None}} for the notes to split."""
    notes = _read_notes(vault)
    plan = ResplitPlan([], [], [])
    if not notes:
        return plan
    raw = resplitter([{"pattern": p, "rule": r, "examples": [(b, a) for b, a, _ in ex]}
                      for p, _, r, ex in notes])
    existing = {_key(p): p for p, _, _, _ in notes}
    splitting = {_key(p) for p, _, _, _ in notes if p in raw}
    for pattern, path, _, examples in notes:
        if pattern not in raw:
            plan.kept.append(pattern)
            continue
        moves, reason = _moves(pattern, examples, raw[pattern], existing, splitting)
        if reason:
            plan.skipped.append((pattern, reason))
        else:
            plan.splits.append(NoteSplit(pattern, path, moves))
    return plan


def _moves(pattern, examples, answer, existing, splitting):
    if not examples:
        return [], "no examples"
    answer = {_norm(k): v for k, v in answer.items()}
    moves = []
    for b, a, t in examples:
        if _norm(b) not in answer:
            return [], "incomplete plan"
        target = answer[_norm(b)]
        if target is not None:
            if not isinstance(target, str) or not note_name(target):
                return [], f"invalid target: {target!r}"
            target = existing.get(_key(target), target.strip())
            if _key(target) == _key(pattern):
                return [], f"invalid target: {target}"
            if _key(target) in splitting:
                return [], f"target is itself being split: {target}"
        moves.append(Move(b, a, t, target))
    return moves, ""


def _short(text: str, width: int = 60) -> str:
    return text if len(text) <= width else text[:width - 3] + "…"


def format_plan(plan: ResplitPlan, vault: Path) -> str:
    folder = Path(vault) / "Patterns"
    lines = []
    for s in plan.splits:
        lines.append(f"{s.pattern} → split")
        for m in s.moves:
            if m.target is None:
                dest = "drop"
            else:
                state = "existing" if (folder / f"{note_name(m.target)}.md").exists() else "new"
                dest = f"{m.target} ({state})"
            lines.append(f'  "{_short(m.before)}" → {dest}')
    if plan.kept:
        lines.append("Keep: " + ", ".join(plan.kept))
    for pattern, reason in plan.skipped:
        lines.append(f"Skipped: {pattern} ({reason})")
    return "\n".join(lines) or "No pattern notes."
```

Note: `test_format_plan_truncates_long_before_and_lists_skipped` expects 57 `x` characters followed by `…`, i.e. `width - 3` characters plus the ellipsis.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --offline pytest tests/test_resplit.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add english_coach/resplit.py tests/test_resplit.py
git commit -m "feat: plan and preview re-splitting broad pattern notes"
```

---

### Task 5: Re-link old daily notes

**Files:**
- Modify: `english_coach/resplit.py`
- Test: `tests/test_resplit.py`

**Interfaces:**
- Consumes: `_norm` (Task 4), `vault.note_name`, `frontmatter.read_note/write_note`.
- Produces: `rewrite_daily_links(vault: Path, moves: dict[str, dict[str, str | None]]) -> int`. `moves` maps the removed note's **link name** (`note_name(pattern)`) to `{_norm(before): target-or-None}`. Returns the number of daily notes rewritten.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_resplit.py`)

```python
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
            "| [[Missing words]] | a \\| b  c | a or b c |")
    path = _daily(tmp_path, body)
    resplit.rewrite_daily_links(tmp_path, {"Missing words": {"a | b c": "Linking clauses"}})
    assert "| [[Linking clauses]] | a \\| b  c |" in read_note(path)[1]


def test_rewrite_untouched_notes_are_not_written(tmp_path):
    path = _daily(tmp_path, "## Snapshot\n- ok")
    before = path.read_text(encoding="utf-8")
    assert resplit.rewrite_daily_links(tmp_path, MOVES) == 0
    assert path.read_text(encoding="utf-8") == before
    assert resplit.rewrite_daily_links(tmp_path / "nowhere", MOVES) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --offline pytest tests/test_resplit.py -k rewrite -q`
Expected: FAIL with `AttributeError: module 'english_coach.resplit' has no attribute 'rewrite_daily_links'`

- [ ] **Step 3: Implement** (in `english_coach/resplit.py`: merge these imports into the existing ones, then add the code after `format_plan`)

```python
import re
from collections import Counter

from english_coach.frontmatter import read_note, write_note

_ROW_RE = re.compile(r'^\| \[\[(?P<name>[^\]]+)\]\] \|(?P<rest>.*)$')
_FOCUS_RE = re.compile(r'^\*\*\[\[(?P<name>[^\]]+)\]\]\*\*')
_CELL_SEP = re.compile(r'(?<!\\)\|')


def _first_cell(row_rest: str) -> str:
    return _norm(_CELL_SEP.split(row_rest)[0])


def _relink(line: str, name: str, target: str | None) -> str:
    return line.replace(f"[[{name}]]", f"[[{note_name(target)}]]" if target else name, 1)


def _rewrite_body(body: str, moves: dict) -> str:
    lines = body.split("\n")
    section = ""
    focus_at, focus_befores = None, []
    for i, line in enumerate(lines):
        if line.startswith("## "):
            section = line[3:].strip()
        elif section == "Focus pattern":
            m = _FOCUS_RE.match(line)
            if m and m.group("name") in moves:
                focus_at = i
            elif focus_at is not None and line.startswith("| "):
                cell = _first_cell(line[1:])
                if cell not in ("before", "---"):
                    focus_befores.append(cell)
        elif section == "Recurring patterns":
            m = _ROW_RE.match(line)
            if m and m.group("name") in moves:
                name = m.group("name")
                lines[i] = _relink(line, name, moves[name].get(_first_cell(m.group("rest"))))
    if focus_at is not None:
        name = _FOCUS_RE.match(lines[focus_at]).group("name")
        targets = [t for b in focus_befores if (t := moves[name].get(b))]
        top = Counter(targets).most_common(1)[0][0] if targets else None  # ties: first seen
        lines[focus_at] = _relink(lines[focus_at], name, top)
    return "\n".join(lines)


def rewrite_daily_links(vault: Path, moves: dict) -> int:
    """Point daily-note links at the notes each example moved to. `moves` maps a removed
    note's link name to {normalised before: target-or-None}. Returns notes rewritten."""
    folder = Path(vault) / "Daily"
    if not moves or not folder.is_dir():
        return 0
    count = 0
    for path in sorted(folder.glob("*.md")):
        fm, body = read_note(path)
        new = _rewrite_body(body, moves)
        if new != body:
            write_note(path, fm, new)
            count += 1
    return count
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --offline pytest tests/test_resplit.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add english_coach/resplit.py tests/test_resplit.py
git commit -m "feat: re-link daily notes after a pattern re-split"
```

---

### Task 6: Apply a re-split plan

**Files:**
- Modify: `english_coach/resplit.py`
- Test: `tests/test_resplit.py`

**Interfaces:**
- Consumes: `ResplitPlan`/`NoteSplit`/`Move`/`plan_resplit` (Task 4), `rewrite_daily_links` (Task 5), `vault.ensure_pattern_note`, `vault.append_pattern_examples_tagged` (Task 3), `vault.enrich_pattern_notes(vault, enricher) -> int`.
- Produces:

```python
@dataclass
class ResplitResult:
    notes_split: int = 0
    moved: int = 0
    dropped: int = 0
    created: int = 0
    dailies: int = 0
    enriched: int = 0

def apply_resplit(vault: Path, plan: ResplitPlan, enricher) -> ResplitResult
```

`enricher` has the shape of `analyzer.enrich_patterns` with `runner`/`profile` bound.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_resplit.py`)

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --offline pytest tests/test_resplit.py -k apply -q`
Expected: FAIL with `AttributeError: module 'english_coach.resplit' has no attribute 'apply_resplit'`

- [ ] **Step 3: Implement** (in `english_coach/resplit.py`: extend the `english_coach.vault` import with `append_pattern_examples_tagged, enrich_pattern_notes, ensure_pattern_note`, add `ResplitResult` after `ResplitPlan`, and add `apply_resplit` at the end)

```python
@dataclass
class ResplitResult:
    notes_split: int = 0
    moved: int = 0
    dropped: int = 0
    created: int = 0
    dailies: int = 0
    enriched: int = 0


def apply_resplit(vault: Path, plan: ResplitPlan, enricher) -> ResplitResult:
    """Move each split note's examples to their targets (keeping date tags), delete the
    note, re-link daily notes, then write Rules for the newly created notes."""
    res = ResplitResult()
    if not plan.splits:
        return res
    folder = Path(vault) / "Patterns"
    for s in plan.splits:
        rows: dict[str, list[tuple[str, str, str]]] = {}
        for m in s.moves:
            if m.target is None:
                res.dropped += 1
                continue
            if not (folder / f"{note_name(m.target)}.md").exists():
                res.created += 1
            ensure_pattern_note(vault, m.target)
            rows.setdefault(m.target, []).append((m.before, m.after, m.tag))
            res.moved += 1
        for target, items in rows.items():
            append_pattern_examples_tagged(vault, target, items)
        s.path.unlink()
        res.notes_split += 1
    res.dailies = rewrite_daily_links(
        vault, {note_name(s.pattern): {_norm(m.before): m.target for m in s.moves}
                for s in plan.splits})
    res.enriched = enrich_pattern_notes(vault, enricher)
    return res
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --offline pytest tests/test_resplit.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add english_coach/resplit.py tests/test_resplit.py
git commit -m "feat: apply a pattern re-split plan"
```

---

### Task 7: `enrich --resplit [--apply]` CLI and README

**Files:**
- Modify: `english_coach/cli.py` (imports; `cmd_enrich`; `build_parser` enrich subparser)
- Modify: `README.md:79` (commands table)
- Test: `tests/test_cli_run.py`

**Interfaces:**
- Consumes: `resplit.plan_resplit`, `resplit.format_plan`, `resplit.apply_resplit`, `ResplitResult` fields (Tasks 4-6); `analyzer.resplit_patterns` (Task 2); `analyzer.enrich_patterns`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_cli_run.py`)

```python
def _resplit_vault(cfg):
    from english_coach.vault import append_pattern_examples_tagged, ensure_pattern_note
    ensure_pattern_note(cfg.vault_path, "Missing words", "add words")
    append_pattern_examples_tagged(cfg.vault_path, "Missing words", [("It total", "In total", "09-23")])


def test_enrich_resplit_previews_without_writing(tmp_path, monkeypatch, capsys):
    import json
    paths, cfg = _setup(tmp_path)
    _resplit_vault(cfg)
    reply = json.dumps({"notes": [{"pattern": "Missing words", "action": "split",
                                   "examples": [{"before": "It total", "target": None}]}]})
    monkeypatch.setattr(cli, "make_runner", lambda config, p: (lambda prompt: reply))
    env = {"ENGLISH_COACH_CONFIG_DIR": str(paths.config_dir)}
    assert cli.main(["enrich", "--resplit"], env=env) == 0
    out = capsys.readouterr().out
    assert '"It total" → drop' in out and "--apply" in out
    assert (cfg.vault_path / "Patterns" / "Missing words.md").exists()

    assert cli.main(["enrich", "--resplit", "--apply"], env=env) == 0
    assert "Split 1 note(s): moved 0, dropped 1" in capsys.readouterr().out
    assert not (cfg.vault_path / "Patterns" / "Missing words.md").exists()


def test_enrich_resplit_runs_alone_and_apply_needs_resplit(tmp_path, monkeypatch, capsys):
    paths, cfg = _setup(tmp_path)
    seen = []
    monkeypatch.setattr(cli.vault, "enrich_phrase_notes", lambda *a, **k: seen.append("phrases") or 0)
    monkeypatch.setattr(cli.vault, "enrich_pattern_notes", lambda *a, **k: seen.append("patterns") or 0)
    monkeypatch.setattr(cli.constructions, "enrich_construction_notes",
                        lambda *a, **k: seen.append("constructions") or 0)
    monkeypatch.setattr(cli, "make_runner", lambda config, p: (lambda prompt: '{"notes": []}'))
    env = {"ENGLISH_COACH_CONFIG_DIR": str(paths.config_dir)}
    assert cli.main(["enrich", "--resplit"], env=env) == 0
    assert seen == []
    assert cli.main(["enrich", "--apply"], env=env) == 1
    assert "--apply only works with --resplit" in capsys.readouterr().err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --offline pytest tests/test_cli_run.py -k resplit -q`
Expected: FAIL (argparse error `unrecognized arguments: --resplit`, exit code 2 → `SystemExit`).

- [ ] **Step 3: Implement**

In `english_coach/cli.py`, change the imports:

```python
from english_coach import coach, constructions, resplit, scheduler, vault
from english_coach.analyzer import (
    ClaudeAnalyzer, ClaudeCliAnalyzer, enrich_constructions, enrich_patterns, enrich_phrases,
    resplit_patterns, run_claude_cli,
)
```

Add above `cmd_enrich`:

```python
def _cmd_resplit(args, config: Config, runner) -> int:
    prof = config.profile
    plan = resplit.plan_resplit(
        config.vault_path, lambda items: resplit_patterns(items, runner=runner, profile=prof))
    print(resplit.format_plan(plan, config.vault_path))
    if not args.apply:
        if plan.splits:
            print("Run again with --apply to write these changes.")
        return 0
    r = resplit.apply_resplit(
        config.vault_path, plan, lambda items: enrich_patterns(items, runner=runner, profile=prof))
    print(f"Split {r.notes_split} note(s): moved {r.moved}, dropped {r.dropped}, "
          f"created {r.created} note(s), re-linked {r.dailies} daily note(s), "
          f"wrote {r.enriched} rule(s).")
    return 0
```

In `cmd_enrich`, directly after `config = _load(paths, env, args)`:

```python
    if args.apply and not args.resplit:
        print("Error: --apply only works with --resplit.", file=sys.stderr)
        return 1
```

and as the first statement inside the existing `try:` block:

```python
        if args.resplit:
            return _cmd_resplit(args, config, runner)
```

In `build_parser`, after `enrich.add_argument("--force", ...)`:

```python
    enrich.add_argument("--resplit", action="store_true",
                        help="Split broad pattern notes into one-rule notes (preview only).")
    enrich.add_argument("--apply", action="store_true", help="With --resplit: write the changes.")
```

In `README.md`, add this row after the `english-coach enrich` row of the commands table:

```markdown
| `english-coach enrich --resplit` | Audits pattern notes and previews splitting broad ones (e.g. "Missing words") into one-rule notes; add `--apply` to move the examples, delete the broad note and re-link old daily notes. Safe to re-run any time. |
```

- [ ] **Step 4: Run the full suite**

Run: `uv run --offline pytest -q`
Expected: all PASS (baseline 297 + the new tests), 3 skipped.

- [ ] **Step 5: Commit**

```bash
git add english_coach/cli.py tests/test_cli_run.py README.md
git commit -m "feat: enrich --resplit [--apply] command"
```
