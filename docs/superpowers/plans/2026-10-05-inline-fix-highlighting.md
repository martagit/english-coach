# Inline Fix Highlighting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show every before → after correction as one sentence with the change marked inline (`paste ~~to~~ **into the** team channel`): in pattern notes, construction notes and all three daily tables. Reformat existing notes automatically, and refresh pattern Rules after a re-split.

**Architecture:** A new pure module `english_coach/fix_markup.py` (`render_fix`, `parse_fix`, `text_key`) owns the markup. `vault.py` gains `parse_example_line`, `reformat_example_lines`, `reformat_daily_body` and `reformat_notes`, and renders with `render_fix`. `constructions.py` reuses them. `coach.run` calls `reformat_notes` first (fail-soft). `resplit.py` reformats a daily note before re-linking, matches with `text_key`, and clears `enriched` on notes whose examples changed.

**Tech Stack:** Python ≥3.11, `difflib`, pytest, PyYAML frontmatter, `uv`.

**Spec:** `docs/superpowers/specs/2026-10-05-inline-fix-highlighting-design.md`

Deviations from the spec, found by prototyping against the real vault:
- **Comparison key:** examples are compared with `text_key` (all whitespace removed), not with whitespace collapsed to single spaces. Words that appear in both sentences take the corrected sentence's spacing, so `now+5mins` is parsed back as `now + 5mins`. An exact round trip of spacing is impossible; a round trip of the text without whitespace is exact.
- **Re-link:** the re-split's daily re-link first converts the note with `reformat_daily_body`, then reads only the new format. That replaces "support both header formats" with a single code path; `reformat_notes` would convert the note on the next run anyway.

## Global Constraints

- Run tests with `uv run --offline pytest -q` from `C:\Tools\english-coach-public`. Baseline: 332 passed, 3 skipped.
- Markup: `~~x~~` = only in what the learner wrote, `**x**` = only in the fix. Literal `*`/`~` in text are escaped as `\*`/`\~`.
- Fallback when the token similarity is below `0.5`: `~~before~~ → **after**`.
- Daily table headers: `| fix |`, `| pattern | fix |`, `| construction | fix |`. Table cells escape `|` via `vault._cell`.
- Date tags: `YYYY-MM-DD` → `MM-DD`; `YYYY-MM-DD_to_MM-DD` → `MM-DD–MM-DD` (en dash).
- Reformatting is deterministic, makes no Claude call, writes a file only if its content changed, and only touches example lines and the three daily tables. Every other line and the frontmatter stay unchanged.
- `coach.run` must not fail because reformatting failed.
- Commit after every task; message ends with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Never edit regex or backslash-heavy lines with `sed` (it mangled them during prototyping); use the editor.

## Review Focus

1. **The learner's own lines in a pattern or construction note**, e.g. a hand-written bullet below "Before → after" or in their own section. Reformatting must not touch them: only old `- ✗ … → ✓ …` lines are converted, and only inside the examples section. Tested in Task 3 (`test_reformat_example_lines_only_touches_old_lines_in_section`).
2. **Column-aligned daily tables** (the learner's vault has one: `| pattern           | before   | after |`) must be recognised and converted. Tested in Task 5 (`test_reformat_daily_body_converts_aligned_tables`).
3. **Escaped pipes in table cells** must survive render → cell → parse. Tested in Task 5 (`test_reformat_daily_body_keeps_escaped_pipes`) and Task 7.
4. **A note without frontmatter** must not gain an empty `{}` frontmatter block when reformatted. Tested in Task 6 (`test_reformat_notes_keeps_note_without_frontmatter`).
5. **The same example in the old and the new format** must be one example: appending a pair that already exists in the other format must not duplicate it. Tested in Task 3 (`test_append_dedupes_across_formats`).

---

### Task 1: `fix_markup` module

**Files:**
- Create: `english_coach/fix_markup.py`
- Test: `tests/test_fix_markup.py` (new)

**Interfaces:**
- Produces:
  - `render_fix(before: str, after: str) -> str`
  - `parse_fix(text: str) -> tuple[str, str]`, which returns whitespace-collapsed `(before, after)`
  - `text_key(text: str) -> str`: the text without escapes or any whitespace, used for comparisons

- [ ] **Step 1: Write the failing tests** (create `tests/test_fix_markup.py`)

```python
import pytest

from english_coach.fix_markup import parse_fix, render_fix, text_key

CASES = [
    ("prepare a list ... that I can paste to team channel",
     "prepare a list ... that I can paste into the team channel",
     "prepare a list ... that I can paste ~~to~~ **into the** team channel"),
    ("Draft an explanation what happened", "Draft an explanation of what happened",
     "Draft an explanation **of** what happened"),
    ("every day one ticket by component is created",
     "every day, one ticket per component is created",
     "every day**,** one ticket ~~by~~ **per** component is created"),
    ("it seems it was executed for the PROD", "it seems it was executed against PROD",
     "it seems it was executed ~~for the~~ **against** PROD"),
    ("generate a cron expression now+5mins, once a year. it utc",
     "generate a cron expression for now + 5 minutes, once a year, in UTC",
     "generate a cron expression **for** now + ~~5mins~~ **5 minutes**, once a year~~. it utc~~**, in UTC**"),
    ("So we go", "we go", "~~So~~ we go"),
    ("before x", "after y", "~~before x~~ → **after y**"),
    ("same", "same", "same"),
    ("a*b ~x", "a*b ~y z", "a\\*b \\~~~x~~ **y z**"),
]


@pytest.mark.parametrize("before,after,rendered", CASES)
def test_render_fix(before, after, rendered):
    assert render_fix(before, after) == rendered


@pytest.mark.parametrize("before,after,rendered", CASES)
def test_parse_fix_round_trips_ignoring_whitespace(before, after, rendered):
    b, a = parse_fix(rendered)
    assert (text_key(b), text_key(a)) == (text_key(before), text_key(after))


def test_parse_fix_of_plain_text_is_unchanged_pair():
    assert parse_fix("  just   text ") == ("just text", "just text")


def test_parse_fix_returns_collapsed_spacing():
    assert parse_fix("Draft an explanation **of** what happened") == (
        "Draft an explanation what happened", "Draft an explanation of what happened")


def test_text_key_ignores_whitespace_and_escapes():
    assert text_key("now + 5\\*mins") == text_key("now+5*mins") == "now+5*mins"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --offline pytest tests/test_fix_markup.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'english_coach.fix_markup'`

- [ ] **Step 3: Implement** (create `english_coach/fix_markup.py`; this is the prototype verified against the learner's vault)

```python
"""Inline before → after markup: ~~only in before~~ **only in after**.

render_fix shows a correction as one sentence with the change marked; parse_fix recovers
the (before, after) pair from it, so notes never need to store the two sentences separately.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

_TOKEN = re.compile(r"\s*(\w+(?:'\w+)*|[^\w\s])")
_FALLBACK = re.compile(r"^~~(?P<b>.+?)(?<!\\)~~ → \*\*(?P<a>.+)(?<!\\)\*\*$")
_DEL = re.compile(r"(?<!\\)~~(.+?)(?<!\\)~~")
_INS = re.compile(r"(?<!\\)\*\*(.+?)(?<!\\)\*\*")
_MIN_RATIO = 0.5


def _escape(text: str) -> str:
    return text.replace("*", r"\*").replace("~", r"\~")


def _unescape(text: str) -> str:
    return text.replace(r"\*", "*").replace(r"\~", "~")


def _norm(text: str) -> str:
    return " ".join(text.split())


def _tokens(text: str) -> list[tuple[str, str]]:
    """(leading whitespace, token) pairs."""
    return [(m.group(0)[:len(m.group(0)) - len(m.group(1))], m.group(1))
            for m in _TOKEN.finditer(text)]


def _join(toks: list[tuple[str, str]]) -> str:
    return "".join(ws + _escape(t) for ws, t in toks).strip()


def render_fix(before: str, after: str) -> str:
    """One sentence with the change marked: ~~removed~~ **added**."""
    before, after = _norm(before), _norm(after)
    if before == after:
        return _escape(after)
    a, b = _tokens(before), _tokens(after)
    sm = SequenceMatcher(None, [t for _, t in a], [t for _, t in b], autojunk=False)
    if sm.ratio() < _MIN_RATIO:  # mostly rewritten: inline marks would be noise
        return f"~~{_escape(before)}~~ → **{_escape(after)}**"
    out = []
    after_delete = None  # before-side whitespace to restore after a pure deletion
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            toks = list(b[j1:j2])
            if after_delete is not None:
                toks[0] = (toks[0][0] or after_delete, toks[0][1])
            out.append("".join(ws + _escape(t) for ws, t in toks))
            after_delete = None
            continue
        ws = b[j1][0] if j1 < j2 else a[i1][0]
        text = f"~~{_join(a[i1:i2])}~~" if i1 < i2 else ""
        if j1 < j2:
            ins = _join(b[j1:j2])
            gap = " " if text and re.match(r"\w", ins) else ""
            text += f"{gap}**{ins}**"
        out.append(ws + text)
        after_delete = a[i2][0] if (j1 == j2 and i2 < len(a)) else None
    return "".join(out).strip()


def text_key(text: str) -> str:
    """Comparison key for example text: spacing can't survive render → parse exactly
    (equal words take the corrected sentence's spacing), so compare without whitespace."""
    return "".join(_unescape(text).split())


def parse_fix(text: str) -> tuple[str, str]:
    """(before, after) from render_fix output, whitespace-collapsed."""
    text = text.strip()
    m = _FALLBACK.match(text)
    if m:
        return _norm(_unescape(m.group("b"))), _norm(_unescape(m.group("a")))
    before = _INS.sub("", _DEL.sub(r"\1", text))
    after = _DEL.sub("", _INS.sub(r"\1", text))
    return _norm(_unescape(before)), _norm(_unescape(after))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --offline pytest tests/test_fix_markup.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add english_coach/fix_markup.py tests/test_fix_markup.py
git commit -m "feat: inline before/after fix markup"
```

---

### Task 2: Short range date tags

**Files:**
- Modify: `english_coach/vault.py` (`_short_date`, around line 153)
- Test: `tests/test_vault_notes.py`

**Interfaces:**
- Produces: `vault._short_date(label: str) -> str`, which also shortens `YYYY-MM-DD_to_MM-DD` and passes already-short tags through unchanged.

- [ ] **Step 1: Write the failing test** (append to `tests/test_vault_notes.py`)

```python
def test_short_date_shortens_days_and_ranges():
    from english_coach.vault import _short_date
    assert _short_date("2026-09-23") == "09-23"
    assert _short_date("2026-09-16_to_09-22") == "09-16–09-22"
    assert _short_date("09-16–09-22") == "09-16–09-22"
    assert _short_date("") == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --offline pytest tests/test_vault_notes.py::test_short_date_shortens_days_and_ranges -q`
Expected: FAIL (`'2026-09-16_to_09-22' != '09-16–09-22'`)

- [ ] **Step 3: Implement.** Replace `_short_date` in `english_coach/vault.py` with:

```python
def _short_date(label: str) -> str:
    m = re.match(r'^\d{4}-(\d{2}-\d{2})(?:_to_(\d{2}-\d{2}))?$', label or "")
    if not m:
        return label or ""
    return f"{m.group(1)}–{m.group(2)}" if m.group(2) else m.group(1)
```

- [ ] **Step 4: Run the vault tests**

Run: `uv run --offline pytest tests/test_vault_notes.py tests/test_constructions.py -q`
Expected: all PASS except `test_append_pattern_examples_tagged_keeps_given_tags_and_dedupes`, which still expects the long tag (`_2026-09-16_to_09-22_`). Task 3 rewrites that assertion; leave it failing for now and record it in the ledger.

- [ ] **Step 5: Commit**

```bash
git add english_coach/vault.py tests/test_vault_notes.py
git commit -m "feat: shorten date-range tags"
```

---

### Task 3: Pattern notes in the inline format

**Files:**
- Modify: `english_coach/vault.py` (`_EX_RE` area, `_parse_pattern_examples`, `_render_pattern_note`, `append_pattern_examples_tagged`)
- Test: `tests/test_vault_notes.py`

**Interfaces:**
- Consumes: `render_fix`, `parse_fix`, `text_key` (Task 1); `_short_date` (Task 2).
- Produces:
  - `vault.parse_example_line(s: str) -> tuple[str, str, str] | None`: `(before, after, tag)` from an old `- ✗ b → ✓ a · _tag_` line or a new `- <fix> · _tag_` line.
  - `vault.example_line(before: str, after: str, tag: str) -> str`: `- <render_fix>  · _<short tag>_`.
  - `vault.reformat_example_lines(body: str, header: str) -> str`: converts old-format lines under `header` (until the next `#` heading) in place.

- [ ] **Step 1: Write the failing tests.** In `tests/test_vault_notes.py`, add `from english_coach.fix_markup import render_fix` to the imports and make these changes.

Replace the assertion in `test_ensure_pattern_note_and_append`:

```python
    assert "✗ run mcp server → ✓ run the MCP server" in body
```
with
```python
    assert f"- {render_fix('run mcp server', 'run the MCP server')}  · _07-05_" in body
```

In `test_append_pattern_examples_idempotent` (around line 79), replace the line that counts `"✗ a → ✓ the a"` with:

```python
    assert body.count(render_fix("a", "the a")) == 1  # deduped by pair, even across days
```

In `test_enrich_pattern_notes_migrates_old_table_and_sets_rule`, replace
```python
    assert "✗ run mcp server → ✓ run the MCP server" in body  # migrated to study-card list
```
with
```python
    assert render_fix("run mcp server", "run the MCP server") in body  # migrated to the list
```

In `test_append_pattern_examples_tagged_keeps_given_tags_and_dedupes`, replace the last assertion with:

```python
    fix = render_fix("check occurrence's status", "check the occurrence's status")
    assert f"- {fix}  · _09-16–09-22_" in body
```

Append these new tests:

```python
def test_parse_example_line_reads_both_formats():
    from english_coach.vault import parse_example_line
    assert parse_example_line("- ✗ a b → ✓ a the b  · _09-01_") == ("a b", "a the b", "09-01")
    assert parse_example_line("- a **the** b  · _09-01_") == ("a b", "a the b", "09-01")
    assert parse_example_line("- a **the** b") == ("a b", "a the b", "")
    assert parse_example_line("plain text") is None
    assert parse_example_line("- my own reminder: check every noun") is None  # no markup


def test_append_dedupes_across_formats(tmp_path):
    from english_coach.frontmatter import write_note
    from english_coach.vault import append_pattern_examples_tagged
    write_note(tmp_path / "Patterns" / "Articles.md", {"pattern": "Articles"},
               "# Articles\n\n**Rule:** r\n\n## Before → after\n- ✗ use mcp → ✓ use the MCP  · _09-01_")
    append_pattern_examples_tagged(tmp_path, "Articles", [("use  mcp", "use the MCP", "09-30")])
    _, body = read_note(tmp_path / "Patterns" / "Articles.md")
    assert body.count("use") == 2 and "09-30" not in body   # one example, re-rendered


def test_reformat_example_lines_only_touches_old_lines_in_section():
    from english_coach.vault import reformat_example_lines
    body = ("# Articles\n\n**Rule:** r\n\n## Before → after\n"
            "- ✗ use mcp server → ✓ use the mcp server  · _2026-09-16_to_09-22_\n"
            "- my own reminder: check every noun\n\n"
            "## My notes\n- ✗ keep → ✓ this one")
    out = reformat_example_lines(body, "## Before → after")
    assert "- use **the** mcp server  · _09-16–09-22_" in out
    assert "- my own reminder: check every noun" in out
    assert "## My notes\n- ✗ keep → ✓ this one" in out
    assert reformat_example_lines(out, "## Before → after") == out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --offline pytest tests/test_vault_notes.py -q`
Expected: FAIL. The new tests fail with `ImportError: cannot import name 'parse_example_line'`; the rewritten assertions fail because notes still render `✗ … → ✓ …`.

- [ ] **Step 3: Implement** in `english_coach/vault.py`.

Add to the imports at the top:

```python
from english_coach.fix_markup import parse_fix, render_fix, text_key
```

Below `_EX_RE`, add:

```python
_FIX_LINE_RE = re.compile(r'^- (?P<fix>.+?)(?:\s+·\s+_(?P<tag>.+?)_)?$')


def parse_example_line(s: str) -> tuple[str, str, str] | None:
    """(before, after, tag) from an example line in the old `✗ b → ✓ a` or the inline format."""
    m = _EX_RE.match(s)
    if m:
        return m.group("before").strip(), m.group("after").strip(), m.group("tag") or ""
    m = _FIX_LINE_RE.match(s)
    if m and ("~~" in m.group("fix") or "**" in m.group("fix")):  # a learner's own bullet isn't one
        b, a = parse_fix(m.group("fix"))
        return b, a, m.group("tag") or ""
    return None


def example_line(before: str, after: str, tag: str) -> str:
    t = _short_date(tag)
    return f"- {render_fix(before, after)}" + (f"  · _{t}_" if t else "")


def reformat_example_lines(body: str, header: str) -> str:
    """Convert old `- ✗ b → ✓ a` lines under `header` (until the next heading) to the inline
    format, in place. Every other line is left alone."""
    lines = body.split("\n")
    inside = False
    for i, line in enumerate(lines):
        s = line.strip()
        if s == header:
            inside = True
        elif s.startswith("#"):
            inside = False
        elif inside and (m := _EX_RE.match(s)):
            lines[i] = example_line(m.group("before").strip(), m.group("after").strip(),
                                    m.group("tag") or "")
    return "\n".join(lines)
```

Replace `_parse_pattern_examples` with:

```python
def _parse_pattern_examples(body: str) -> list[tuple[str, str, str]]:
    """Extract (before, after, date_tag) triples from a pattern note: old `✗ b → ✓ a` lines,
    inline-format lines under the examples header, or the old dated-table format.
    Deduplicated by (before, after), ignoring whitespace."""
    pairs: list[tuple[str, str, str]] = []
    seen: set = set()
    cur_tag = ""
    in_examples = False

    def add(b, a, t):
        k = (text_key(b), text_key(a))
        if k not in seen:
            seen.add(k)
            pairs.append((b, a, t))

    for line in body.splitlines():
        s = line.strip()
        if s == _EX_HEADER:
            in_examples = True
            continue
        if s.startswith("### "):
            cur_tag = _short_date(s[4:].strip())
            continue
        if s.startswith("#"):
            in_examples = False
            continue
        if _EX_RE.match(s) or (in_examples and s.startswith("- ")):
            parsed = parse_example_line(s)
            if parsed:
                add(*parsed)
            continue
        if s.startswith("|") and "---" not in s:
            cells = [c.strip() for c in s.strip("|").split("|")]
            if len(cells) == 2 and cells != ["before", "after"]:
                add(cells[0], cells[1], cur_tag)
    return pairs
```

In `_render_pattern_note`, replace the loop

```python
        for b, a, t in pairs:
            tag = f"  · _{t}_" if t else ""
            lines.append(f"- ✗ {b} → ✓ {a}{tag}")
```
with
```python
        lines += [example_line(b, a, t) for b, a, t in pairs]
```

In `append_pattern_examples_tagged`, compare by key:

```python
    seen = {(text_key(b), text_key(a)) for b, a, _ in pairs}
    changed = False
    for b, a, t in rows:
        b, a = b.strip(), a.strip()
        if (text_key(b), text_key(a)) not in seen:
            seen.add((text_key(b), text_key(a)))
            pairs.append((b, a, t))
            changed = True
```

- [ ] **Step 4: Run tests**

Run: `uv run --offline pytest tests/test_vault_notes.py tests/test_vault_daily.py tests/test_vault_curation.py tests/test_curator.py -q`
Expected: all PASS.

Note on `test_append_dedupes_across_formats`: the duplicate isn't appended, so `changed` stays False and the note isn't rewritten. The old-format line remains as the only example: "use" appears twice (before and after), and "09-30" is absent.

- [ ] **Step 5: Commit**

```bash
git add english_coach/vault.py tests/test_vault_notes.py
git commit -m "feat: pattern notes show fixes inline"
```

---

### Task 4: Construction "Try it next time" in the inline format

**Files:**
- Modify: `english_coach/constructions.py` (`_missed_line`, `parse_note_body`, `append_construction_evidence`; new `reformat_construction_body`)
- Test: `tests/test_constructions.py`

**Interfaces:**
- Consumes: `vault.parse_example_line`, `vault.example_line`, `vault.reformat_example_lines` (Task 3); `fix_markup.text_key`.
- Produces: `constructions.reformat_construction_body(body: str) -> str`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_constructions.py`)

```python
def test_missed_lines_render_inline_and_parse_back(tmp_path):
    from english_coach.fix_markup import render_fix
    c.ensure_construction_note(tmp_path, "unless", D, rule="r")
    c.append_construction_evidence(tmp_path, "unless", [], [("wait if not green", "wait unless green")],
                                   "2026-09-16_to_09-22")
    body = read_note(tmp_path / "Constructions" / "unless.md")[1]
    assert f"- {render_fix('wait if not green', 'wait unless green')}  · _09-16–09-22_" in body
    assert c.parse_note_body(body)["missed"] == [("wait if not green", "wait unless green", "09-16–09-22")]
    c.append_construction_evidence(tmp_path, "unless", [], [("wait  if not green", "wait unless green")],
                                   "2026-10-01")
    assert c.parse_note_body(read_note(tmp_path / "Constructions" / "unless.md")[1])["missed"] == [
        ("wait if not green", "wait unless green", "09-16–09-22")]


def test_reformat_construction_body_converts_only_try_it_section():
    body = c.render_note_body("unless", "r", ["ex"], [("I said it", "10-01")], [])
    body = body.replace("_(nothing yet)_", "- ✗ wait if not green → ✓ wait unless green  · _10-01_")
    body += "\n\n## My notes\n- ✗ mine → ✓ untouched"
    out = c.reformat_construction_body(body)
    assert "- wait ~~if not~~ **unless** green  · _10-01_" in out
    assert "- ✗ mine → ✓ untouched" in out and '- "I said it"' in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --offline pytest tests/test_constructions.py -q`
Expected: the two new tests FAIL (`- ✗ wait …` still rendered; `AttributeError: … 'reformat_construction_body'`).

- [ ] **Step 3: Implement** in `english_coach/constructions.py`.

Change the vault import to:

```python
from english_coach.fix_markup import text_key
from english_coach.vault import (
    _short_date, construction_key, example_line, note_name, parse_example_line,
    reformat_example_lines,
)
```

Replace `_missed_line`:

```python
def _missed_line(b: str, a: str, t: str) -> str:
    return example_line(b, a, t)
```

In `parse_note_body`, replace the `missed` branch:

```python
        elif section == "missed" and (m := _MISSED_RE.match(s)):
            missed.append((m.group("before").strip(), m.group("after").strip(), m.group("tag") or ""))
```
with
```python
        elif section == "missed" and s.startswith("- ") and (p := parse_example_line(s)):
            missed.append(p)
```

and delete the now-unused `_MISSED_RE` definition.

In `append_construction_evidence`, compare missed pairs by key:

```python
    seen_missed = {(text_key(b), text_key(a)) for b, a, _ in p["missed"]}
```
and
```python
        if b and a and (text_key(b), text_key(a)) not in seen_missed:
            seen_missed.add((text_key(b), text_key(a)))
            new_missed.append(_missed_line(b, a, tag))
```

Add after `append_construction_evidence`:

```python
def reformat_construction_body(body: str) -> str:
    """Convert old `✗ b → ✓ a` lines in "Try it next time" to the inline format, in place."""
    return reformat_example_lines(body, _MISSED)
```

- [ ] **Step 4: Run tests**

Run: `uv run --offline pytest tests/test_constructions.py tests/test_vault_daily.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add english_coach/constructions.py tests/test_constructions.py
git commit -m "feat: construction notes show fixes inline"
```

---

### Task 5: Daily tables in the inline format, plus the converter

**Files:**
- Modify: `english_coach/vault.py` (`render_daily_body`; new `reformat_daily_body`)
- Test: `tests/test_vault_daily.py`

**Interfaces:**
- Consumes: `render_fix` (Task 1), `_cell`.
- Produces: `vault.reformat_daily_body(body: str) -> str`, which converts the three old tables (header-driven, alignment-tolerant) to `| fix |`, `| pattern | fix |` and `| construction | fix |`.

- [ ] **Step 1: Write the failing tests.** In `tests/test_vault_daily.py`, add `from english_coach.fix_markup import render_fix`, then replace the assertion in `test_render_daily_body_construction_sections`:

```python
    assert "| [[unless]] | if not green then wait | wait unless it's green |" in body
```
with
```python
    fix = render_fix("if not green then wait", "wait unless it's green")
    assert "| construction | fix |" in body
    assert f"| [[unless]] | {fix} |" in body
```

Append:

```python
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
    body = "## Recurring patterns\n| pattern | before | after |\n| --- | --- | --- |\n| [[X]] | a \\| b c | a or b c |"
    row = reformat_daily_body(body).splitlines()[-1]
    cell = row.split(" | ", 1)[1].rsplit(" |", 1)[0]
    assert parse_fix(cell.replace("\\|", "|")) == ("a | b c", "a or b c")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --offline pytest tests/test_vault_daily.py -q`
Expected: FAIL (old headers still rendered; `ImportError: cannot import name 'reformat_daily_body'`).

- [ ] **Step 3: Implement** in `english_coach/vault.py`.

In `render_daily_body`, change the three tables.

Focus pattern:

```python
        lines.append("| fix |")
        lines.append("| --- |")
        for ex in fp.examples:
            lines.append(f"| {_cell(render_fix(ex.before, ex.after))} |")
```

Recurring patterns:

```python
        lines.append("| pattern | fix |")
        lines.append("| --- | --- |")
        for r in analysis.recurring:
            lines.append(f"| {_link(r.pattern)} | {_cell(render_fix(r.before, r.after))} |")
```

Try this construction:

```python
        lines.append("| construction | fix |")
        lines.append("| --- | --- |")
        for m in analysis.missed_constructions:
            lines.append(f"| {_link(m.construction)} | {_cell(render_fix(m.before, m.after))} |")
```

Add after `render_daily_body`:

```python
_CELL_SEP = re.compile(r'(?<!\\)\|')
# Old daily table header → (new header, number of leading cells kept as they are)
_OLD_TABLES = {("before", "after"): ("| fix |", 0),
               ("pattern", "before", "after"): ("| pattern | fix |", 1),
               ("construction", "you wrote", "try"): ("| construction | fix |", 1)}


def _cells(row: str) -> list[str]:
    return [c.strip() for c in _CELL_SEP.split(row.strip()[1:-1])]


def reformat_daily_body(body: str) -> str:
    """Convert old before/after daily tables (also column-aligned ones) to the inline-fix
    columns. Every other line is left alone; already-converted tables are unchanged."""
    out: list[str] = []
    keep = None  # leading cells kept as they are, while inside an old table
    for line in body.split("\n"):
        s = line.strip()
        is_row = s.startswith("|") and s.endswith("|") and len(s) > 1
        hdr = tuple(_cells(s)) if is_row else ()
        if hdr in _OLD_TABLES:
            new_header, keep = _OLD_TABLES[hdr]
            out.append(new_header)
            continue
        if keep is not None and is_row:
            cells = _cells(s)
            if all(set(c) <= set("-: ") for c in cells):
                out.append("| " + " | ".join(["---"] * (keep + 1)) + " |")
            elif len(cells) == keep + 2:
                b, a = (c.replace("\\|", "|") for c in cells[keep:])
                out.append("| " + " | ".join(cells[:keep] + [_cell(render_fix(b, a))]) + " |")
            else:
                out.append(line)
            continue
        keep = None
        out.append(line)
    return "\n".join(out)
```

- [ ] **Step 4: Run tests**

Run: `uv run --offline pytest tests/test_vault_daily.py tests/test_coach.py tests/test_cli_run.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add english_coach/vault.py tests/test_vault_daily.py
git commit -m "feat: daily tables show fixes inline"
```

---

### Task 6: Reformat existing notes on every run

**Files:**
- Modify: `english_coach/vault.py` (new `reformat_notes`), `english_coach/coach.py` (`run`, new `_run_reformat`)
- Test: `tests/test_vault_notes.py`, `tests/test_coach.py`

**Interfaces:**
- Consumes: `reformat_example_lines`, `_EX_HEADER`, `reformat_daily_body` (Tasks 3, 5); `constructions.reformat_construction_body` (Task 4).
- Produces: `vault.reformat_notes(vault: Path) -> int`, which returns the number of files written.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_vault_notes.py`:

```python
def _old_vault(tmp_path):
    from english_coach.frontmatter import write_note
    write_note(tmp_path / "Patterns" / "Articles.md", {"pattern": "Articles", "enriched": True},
               "# Articles\n\n**Rule:** r\n\n## Before → after\n- ✗ use mcp → ✓ use the mcp  · _2026-09-01_")
    write_note(tmp_path / "Daily" / "2026-09-01.md", {"from": "2026-09-01", "prompt_count": 1},
               "## Recurring patterns\n| pattern | before | after |\n| --- | --- | --- |\n"
               "| [[Articles]] | use mcp | use the mcp |")
    from english_coach import constructions as c
    c.ensure_construction_note(tmp_path, "unless", date(2026, 9, 1), rule="r")
    p = tmp_path / "Constructions" / "unless.md"
    p.write_text(p.read_text(encoding="utf-8").replace(
        "_(nothing yet)_", "- ✗ wait if not green → ✓ wait unless green  · _09-01_"), encoding="utf-8")


def test_reformat_notes_converts_every_kind_once(tmp_path):
    from english_coach.vault import reformat_notes
    _old_vault(tmp_path)
    assert reformat_notes(tmp_path) == 3
    fm, art = read_note(tmp_path / "Patterns" / "Articles.md")
    assert fm == {"pattern": "Articles", "enriched": True}
    assert "- use **the** mcp  · _09-01_" in art
    assert "| [[Articles]] | use **the** mcp |" in read_note(tmp_path / "Daily" / "2026-09-01.md")[1]
    assert "- wait ~~if not~~ **unless** green" in read_note(tmp_path / "Constructions" / "unless.md")[1]
    assert reformat_notes(tmp_path) == 0


def test_reformat_notes_keeps_note_without_frontmatter(tmp_path):
    from english_coach.vault import reformat_notes
    p = tmp_path / "Patterns" / "Loose.md"
    p.parent.mkdir(parents=True)
    p.write_text("# Loose\n\n## Before → after\n- ✗ a b → ✓ a the b\n", encoding="utf-8")
    assert reformat_notes(tmp_path) == 1
    text = p.read_text(encoding="utf-8")
    assert not text.startswith("---") and "- a **the** b" in text


def test_reformat_notes_empty_vault(tmp_path):
    from english_coach.vault import reformat_notes
    assert reformat_notes(tmp_path) == 0
```

Append to `tests/test_coach.py`:

```python
def test_run_reformats_old_notes_first(tmp_path):
    from english_coach.frontmatter import read_note, write_note
    write_note(tmp_path / "Patterns" / "Articles.md", {"pattern": "Articles"},
               "# Articles\n\n**Rule:** r\n\n## Before → after\n- ✗ use mcp → ✓ use the mcp")
    run(_cfg(tmp_path), FakeSource([]), FakeAnalyzer(_empty_analysis()), now_utc=NOW)
    assert "- use **the** mcp" in read_note(tmp_path / "Patterns" / "Articles.md")[1]


def test_run_survives_reformat_failure(tmp_path, monkeypatch, capsys):
    from english_coach import coach

    def boom(v):
        raise OSError("locked")

    monkeypatch.setattr(coach.vault, "reformat_notes", boom)
    prompts = [_p("Why we need here the reference?")]
    assert run(_cfg(tmp_path), FakeSource(prompts), FakeAnalyzer(_empty_analysis()),
               now_utc=NOW) == "wrote:2026-07-05"
    assert "Reformat failed (skipped): locked" in capsys.readouterr().err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --offline pytest tests/test_vault_notes.py -k reformat_notes tests/test_coach.py -q`
Expected: FAIL (`ImportError: cannot import name 'reformat_notes'`; `AttributeError` on `coach.vault.reformat_notes`).

- [ ] **Step 3: Implement**

In `english_coach/vault.py`, add after `read_known_patterns`:

```python
def reformat_notes(vault: Path) -> int:
    """Bring older notes to the inline before → after format: example lines in pattern and
    construction notes, and the before/after tables in daily notes. Deterministic and
    idempotent; writes only files that change. Returns the number of files written."""
    from english_coach import constructions  # local: constructions imports this module
    jobs = (("Patterns", lambda body: reformat_example_lines(body, _EX_HEADER)),
            ("Constructions", constructions.reformat_construction_body),
            ("Daily", reformat_daily_body))
    count = 0
    for folder, convert in jobs:
        d = Path(vault) / folder
        if not d.is_dir():
            continue
        for path in sorted(d.glob("*.md")):
            fm, body = read_note(path)
            new = convert(body)
            if new == body:
                continue
            if fm:
                write_note(path, fm, new)
            else:
                path.write_text(new.strip() + "\n", encoding="utf-8")
            count += 1
    return count
```

In `english_coach/coach.py`, make this the first statement of `run` (before `is_override = …`):

```python
    _run_reformat(config.vault_path)
```

and add next to `_run_enricher`:

```python
def _run_reformat(vault_path) -> None:
    """Fail-soft: bring older notes to the current before → after format."""
    try:
        n = vault.reformat_notes(vault_path)
        if n:
            print(f"Reformatted {n} note(s).")
    except Exception as exc:
        print(f"Reformat failed (skipped): {exc}", file=sys.stderr)
```

- [ ] **Step 4: Run tests**

Run: `uv run --offline pytest tests/test_vault_notes.py tests/test_coach.py tests/test_cli_run.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add english_coach/vault.py english_coach/coach.py tests/test_vault_notes.py tests/test_coach.py
git commit -m "feat: reformat older notes to inline fixes on every run"
```

---

### Task 7: Re-split works with the inline format and refreshes Rules

**Files:**
- Modify: `english_coach/resplit.py` (`_norm`, `_first_cell`, `_rewrite_body`, `rewrite_daily_links`, `apply_resplit`)
- Test: `tests/test_resplit.py`

**Interfaces:**
- Consumes: `vault.reformat_daily_body` (Task 5), `fix_markup.parse_fix`, `fix_markup.text_key`.
- Produces: `rewrite_daily_links(vault, moves)` accepts unnormalised `before` keys in `moves`; `apply_resplit` clears `enriched` on notes whose examples changed.

- [ ] **Step 1: Write the failing tests.** In `tests/test_resplit.py`, add `from english_coach.fix_markup import render_fix` to the imports and update the assertions that read old daily rows (they now see the converted tables):

In `test_rewrite_relinks_rows_and_focus_line`, replace the four row assertions with:

```python
    assert "| [[Articles]] | get familiar with" in body
    assert f"| Missing words | {render_fix('It total, 85k records', 'In total, 85k records')} |" in body
    assert f"| Missing words | {render_fix('something never planned', 'x')} |" in body
    assert f"| [[Articles]] | {render_fix('use mcp', 'use the MCP')} |" in body
```

In `test_rewrite_matches_escaped_pipe_cell`, replace the assertion with:

```python
    out = read_note(path)[1]
    assert "| [[Linking clauses]] | " in out and "[[Missing words]]" not in out
```

In `test_rewrite_matches_column_aligned_table_rows`, replace the assertion with:

```python
    assert "| [[Prepositions]] | " in read_note(path)[1]
```

In `test_apply_moves_examples_deletes_note_relinks_and_enriches`, replace

```python
    assert asked == ["Verb + preposition"]                      # Articles already enriched
```
with
```python
    assert asked == ["Articles", "Verb + preposition"]          # Articles gained an example
```
then
```python
    assert "✓ change anything in the framework  · _09-16_" in vp
```
with
```python
    assert f"- {render_fix('change anything the framework', 'change anything in the framework')}  · _09-16_" in vp
```
and
```python
    assert "| [[Articles]] | get familiar with a new spec |" in read_note(daily)[1]
```
with
```python
    assert "| [[Articles]] | get familiar with" in read_note(daily)[1]
```

In `test_apply_relinks_daily_notes_of_a_renamed_note`, replace `"| [[Articles]] | get familiar with a new spec |"` with `"| [[Articles]] | get familiar with"`.

In `test_apply_trims_partly_split_note_and_backs_it_up`, replace

```python
    assert "use mcp" in art and "get familiar with a new spec" in art and "a misfit" not in art
```
with
```python
    assert "use mcp" in art and "get familiar with" in art and "a misfit" not in art
```
then
```python
    assert "a misfit here" in read_note(v / "Patterns" / "Verb + preposition.md")[1]
```
with
```python
    assert "a misfit ~~here~~ **fixed**" in read_note(v / "Patterns" / "Verb + preposition.md")[1]
```
and the two daily-row assertions with:
```python
    assert "| [[Articles]] | ~~use mcp~~" in body
    assert "| [[Verb + preposition]] | a misfit ~~here~~ **fixed** |" in body
```

Append the new test:

```python
def test_apply_marks_changed_notes_for_a_new_rule(tmp_path):
    v = _vault_with_misfit(tmp_path)
    for name in ("Articles", "Missing words"):
        p = v / "Patterns" / f"{name}.md"
        fm, body = read_note(p)
        write_note(p, {**fm, "enriched": True}, body)
    ensure_pattern_note(v, "Linking clauses", "join clauses")
    p = v / "Patterns" / "Linking clauses.md"
    write_note(p, {**read_note(p)[0], "enriched": True}, read_note(p)[1])
    asked = []
    resplit.apply_resplit(v, resplit.plan_resplit(v, lambda items: PARTIAL),
                          lambda items: asked.extend(i["pattern"] for i in items) or {})
    assert asked == ["Articles", "Verb + preposition"]   # trimmed + received; new note
    assert read_note(v / "Patterns" / "Linking clauses.md")[0]["enriched"] is True  # untouched
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --offline pytest tests/test_resplit.py -q`
Expected: FAIL. `asked` lacks `Articles`; the daily rows aren't converted yet; and the new-format row assertions don't match.

- [ ] **Step 3: Implement** in `english_coach/resplit.py`.

Extend the imports:

```python
from english_coach.fix_markup import parse_fix, text_key
```
and add `reformat_daily_body` to the `english_coach.vault` import list.

Replace `_norm`:

```python
def _norm(text: str) -> str:
    """Matching key: whitespace- and escape-insensitive (see fix_markup.text_key)."""
    return text_key(str(text).replace("\\|", "|"))
```

Replace `_first_cell`:

```python
def _first_cell(row_rest: str) -> str:
    """The `before` of a converted daily row's fix cell, as a matching key."""
    cell = _CELL_SEP.split(row_rest)[0].strip().replace("\\|", "|")
    return _norm(parse_fix(cell)[0])
```

In `_rewrite_body`, convert first and skip the focus table's header and separator. Replace the start of the function

```python
def _rewrite_body(body: str, moves: dict) -> str:
    lines = body.split("\n")
```
with
```python
def _rewrite_body(body: str, moves: dict) -> str:
    lines = reformat_daily_body(body).split("\n")
```

and the focus-row branch

```python
            elif focus_at is not None and line.startswith("| "):
                cell = _first_cell(line[1:])
                if cell not in ("before", "---"):
                    focus_befores.append(cell)
```
with
```python
            elif focus_at is not None and line.startswith("| "):
                if line[1:].split("|")[0].strip() not in ("fix", "---"):
                    focus_befores.append(_first_cell(line[1:]))
```

In `rewrite_daily_links`, normalise the keys of `moves` once, right after the early return:

```python
    moves = {name: {_norm(k): v for k, v in m.items()} for name, m in moves.items()}
```

In `apply_resplit`, collect the notes whose examples change and clear their `enriched` flag before enriching:

- inside the per-move loop, replace
  ```python
            if not (folder / f"{note_name(m.target)}.md").exists():
                res.created += 1
  ```
  with
  ```python
            target_path = folder / f"{note_name(m.target)}.md"
            if target_path.exists():
                changed.add(target_path)
            else:
                res.created += 1
  ```
- declare `changed: set[Path] = set()` just before `for s in plan.splits:  # back up notes…`;
- in the trim branch, after `_trim(vault, s)`, add `changed.add(s.path)`;
- immediately before `res.enriched = enrich_pattern_notes(vault, enricher)`, add
  ```python
    for path in changed:
        _mark_for_new_rule(path)
  ```
- add the helper after `_trim`:
  ```python
def _mark_for_new_rule(path: Path) -> None:
    """A note whose examples changed gets its Rule rewritten by the next enrichment."""
    if not path.exists():
        return
    fm, body = read_note(path)
    if fm.get("enriched"):
        write_note(path, {**fm, "enriched": False}, body)
  ```

- [ ] **Step 4: Run the full suite**

Run: `uv run --offline pytest -q`
Expected: all PASS (332 baseline + the new tests), 3 skipped.

- [ ] **Step 5: Commit**

```bash
git add english_coach/resplit.py tests/test_resplit.py
git commit -m "feat: re-split reads inline fixes and refreshes changed Rules"
```
