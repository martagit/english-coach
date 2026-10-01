# Grammar Constructions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a third note kind, grammar *constructions* (everyday native structures the learner never uses), with the same active/backlog/adopted lifecycle as phrases, detected by the existing daily analysis call.

**Architecture:** A new `english_coach/constructions.py` owns the `Constructions/` notes (starter seeding, evidence, enrichment). The analyzer prompt/schema gain three optional keys. `vault.py` renders the new daily sections, counts reuse for both kinds, and its curation helpers take a folder parameter. The curator gets a `CurationKind` so one implementation curates both folders. `coach.run` / `cli.py` wire it together.

**Tech Stack:** Python ≥3.11, pytest, PyYAML frontmatter, `tomllib`, `importlib.resources`, hatchling, `uv`.

**Spec:** `docs/superpowers/specs/2026-10-01-grammar-constructions-design.md`

## Global Constraints

- Run tests with `uv run --offline pytest -q` from `C:\Tools\english-coach-public`. Baseline: 250 passed, 3 skipped.
- Folder name: `Constructions`. Frontmatter name key: `construction`. Tag: `construction`.
- Defaults: `max_active_constructions = 3`, `max_new_constructions = 1`, `construction_adopted_threshold = 5`; phrase defaults unchanged (`adopted_threshold = 3`, `max_active = 12`, `max_new_phrases = 2`).
- At most 3 `missed_constructions` per analysis; missed opportunities are only for `active` constructions and never reduce progress.
- The three new analyzer keys (`construction_wins`, `missed_constructions`, `new_constructions`) are optional: not in the tool schema's `required`, parsed with defaults.
- Every new prompt preamble must be in `COACH_PROMPT_PREFIXES`.
- Shipped starter list must contain no personal sentences; `tests/test_no_personal_data.py` scans it.
- Existing public signatures keep working with their current arguments (new params are keyword/defaulted).
- Commit after every task; message ends with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. **Existing vault with no `Constructions/` folder** (the author's real vault) — first `run` must seed the starter list and still write the daily note. Test in Task 7.
2. **Model returns construction names with different punctuation** (e.g. `What if we...` vs `What if we…?`, missing `?`) — matched via `note_name`, mapped back to the canonical name. Test in Task 4.
3. **Learner deletes a starter note they don't want** — next run must not resurrect it. Test in Task 2.
4. **Malformed construction items** (missing keys, non-dict, empty strings) — dropped individually, rest of the analysis kept. Test in Task 4.
5. **Same construction used several times in one day** — counts once toward adoption (distinct days), but each missed item counts toward `missed_count`. Test in Task 3.

---

## File Structure

| File | Responsibility |
|---|---|
| `english_coach/models.py` (modify) | `MissedConstruction`, `NewConstruction`, `ConstructionInfo`; three defaulted `Analysis` fields |
| `english_coach/config.py` (modify) | three new `[limits]` |
| `english_coach/assets/constructions.toml` (create) | generic starter list |
| `english_coach/constructions.py` (create) | construction note format, seeding, evidence, reading, note enrichment |
| `english_coach/vault.py` (modify) | daily sections + frontmatter, two-kind reuse recompute, dashboard, folder-aware curation I/O |
| `english_coach/analyzer.py` (modify) | prompt block, schema, CLI JSON shape, parsing, `enrich_constructions` |
| `english_coach/coach_prompts.py` (modify) | two new preambles |
| `english_coach/curator.py` (modify) | `CurationKind`, `PHRASES`, `CONSTRUCTIONS` |
| `english_coach/coach.py`, `cli.py`, `skeleton.py` (modify) | orchestration |
| `README.md` (modify) | docs |
| tests: `test_models.py`, `test_config.py`, `test_constructions.py` (create), `test_vault_daily.py`, `test_vault_reuse.py`, `test_analyzer.py`, `test_transcripts.py`, `test_curator.py`, `test_coach.py`, `test_cli_run.py`, `test_skeleton.py`, `test_no_personal_data.py` | |

---

### Task 1: Data model and config limits

**Files:**
- Modify: `english_coach/models.py`
- Modify: `english_coach/config.py`
- Test: `tests/test_models.py`, `tests/test_config.py`

**Interfaces:**
- Produces: `MissedConstruction(construction: str, before: str, after: str)`, `NewConstruction(construction: str, rule: str, example: str)`, `ConstructionInfo(construction: str, status: str, reuse_count: int, rule: str = "")`; `Analysis.construction_wins: list[Win]`, `Analysis.missed_constructions: list[MissedConstruction]`, `Analysis.new_constructions: list[NewConstruction]` (all default `[]`); `Config.max_active_constructions: int = 3`, `Config.max_new_constructions: int = 1`, `Config.construction_adopted_threshold: int = 5`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_models.py`:

```python
def test_analysis_construction_fields_default_empty():
    from english_coach.models import Analysis
    a = Analysis(wins=[], focus_pattern=None, recurring=[], new_phrases=[],
                 reused_phrases=[], snapshot=[])
    assert a.construction_wins == []
    assert a.missed_constructions == []
    assert a.new_constructions == []


def test_construction_dataclasses():
    from english_coach.models import ConstructionInfo, MissedConstruction, NewConstruction
    assert MissedConstruction("be supposed to", "b", "a").after == "a"
    assert NewConstruction("unless", "rule", "ex").rule == "rule"
    assert ConstructionInfo("unless", "active", 2).rule == ""
```

Append to `tests/test_config.py`:

```python
def test_construction_limits_default_and_round_trip(tmp_path):
    p = _paths(tmp_path)
    p.config_dir.mkdir(parents=True)
    p.config_file.write_text('vault_path = "~/v"\n', encoding="utf-8")
    cfg = load_config(p, env={})
    assert (cfg.max_active_constructions, cfg.max_new_constructions,
            cfg.construction_adopted_threshold) == (3, 1, 5)
    custom = Config(vault_path=tmp_path / "v", max_active_constructions=2,
                    max_new_constructions=0, construction_adopted_threshold=7)
    save_config(p, custom)
    assert load_config(p, env={}) == custom
```

And extend the existing parametrize on `test_...` at `tests/test_config.py:108` so the list reads:

```python
@pytest.mark.parametrize("key", ["adopted_threshold", "max_active", "max_new_phrases",
                                 "max_active_constructions", "max_new_constructions",
                                 "construction_adopted_threshold"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --offline pytest -q tests/test_models.py tests/test_config.py`
Expected: FAIL — `AttributeError: 'Analysis' object has no attribute 'construction_wins'`, `ImportError` for `ConstructionInfo`, `TypeError` for `max_active_constructions`.

- [ ] **Step 3: Implement**

In `english_coach/models.py` change the import to `from dataclasses import dataclass, field`, add above `Analysis`:

```python
@dataclass(frozen=True)
class MissedConstruction:
    construction: str
    before: str
    after: str


@dataclass(frozen=True)
class NewConstruction:
    construction: str
    rule: str
    example: str
```

Add at the end of `Analysis` (after `snapshot`):

```python
    construction_wins: list[Win] = field(default_factory=list)
    missed_constructions: list[MissedConstruction] = field(default_factory=list)
    new_constructions: list[NewConstruction] = field(default_factory=list)
```

Append at the end of the file:

```python
@dataclass(frozen=True)
class ConstructionInfo:
    construction: str
    status: str
    reuse_count: int
    rule: str = ""
```

In `english_coach/config.py`, add to `Config` after `max_new_phrases`:

```python
    max_active_constructions: int = 3
    max_new_constructions: int = 1
    construction_adopted_threshold: int = 5
```

In `load_config`, add after `max_new_phrases=limit("max_new_phrases", 2),`:

```python
        max_active_constructions=limit("max_active_constructions", 3),
        max_new_constructions=limit("max_new_constructions", 1),
        construction_adopted_threshold=limit("construction_adopted_threshold", 5),
```

In `save_config`, the `"limits"` dict becomes:

```python
        "limits": {"adopted_threshold": config.adopted_threshold,
                   "max_active": config.max_active,
                   "max_new_phrases": config.max_new_phrases,
                   "max_active_constructions": config.max_active_constructions,
                   "max_new_constructions": config.max_new_constructions,
                   "construction_adopted_threshold": config.construction_adopted_threshold},
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --offline pytest -q`
Expected: all pass (250 + new).

- [ ] **Step 5: Commit**

```bash
git add english_coach/models.py english_coach/config.py tests/test_models.py tests/test_config.py
git commit -m "feat: construction data model and config limits"
```

---

### Task 2: Starter list and construction notes

**Files:**
- Create: `english_coach/assets/constructions.toml`
- Create: `english_coach/constructions.py`
- Test: `tests/test_constructions.py` (create)

**Interfaces:**
- Consumes: `ConstructionInfo`, `Analysis`, `Win`, `MissedConstruction`, `NewConstruction` (Task 1); `vault.note_name(str) -> str`, `vault._short_date(str) -> str`; `frontmatter.read_note/write_note`.
- Produces (module `english_coach.constructions`):
  - `FOLDER = "Constructions"`
  - `load_starter() -> list[dict]` (keys `name, theme, priority, rule, example`)
  - `parse_note_body(body: str) -> dict` with keys `rule: str, examples: list[str], used: list[tuple[str, str]], missed: list[tuple[str, str, str]]`
  - `render_note_body(name, rule, examples, used, missed) -> str`
  - `ensure_construction_note(vault, name, introduced, rule="", example="", status="backlog", priority=None, theme=None) -> Path`
  - `seed_constructions(vault, introduced, max_active=3) -> int` (notes created)
  - `append_construction_evidence(vault, name, used_quotes: list[str], missed_pairs: list[tuple[str, str]], day_label: str) -> None`
  - `apply_construction_notes(vault, analysis: Analysis, introduced, day_label) -> None`
  - `read_constructions(vault) -> list[ConstructionInfo]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_constructions.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --offline pytest -q tests/test_constructions.py`
Expected: FAIL — `ImportError: cannot import name 'constructions'`.

- [ ] **Step 3: Create the starter list**

Create `english_coach/assets/constructions.toml` (generic examples only — no personal text):

```toml
# Starter grammar constructions seeded into a vault's Constructions/ folder.
# Generic on purpose: the learner's own sentences live only in their vault.

[[construction]]
name = "be supposed to"
theme = "expectations"
priority = 1
rule = "Use \"be supposed to + verb\" for what should happen according to a plan, a design or an agreement — often when it didn't."
example = "The job is supposed to retry three times, but it gave up after the first failure."

[[construction]]
name = "What if we…?"
theme = "suggesting"
priority = 1
rule = "Use \"What if we + past simple…?\" to float an idea without insisting on it."
example = "What if we moved the check into the handler instead?"

[[construction]]
name = "end up + -ing"
theme = "results"
priority = 1
rule = "Use \"end up + -ing\" (or \"end up with + noun\") for the result you reach after a process, often one you didn't plan."
example = "If we skip the review, we'll end up fixing the same bug twice."

[[construction]]
name = "cleft sentence (What I don't get is…)"
theme = "emphasis"
priority = 2
rule = "Start with \"What I don't get is…\", \"The thing is…\" or \"The problem is…\" to put the important part at the end of the sentence."
example = "What I don't get is why the second request succeeds."

[[construction]]
name = "which (linking a whole clause)"
theme = "linking ideas"
priority = 2
rule = "After a comma, \"which\" can refer to the whole previous clause, joining a cause and its effect in one sentence."
example = "The cache was never cleared, which meant every user saw stale data."

[[construction]]
name = "I'd rather"
theme = "preferences"
priority = 2
rule = "Use \"I'd rather + base verb\" for your own preference and \"I'd rather we + past simple\" for what you want others to do."
example = "I'd rather we kept this PR small and did the rename separately."

[[construction]]
name = "Is it worth + -ing?"
theme = "suggesting"
priority = 2
rule = "Use \"Is it worth + -ing?\" to ask whether the benefit justifies the effort."
example = "Is it worth adding a test for such a small change?"

[[construction]]
name = "should have + past participle"
theme = "hindsight"
priority = 2
rule = "Use \"should have / shouldn't have + past participle\" to say what would have been right in the past."
example = "We should have checked the logs before restarting the service."

[[construction]]
name = "unless"
theme = "conditions"
priority = 2
rule = "\"Unless\" means \"if not\"; it replaces a negative if-clause and never takes \"if\" after it."
example = "Don't merge it unless the pipeline is green."

[[construction]]
name = "How about + -ing?"
theme = "suggesting"
priority = 3
rule = "Use \"How about + -ing?\" or \"How about + noun?\" for a light, friendly suggestion."
example = "How about splitting the migration into two steps?"

[[construction]]
name = "as long as"
theme = "conditions"
priority = 3
rule = "Use \"as long as\" for a condition that must stay true for something else to be OK."
example = "You can refactor it as long as the public API stays the same."

[[construction]]
name = "in that case"
theme = "conditions"
priority = 3
rule = "Use \"in that case\" to react to what someone just said, and \"otherwise\" for what happens if a condition is not met."
example = "The flag is off in production? In that case, let's test it on staging first."

[[construction]]
name = "make sure (that)"
theme = "instructions"
priority = 3
rule = "Use \"make sure (that) + clause\" or \"make sure to + verb\" to ask someone to guarantee something, instead of \"check if\" or \"remember to\"."
example = "Make sure the migration runs before the new version starts."

[[construction]]
name = "confirmation tag (…, right?)"
theme = "softening"
priority = 3
rule = "Add \", right?\" after a statement to check that you understood correctly."
example = "The worker reads from the same queue, right?"

[[construction]]
name = "second conditional"
theme = "hypotheticals"
priority = 3
rule = "Use \"If + past simple, would + verb\" for imagined or unlikely situations."
example = "If we merged both PRs today, would the deployment break?"

[[construction]]
name = "get something working (get + object + -ing)"
theme = "results"
priority = 3
rule = "Use \"get + object + -ing / past participle / adjective\" for causing a change of state."
example = "I finally got the tests running locally."
```

- [ ] **Step 4: Create `english_coach/constructions.py`**

```python
"""Grammar constructions: everyday native structures the learner rarely uses.

Notes live in <vault>/Constructions/, one per construction, with the same
active/backlog/adopted lifecycle as phrases. Evidence (sentences the learner
wrote with it, and ones that could have used it) is appended by each run.
"""
from __future__ import annotations

import re
import tomllib
from importlib.resources import files
from pathlib import Path

from english_coach.frontmatter import read_note, write_note
from english_coach.models import Analysis, ConstructionInfo
from english_coach.vault import _short_date, note_name

FOLDER = "Constructions"
_RULE = "**Rule:**"
_NO_RULE = "(rule to be added)"
_EXAMPLES = "**Examples**"
_USED = "## You used it"
_MISSED = "## Try it next time"
_USED_RE = re.compile(r'^- "(?P<quote>.+)"(?:\s+·\s+_(?P<tag>.+?)_)?$')
_MISSED_RE = re.compile(r'^- ✗ (?P<before>.+?) → ✓ (?P<after>.+?)(?:\s+·\s+_(?P<tag>.+?)_)?$')


def _dir(vault) -> Path:
    return Path(vault) / FOLDER


def _path(vault, name: str) -> Path:
    return _dir(vault) / f"{note_name(name)}.md"


def _tag(t: str) -> str:
    return f"  · _{t}_" if t else ""


def load_starter() -> list[dict]:
    text = (files("english_coach") / "assets" / "constructions.toml").read_text(encoding="utf-8")
    return tomllib.loads(text)["construction"]


def render_note_body(name, rule, examples, used, missed) -> str:
    lines = [f"# {name}", "", f"{_RULE} {rule or _NO_RULE}", "", _EXAMPLES]
    lines += [f"- {e}" for e in examples] or ["_(no examples yet)_"]
    lines += ["", _USED]
    lines += [f'- "{q}"{_tag(t)}' for q, t in used] or ["_(not yet)_"]
    lines += ["", _MISSED]
    lines += [f"- ✗ {b} → ✓ {a}{_tag(t)}" for b, a, t in missed] or ["_(nothing yet)_"]
    return "\n".join(lines)


def parse_note_body(body: str) -> dict:
    rule, examples, used, missed = "", [], [], []
    section = None
    for line in body.splitlines():
        s = line.strip()
        if s.startswith(_RULE):
            rule = s[len(_RULE):].strip()
        elif s == _EXAMPLES:
            section = "examples"
        elif s == _USED:
            section = "used"
        elif s == _MISSED:
            section = "missed"
        elif s.startswith("#"):
            section = None
        elif section == "examples" and s.startswith("- "):
            examples.append(s[2:].strip())
        elif section == "used" and (m := _USED_RE.match(s)):
            used.append((m.group("quote"), m.group("tag") or ""))
        elif section == "missed" and (m := _MISSED_RE.match(s)):
            missed.append((m.group("before").strip(), m.group("after").strip(), m.group("tag") or ""))
    return {"rule": rule, "examples": examples, "used": used, "missed": missed}


def ensure_construction_note(vault, name: str, introduced, rule: str = "", example: str = "",
                             status: str = "backlog", priority: int | None = None,
                             theme: str | None = None) -> Path:
    path = _path(vault, name)
    if path.exists():
        return path
    fm = {"construction": name, "introduced": introduced, "status": status,
          "reuse_count": 0, "missed_count": 0, "tags": ["construction"]}
    if priority is not None:
        fm["priority"] = priority
    if theme:
        fm["theme"] = theme
    write_note(path, fm, render_note_body(name, rule, [example] if example else [], [], []))
    return path


def seed_constructions(vault, introduced, max_active: int = 3) -> int:
    """Seed the starter list into an empty/missing Constructions/ folder.

    Never runs once the folder holds any note, so notes the learner deleted stay deleted."""
    folder = _dir(vault)
    if folder.is_dir() and any(folder.glob("*.md")):
        return 0
    starter = sorted(load_starter(), key=lambda s: s["priority"])  # stable: file order within a priority
    for i, s in enumerate(starter):
        ensure_construction_note(vault, s["name"], introduced, rule=s["rule"], example=s["example"],
                                 status="active" if i < max_active else "backlog",
                                 priority=s["priority"], theme=s["theme"])
    return len(starter)


def append_construction_evidence(vault, name: str, used_quotes, missed_pairs, day_label: str) -> None:
    path = _path(vault, name)
    if not path.exists():
        return
    fm, body = read_note(path)
    p = parse_note_body(body)
    tag = _short_date(day_label)
    seen_used = {q for q, _ in p["used"]}
    seen_missed = {(b, a) for b, a, _ in p["missed"]}
    changed = False
    for q in used_quotes:
        q = q.strip()
        if q and q not in seen_used:
            seen_used.add(q)
            p["used"].append((q, tag))
            changed = True
    for b, a in missed_pairs:
        b, a = b.strip(), a.strip()
        if b and a and (b, a) not in seen_missed:
            seen_missed.add((b, a))
            p["missed"].append((b, a, tag))
            changed = True
    if changed:
        write_note(path, fm, render_note_body(fm.get("construction", name), p["rule"],
                                              p["examples"], p["used"], p["missed"]))


def apply_construction_notes(vault, analysis: Analysis, introduced, day_label: str) -> None:
    for nc in analysis.new_constructions:
        ensure_construction_note(vault, nc.construction, introduced, rule=nc.rule, example=nc.example)
    used: dict[str, list[str]] = {}
    missed: dict[str, list[tuple[str, str]]] = {}
    for w in analysis.construction_wins:
        used.setdefault(w.phrase, []).append(w.quote)
    for m in analysis.missed_constructions:
        missed.setdefault(m.construction, []).append((m.before, m.after))
    for name in {**used, **missed}:
        append_construction_evidence(vault, name, used.get(name, []), missed.get(name, []), day_label)


def read_constructions(vault) -> list[ConstructionInfo]:
    folder = _dir(vault)
    if not folder.is_dir():
        return []
    out: list[ConstructionInfo] = []
    for note in sorted(folder.glob("*.md")):
        fm, body = read_note(note)
        rule = parse_note_body(body)["rule"]
        out.append(ConstructionInfo(construction=fm.get("construction", note.stem),
                                    status=fm.get("status", "backlog"),
                                    reuse_count=int(fm.get("reuse_count", 0)),
                                    rule="" if rule == _NO_RULE else rule))
    return out
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run --offline pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add english_coach/assets/constructions.toml english_coach/constructions.py tests/test_constructions.py
git commit -m "feat: construction notes, starter list and seeding"
```

---

### Task 3: Daily note, reuse counting, dashboard, folder-aware curation I/O

**Files:**
- Modify: `english_coach/vault.py`
- Test: `tests/test_vault_daily.py`, `tests/test_vault_reuse.py`, `tests/test_vault_curation.py`

**Interfaces:**
- Consumes: Task 1 models; `constructions.apply_construction_notes` (Task 2).
- Produces:
  - daily frontmatter keys `constructions_used: list[str]` (distinct, in order) and `constructions_missed: list[str]` (one per missed item); quiet notes get `[]` for both.
  - `recompute_reuse(vault, adopted_threshold=3, construction_adopted_threshold=5) -> None` — also writes `reuse_count`, `status`, `last_used`, `missed_count` on `Constructions/*.md`.
  - `read_curation_inventory(vault, folder="Phrases", name_key="phrase") -> list[dict]` — items gain `"missed_count": int`; the name stays under key `"phrase"`.
  - `apply_curation(vault, updates, folder="Phrases") -> int`.
  - `apply_analysis_notes` also calls `constructions.apply_construction_notes`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_vault_daily.py`:

```python
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
    assert "| [[unless]] | if not green then wait | wait unless it's green |" in body
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
```

Append to `tests/test_vault_reuse.py`:

```python
from english_coach import constructions as cons
from english_coach.models import MissedConstruction, Win
from english_coach.vault import write_quiet_note


def _cons_analysis(used=(), missed=()):
    return Analysis(wins=[], focus_pattern=None, recurring=[], new_phrases=[], reused_phrases=[],
                    snapshot=[], construction_wins=[Win(n, f"quote {i}") for i, n in enumerate(used)],
                    missed_constructions=[MissedConstruction(n, "b", "a") for n in missed])


def test_construction_reuse_counts_distinct_days_and_missed(tmp_path):
    cons.ensure_construction_note(tmp_path, "unless", date(2026, 7, 1), status="active")
    write_daily_note(tmp_path, _win(3), 1, _cons_analysis(used=["unless", "unless"], missed=["unless"]))
    write_daily_note(tmp_path, _win(4), 1, _cons_analysis(missed=["unless", "unless"]))
    recompute_reuse(tmp_path)
    fm, _ = read_note(tmp_path / "Constructions" / "unless.md")
    assert fm["reuse_count"] == 1
    assert fm["missed_count"] == 3
    assert fm["status"] == "active"
    assert fm["last_used"] == date(2026, 7, 3)


def test_construction_adopted_after_threshold_days(tmp_path):
    cons.ensure_construction_note(tmp_path, "unless", date(2026, 7, 1), status="active")
    for d in (3, 4, 5, 6):
        write_daily_note(tmp_path, _win(d), 1, _cons_analysis(used=["unless"]))
    recompute_reuse(tmp_path, construction_adopted_threshold=5)
    assert read_note(tmp_path / "Constructions" / "unless.md")[0]["status"] == "active"
    write_daily_note(tmp_path, _win(7), 1, _cons_analysis(used=["unless"]))
    recompute_reuse(tmp_path, construction_adopted_threshold=5)
    assert read_note(tmp_path / "Constructions" / "unless.md")[0]["status"] == "adopted"


def test_quiet_note_has_empty_construction_lists(tmp_path):
    fm, _ = read_note(write_quiet_note(tmp_path, _win(5)))
    assert fm["constructions_used"] == [] and fm["constructions_missed"] == []


def test_dashboard_has_construction_sections(tmp_path):
    text = write_dashboard(tmp_path).read_text(encoding="utf-8")
    assert "## Constructions — practicing" in text
    assert 'FROM "Constructions"' in text
    assert "missed_count" in text
    assert "constructions_used" in text
```

Append to `tests/test_vault_curation.py`:

```python
def test_curation_io_on_constructions_folder(tmp_path):
    from datetime import date
    from english_coach import constructions as cons
    from english_coach.frontmatter import read_note
    from english_coach.vault import apply_curation, read_curation_inventory
    cons.ensure_construction_note(tmp_path, "unless", date(2026, 7, 1))
    inv = read_curation_inventory(tmp_path, folder="Constructions", name_key="construction")
    assert inv[0]["phrase"] == "unless" and inv[0]["missed_count"] == 0
    n = apply_curation(tmp_path, {"unless": {"status": "active", "priority": 1, "theme": "conditions"}},
                       folder="Constructions")
    assert n == 1
    assert read_note(tmp_path / "Constructions" / "unless.md")[0]["status"] == "active"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --offline pytest -q tests/test_vault_daily.py tests/test_vault_reuse.py tests/test_vault_curation.py`
Expected: FAIL — missing sections/keys, `TypeError: unexpected keyword argument 'folder'`.

- [ ] **Step 3: Implement in `english_coach/vault.py`**

In `render_daily_body`, insert between the "New phrases" block (after its trailing `lines.append("")`) and `lines.append("## Snapshot")`:

```python
    lines.append("## Constructions used")
    if analysis.construction_wins:
        for w in analysis.construction_wins:
            lines.append(f"- {_link(w.phrase)} — \"{w.quote}\"")
    else:
        lines.append("- (none this time)")
    lines.append("")

    lines.append("## Try this construction")
    if analysis.missed_constructions:
        lines.append("| construction | you wrote | try |")
        lines.append("| --- | --- | --- |")
        for m in analysis.missed_constructions:
            lines.append(f"| {_link(m.construction)} | {_cell(m.before)} | {_cell(m.after)} |")
    else:
        lines.append("(none this time)")
    lines.append("")

    if analysis.new_constructions:
        lines.append("## New constructions")
        for nc in analysis.new_constructions:
            lines.append(f"- {_link(nc.construction)} — {nc.rule} (e.g. \"{nc.example}\")")
        lines.append("")
```

In `write_daily_note`, the frontmatter dict gains:

```python
        "constructions_used": list(dict.fromkeys(w.phrase for w in analysis.construction_wins)),
        "constructions_missed": [m.construction for m in analysis.missed_constructions],
```

In `write_quiet_note`, the frontmatter dict gains:

```python
        "constructions_used": [],
        "constructions_missed": [],
```

At the end of `apply_analysis_notes` add:

```python
    from english_coach import constructions  # local: constructions imports this module
    constructions.apply_construction_notes(vault, analysis, introduced, day_label)
```

Replace the whole `recompute_reuse` function with:

```python
def _count_daily(vault: Path, key: str) -> tuple[dict[str, int], dict[str, _date]]:
    """Occurrences of each name under frontmatter `key` across daily notes, plus last date."""
    counts: dict[str, int] = {}
    last: dict[str, _date] = {}
    daily_dir = Path(vault) / "Daily"
    if daily_dir.exists():
        for daily in sorted(daily_dir.glob("*.md")):
            fm, _ = read_note(daily)
            to = fm.get("to")
            for name in (fm.get(key) or []):
                k = note_name(name)
                counts[k] = counts.get(k, 0) + 1
                if to and (k not in last or to > last[k]):
                    last[k] = to
    return counts, last


def _apply_reuse(folder: Path, counts: dict, last_used: dict, threshold: int,
                 missed: dict | None = None) -> None:
    if not folder.exists():
        return
    for note in folder.glob("*.md"):
        fm, body = read_note(note)
        key = note.stem
        c = counts.get(key, 0)
        fm["reuse_count"] = c
        if missed is not None:
            fm["missed_count"] = missed.get(key, 0)
        status = fm.get("status")
        if c >= threshold or status == "adopted":
            fm["status"] = "adopted"  # terminal: reached threshold once, stays adopted
        elif status not in ("active", "backlog"):
            fm["status"] = "backlog"  # migrate legacy 'learning' / missing status
        if key in last_used:
            fm["last_used"] = last_used[key]
        write_note(note, fm, body)


def recompute_reuse(vault: Path, adopted_threshold: int = 3,
                    construction_adopted_threshold: int = 5) -> None:
    counts, last_used = _count_daily(vault, "reused")
    _apply_reuse(Path(vault) / "Phrases", counts, last_used, adopted_threshold)
    c_counts, c_last = _count_daily(vault, "constructions_used")
    missed, _ = _count_daily(vault, "constructions_missed")
    _apply_reuse(Path(vault) / "Constructions", c_counts, c_last,
                 construction_adopted_threshold, missed)
```

In `_DASHBOARD`, insert after the "## Adopted" block (before "## Recent days"):

````
## Constructions — practicing

```dataview
TABLE priority, theme, reuse_count, missed_count, last_used
FROM "Constructions"
WHERE status = "active"
SORT priority ASC
```

## Constructions — backlog

```dataview
TABLE priority, theme
FROM "Constructions"
WHERE status = "backlog"
SORT priority ASC
LIMIT 15
```

## Constructions — adopted

```dataview
TABLE reuse_count, last_used
FROM "Constructions"
WHERE status = "adopted"
SORT reuse_count DESC
```
````

and change the "Recent days" query's first line to `TABLE prompt_count, reused, constructions_used`. Also change the intro sentence to: `everything else waits in the backlog. Open the graph view to see how days, phrases, constructions and patterns connect.` (keep the line breaks short like the original).

Change `read_curation_inventory` to:

```python
def read_curation_inventory(vault: Path, folder: str = "Phrases",
                            name_key: str = "phrase") -> list[dict]:
    """One entry per NON-adopted note in `folder`, with the metadata the curator needs.
    The item's name is always under "phrase" (the curator's JSON protocol)."""
    notes_dir = Path(vault) / folder
    out: list[dict] = []
    if not notes_dir.exists():
        return out
    for pnote in sorted(notes_dir.glob("*.md")):
        fm, _ = read_note(pnote)
        if fm.get("status") == "adopted":
            continue
        out.append({
            "note_name": pnote.stem,
            "phrase": fm.get(name_key, pnote.stem),
            "status": fm.get("status", "backlog"),
            "priority": fm.get("priority"),
            "theme": fm.get("theme"),
            "reuse_count": int(fm.get("reuse_count", 0)),
            "missed_count": int(fm.get("missed_count", 0)),
            "introduced": fm.get("introduced"),
            "last_used": fm.get("last_used"),
        })
    return out
```

Change `apply_curation`'s signature to `def apply_curation(vault: Path, updates: dict[str, dict], folder: str = "Phrases") -> int:` and its first line to `phrases_dir = Path(vault) / folder`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --offline pytest -q`
Expected: all pass (existing phrase reuse tests unchanged).

- [ ] **Step 5: Commit**

```bash
git add english_coach/vault.py tests/test_vault_daily.py tests/test_vault_reuse.py tests/test_vault_curation.py
git commit -m "feat: construction sections in daily notes, reuse counting and dashboard"
```

---

### Task 4: Analyzer — prompt, schema and parsing

**Files:**
- Modify: `english_coach/analyzer.py`
- Test: `tests/test_analyzer.py`

**Interfaces:**
- Consumes: `ConstructionInfo`, `MissedConstruction`, `NewConstruction`, `Win` (Task 1); `vault.note_name`.
- Produces:
  - `build_analysis_prompt(prompts, phrasebook, max_new_phrases=2, known_patterns=(), profile=Profile(), constructions=(), max_new_constructions=1) -> str`
  - `parse_analysis(payload, max_new_phrases=2, known_constructions=None, max_new_constructions=1) -> Analysis`
  - `ClaudeAnalyzer.analyze(prompts, phrasebook, known_patterns=(), constructions=())` and the same on `ClaudeCliAnalyzer`. Both send only non-adopted constructions to the model and filter wins/missed to those names.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_analyzer.py`:

```python
from english_coach.models import ConstructionInfo
from english_coach.analyzer import _CLI_JSON_INSTRUCTION

_CONS = [ConstructionInfo("be supposed to", "active", 0, "expected behaviour"),
         ConstructionInfo("What if we…?", "backlog", 0, "suggestions"),
         ConstructionInfo("unless", "adopted", 5, "if not")]


def _payload(**extra):
    base = {"wins": [], "focus_pattern": None, "recurring": [], "new_phrases": [],
            "reused_phrases": [], "snapshot": []}
    base.update(extra)
    return base


def test_schema_has_optional_construction_keys():
    schema = ANALYSIS_TOOL["input_schema"]
    for key in ("construction_wins", "missed_constructions", "new_constructions"):
        assert key in schema["properties"]
        assert key not in schema["required"]
        assert key in _CLI_JSON_INSTRUCTION


def test_prompt_lists_constructions_and_active_only_rule():
    text = build_analysis_prompt([UserPrompt("x", None)], [], constructions=_CONS[:2],
                                 max_new_constructions=1)
    assert "- be supposed to | active | expected behaviour" in text
    assert "- What if we…? | backlog | suggestions" in text
    assert "ONLY for constructions with status 'active'" in text
    assert "AT MOST 3" in text


def test_prompt_without_constructions_says_none_yet():
    text = build_analysis_prompt([UserPrompt("x", None)], [])
    assert "Grammar constructions" in text and "- (none yet)" in text


def test_parse_without_construction_keys_gives_empty_lists():
    a = parse_analysis(_payload())
    assert a.construction_wins == [] and a.missed_constructions == [] and a.new_constructions == []


def test_parse_construction_keys_canonicalises_and_filters():
    payload = _payload(
        construction_wins=[{"construction": "be supposed to", "quote": "it's supposed to retry"},
                           {"construction": "BE SUPPOSED TO?", "quote": "case differs"},
                           {"construction": "made up", "quote": "x"},
                           {"construction": "be supposed to"},
                           "not a dict"],
        missed_constructions=[{"construction": "What if we...?", "before": "b", "after": "a"}] * 4
                             + [{"construction": "be supposed to", "before": "", "after": "a"}],
        new_constructions=[{"construction": "end up + -ing", "rule": "r", "example": "e"},
                           {"construction": "as long as", "rule": "r", "example": "e"}])
    a = parse_analysis(payload, known_constructions=["be supposed to", "What if we…?"],
                       max_new_constructions=1)
    assert [(w.phrase, w.quote) for w in a.construction_wins] == [("be supposed to", "it's supposed to retry")]
    assert len(a.missed_constructions) == 3
    assert a.missed_constructions[0].construction == "What if we…?"
    assert [n.construction for n in a.new_constructions] == ["end up + -ing"]


def test_parse_new_construction_matching_known_name_is_dropped():
    a = parse_analysis(_payload(new_constructions=[{"construction": "be supposed to",
                                                    "rule": "r", "example": "e"}]),
                       known_constructions=["be supposed to"])
    assert a.new_constructions == []


def test_cli_analyzer_sends_non_adopted_constructions_and_filters():
    seen = {}

    def runner(prompt):
        seen["prompt"] = prompt
        return json.dumps(_payload(construction_wins=[{"construction": "unless", "quote": "q"},
                                                      {"construction": "be supposed to", "quote": "q2"}]))

    a = ClaudeCliAnalyzer(_cfg(), runner=runner).analyze([UserPrompt("x", None)], [], (), _CONS)
    assert "be supposed to | active" in seen["prompt"]
    assert "unless | adopted" not in seen["prompt"]
    assert [w.phrase for w in a.construction_wins] == ["be supposed to"]
```

Matching rule (Review Focus item 2): names are compared by `_cons_key(name) = note_name(name.replace("...", "…")).strip()`, so `"What if we...?"` matches `"What if we…?"` (and is stored under the canonical name), while matching stays case-sensitive — `"BE SUPPOSED TO?"` is dropped.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --offline pytest -q tests/test_analyzer.py`
Expected: FAIL — `ImportError`/`KeyError` for construction keys, `TypeError` for `constructions=`.

- [ ] **Step 3: Implement in `english_coach/analyzer.py`**

Imports: extend the models import with `ConstructionInfo, MissedConstruction, NewConstruction`, and add `from english_coach.vault import note_name`.

In `ANALYSIS_TOOL["input_schema"]["properties"]`, add after `"snapshot"`:

```python
            "construction_wins": {"type": "array", "items": {"type": "object", "properties": {
                "construction": {"type": "string"}, "quote": {"type": "string"}},
                "required": ["construction", "quote"]}},
            "missed_constructions": {"type": "array", "items": {"type": "object", "properties": {
                "construction": {"type": "string"}, "before": {"type": "string"},
                "after": {"type": "string"}},
                "required": ["construction", "before", "after"]}},
            "new_constructions": {"type": "array", "items": {"type": "object", "properties": {
                "construction": {"type": "string"}, "rule": {"type": "string"},
                "example": {"type": "string"}},
                "required": ["construction", "rule", "example"]}},
```

(`required` stays the six original keys.)

Replace `build_analysis_prompt` with:

```python
def build_analysis_prompt(prompts: list[UserPrompt], phrasebook: list[PhraseInfo],
                          max_new_phrases: int = 2, known_patterns=(),
                          profile: Profile = Profile(), constructions=(),
                          max_new_constructions: int = 1) -> str:
    patterns = "\n".join(f"- {name}: {desc}" if desc else f"- {name}"
                         for name, desc in known_patterns) or "- (none yet)"
    book = "\n".join(f"- {p.phrase} (status: {p.status}, reuse_count: {p.reuse_count})"
                     for p in phrasebook) or "- (empty)"
    cons = "\n".join(f"- {c.construction} | {c.status} | {c.rule or '-'}"
                     for c in constructions) or "- (none yet)"
    joined = "\n\n".join(f"[{i + 1}] {p.text}" for i, p in enumerate(prompts))
    return (
        f"{system_prompt(profile)}\n\n"
        "Known recurring patterns for this user:\n"
        f"{patterns}\n\n"
        "Current phrasebook (taught phrases — detect which were reused today):\n"
        f"{book}\n\n"
        "Grammar constructions the learner is practicing (name | status | rule) — everyday "
        "native structures they rarely use; these are upgrades, not mistakes:\n"
        f"{cons}\n\n"
        "The user's prompts for the period:\n"
        f"{joined}\n\n"
        "Analyze and call report_analysis. reused_phrases must be a subset of the phrasebook "
        "phrase names that the user actually reused correctly. Pick ONE highest-value focus_pattern.\n"
        "For every 'pattern' field (in focus_pattern and recurring), use the EXACT short name "
        "from the 'Known recurring patterns' list above when it applies — copied verbatim, NOT "
        "expanded or paraphrased into a sentence. Only coin a new short 2-4 word name (e.g. "
        "\"Articles\", \"Question formation\") if the issue is genuinely not in that list. Put "
        "the detailed guidance in 'explanation', never in the name.\n"
        f"For new_phrases: propose AT MOST {max_new_phrases}, and only if genuinely high-value "
        "for this user — an empty list is a fine answer. Never re-teach anything already in the "
        "phrasebook above, including close variants of it.\n"
        "construction_wins: for each construction listed above that the learner actually used "
        "correctly, give its name copied verbatim and the learner's verbatim quote. Only names "
        "from that list.\n"
        "missed_constructions: AT MOST 3, ONLY for constructions with status 'active'. Pick "
        "sentences the learner actually wrote ('before', verbatim) where that construction would "
        "sound clearly more natural, and rewrite them with it ('after', same meaning). Skip it "
        "if the rewrite is merely different. An empty list is fine.\n"
        f"new_constructions: AT MOST {max_new_constructions}. Only an everyday native grammar "
        "construction the learner's prompts show they avoid — not vocabulary and not a mistake "
        "(those are patterns), and never a variant of a construction, phrase or pattern listed "
        "above. 'rule' is 1-2 plain sentences; 'example' is one of the learner's sentences "
        "rewritten with it. An empty list is fine."
    )
```

Replace `_CLI_JSON_INSTRUCTION` with:

```python
_CLI_JSON_INSTRUCTION = (
    "\n\nOutput ONLY a single JSON object and nothing else — no prose, no explanation, "
    "no markdown code fences. It must match exactly this shape (the first six keys are "
    "required; construction_wins, missed_constructions and new_constructions are optional but "
    "include them; use [] for empty arrays and null for focus_pattern if there is none):\n"
    '{"wins":[{"phrase":"...","quote":"..."}],'
    '"focus_pattern":{"pattern":"...","explanation":"...",'
    '"examples":[{"before":"...","after":"..."}]},'
    '"recurring":[{"pattern":"...","before":"...","after":"..."}],'
    '"new_phrases":[{"phrase":"...","meaning":"...","example":"..."}],'
    '"reused_phrases":["..."],'
    '"snapshot":["..."],'
    '"construction_wins":[{"construction":"...","quote":"..."}],'
    '"missed_constructions":[{"construction":"...","before":"...","after":"..."}],'
    '"new_constructions":[{"construction":"...","rule":"...","example":"..."}]}'
)
```

Replace `parse_analysis` with:

```python
_MAX_MISSED = 3


def _cons_key(name: str) -> str:
    return note_name(name.replace("...", "…")).strip()


def _dicts(payload: dict, key: str) -> list[dict]:
    return [x for x in (payload.get(key) or []) if isinstance(x, dict)]


def _text(d: dict, key: str) -> str:
    v = d.get(key)
    return v.strip() if isinstance(v, str) else ""


def parse_analysis(payload: dict, max_new_phrases: int = 2, known_constructions=None,
                   max_new_constructions: int = 1) -> Analysis:
    fp_raw = payload.get("focus_pattern")
    fp = None
    if fp_raw:
        fp = FocusPattern(
            pattern=fp_raw["pattern"],
            explanation=fp_raw["explanation"],
            examples=[BeforeAfter(e["before"], e["after"]) for e in fp_raw.get("examples", [])],
        )
    known = (None if known_constructions is None
             else {_cons_key(n): n for n in known_constructions})

    def canon(name: str) -> str | None:
        if not name:
            return None
        return name if known is None else known.get(_cons_key(name))

    cons_wins = []
    for d in _dicts(payload, "construction_wins"):
        name, quote = canon(_text(d, "construction")), _text(d, "quote")
        if name and quote:
            cons_wins.append(Win(name, quote))
    missed = []
    for d in _dicts(payload, "missed_constructions"):
        name, before, after = canon(_text(d, "construction")), _text(d, "before"), _text(d, "after")
        if name and before and after:
            missed.append(MissedConstruction(name, before, after))
    new_cons = []
    for d in _dicts(payload, "new_constructions"):
        name, rule, example = _text(d, "construction"), _text(d, "rule"), _text(d, "example")
        if name and rule and (known is None or _cons_key(name) not in known):
            new_cons.append(NewConstruction(name, rule, example))
    return Analysis(
        wins=[Win(w["phrase"], w["quote"]) for w in payload.get("wins", [])],
        focus_pattern=fp,
        recurring=[Recurring(r["pattern"], r["before"], r["after"]) for r in payload.get("recurring", [])],
        new_phrases=[NewPhrase(n["phrase"], n["meaning"], n["example"])
                     for n in payload.get("new_phrases", [])[:max_new_phrases]],
        reused_phrases=list(payload.get("reused_phrases", [])),
        snapshot=list(payload.get("snapshot", [])),
        construction_wins=cons_wins,
        missed_constructions=missed[:_MAX_MISSED],
        new_constructions=new_cons[:max_new_constructions],
    )
```

Add a helper above `class ClaudeAnalyzer`:

```python
def _practicing(constructions) -> list[ConstructionInfo]:
    return [c for c in constructions if c.status != "adopted"]
```

Replace `ClaudeAnalyzer.analyze` with:

```python
    def analyze(self, prompts: list[UserPrompt], phrasebook: list[PhraseInfo],
               known_patterns=(), constructions=()) -> Analysis:
        cons = _practicing(constructions)
        prompt = build_analysis_prompt(prompts, phrasebook, self._config.max_new_phrases,
                                       known_patterns, self._config.profile, cons,
                                       self._config.max_new_constructions)
        message = self._client.messages.create(
            model=self._config.model,
            max_tokens=_MAX_TOKENS,
            tools=[ANALYSIS_TOOL],
            tool_choice={"type": "tool", "name": "report_analysis"},
            messages=[{"role": "user", "content": prompt}],
        )
        for block in message.content:
            if getattr(block, "type", None) == "tool_use":
                return parse_analysis(block.input, self._config.max_new_phrases,
                                      [c.construction for c in cons],
                                      self._config.max_new_constructions)
        raise RuntimeError("Claude did not return a tool_use block.")
```

Replace `ClaudeCliAnalyzer.analyze` with:

```python
    def analyze(self, prompts: list[UserPrompt], phrasebook: list[PhraseInfo],
               known_patterns=(), constructions=()) -> Analysis:
        cons = _practicing(constructions)
        prompt = (build_analysis_prompt(prompts, phrasebook, self._config.max_new_phrases,
                                        known_patterns, self._config.profile, cons,
                                        self._config.max_new_constructions)
                 + _CLI_JSON_INSTRUCTION)
        text = self._runner(prompt)
        try:
            payload = extract_json_object(text)
        except (ValueError, json.JSONDecodeError):
            # One stricter retry — models occasionally wrap JSON in prose/fences.
            text = self._runner(prompt + "\n\nReturn ONLY the JSON object. No other text.")
            payload = extract_json_object(text)
        return parse_analysis(payload, self._config.max_new_phrases,
                              [c.construction for c in cons], self._config.max_new_constructions)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --offline pytest -q`
Expected: all pass. If the existing `test_prompts_use_profile_not_hardcoded_learner` fails, the new block must not mention a language — it doesn't; re-read the diff.

- [ ] **Step 5: Commit**

```bash
git add english_coach/analyzer.py tests/test_analyzer.py
git commit -m "feat: analyzer detects used and missed grammar constructions"
```

---

### Task 5: Construction enrichment and prompt preambles

**Files:**
- Modify: `english_coach/coach_prompts.py`, `english_coach/analyzer.py`, `english_coach/constructions.py`
- Test: `tests/test_analyzer.py`, `tests/test_constructions.py`, `tests/test_transcripts.py`

**Interfaces:**
- Consumes: `constructions.parse_note_body/render_note_body/FOLDER` (Task 2).
- Produces:
  - `coach_prompts.CONSTRUCTION_ENRICH_PREAMBLE = "You explain everyday English grammar constructions"`, `coach_prompts.CONSTRUCTION_CURATOR_PREAMBLE = "You curate a personal list of English grammar constructions"`, both in `COACH_PROMPT_PREFIXES`.
  - `analyzer.build_construction_enrichment_prompt(items, examples_per_construction=3, profile=Profile()) -> str`
  - `analyzer.enrich_constructions(items, runner=None, examples_per_construction=3, profile=Profile()) -> dict` → `{name: {"rule": str, "examples": list[str]}}`; items `[{"construction", "rule", "your_quote"}]`.
  - `constructions.enrich_construction_notes(vault, enricher, force=False) -> int`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_analyzer.py`:

```python
def test_construction_enrichment_prompt_and_parse():
    from english_coach.analyzer import build_construction_enrichment_prompt, enrich_constructions
    from english_coach.coach_prompts import CONSTRUCTION_ENRICH_PREAMBLE
    from english_coach.profile import Profile
    items = [{"construction": "unless", "rule": "if not", "your_quote": "wait unless green"}]
    text = build_construction_enrichment_prompt(items, profile=Profile("German", "QA engineer"))
    assert text.startswith(CONSTRUCTION_ENRICH_PREAMBLE)
    assert "a German-native QA engineer" in text and "unless" in text and "wait unless green" in text
    reply = '{"constructions":[{"construction":"unless","rule":"R","examples":["a","b"]},{"rule":"x"}]}'
    assert enrich_constructions(items, runner=lambda p: reply) == {"unless": {"rule": "R", "examples": ["a", "b"]}}
    assert enrich_constructions([], runner=lambda p: 1 / 0) == {}
```

Append to `tests/test_constructions.py`:

```python
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
```

In `tests/test_transcripts.py::test_coach_own_prompts_are_skipped_even_from_another_cwd`, extend the imports and the `own` list:

```python
    from english_coach.analyzer import build_construction_enrichment_prompt
    from english_coach.curator import CONSTRUCTIONS
```

```python
        build_construction_enrichment_prompt([{"construction": "unless", "rule": "", "your_quote": None}],
                                             profile=prof),
        build_curation_prompt([], 3, profile=prof, kind=CONSTRUCTIONS),
```

(The `CONSTRUCTIONS` import and `kind=` arrive in Task 6; this test stays red until then — run it again at the end of Task 6.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --offline pytest -q tests/test_analyzer.py tests/test_constructions.py`
Expected: FAIL — `ImportError: build_construction_enrichment_prompt`, `AttributeError: enrich_construction_notes`.

- [ ] **Step 3: Implement**

`english_coach/coach_prompts.py` — add the two constants and extend the tuple:

```python
CONSTRUCTION_ENRICH_PREAMBLE = "You explain everyday English grammar constructions"
CONSTRUCTION_CURATOR_PREAMBLE = "You curate a personal list of English grammar constructions"

COACH_PROMPT_PREFIXES = (ANALYSIS_PREAMBLE, ENRICH_PREAMBLE, PATTERN_PREAMBLE, CURATOR_PREAMBLE,
                         CONSTRUCTION_ENRICH_PREAMBLE, CONSTRUCTION_CURATOR_PREAMBLE)
```

`english_coach/analyzer.py` — add `CONSTRUCTION_ENRICH_PREAMBLE` to the `coach_prompts` import, and append at the end of the file:

```python
def construction_enrich_system(profile: Profile) -> str:
    return (
        f"{CONSTRUCTION_ENRICH_PREAMBLE} to {profile.learner()}. Each 'rule' is 1-2 plain-English "
        "sentences: the form of the construction and when native speakers reach for it. Example "
        f"sentences must sound natural in the learner's working context ({profile.work_context()}) "
        "— the kind of thing they would actually say to a colleague or write in a work message."
    )


def build_construction_enrichment_prompt(items: list[dict], examples_per_construction: int = 3,
                                         profile: Profile = Profile()) -> str:
    """items: [{"construction": str, "rule": str, "your_quote": str | None}]."""
    blocks = []
    for it in items:
        q = it.get("your_quote")
        suffix = f'\n  the learner actually used it: "{q}"' if q else ""
        blocks.append(f"- {it['construction']}\n  current rule: {it.get('rule') or '(none)'}{suffix}")
    listing = "\n".join(blocks)
    return (
        f"{construction_enrich_system(profile)}\n\n"
        f"For EACH construction below, write a crisp 'rule' and {examples_per_construction} example "
        "sentences. Do NOT reuse the learner's own quoted sentence as an example — write fresh ones.\n\n"
        f"Constructions:\n{listing}\n\n"
        "Output ONLY a single JSON object of exactly this shape — no prose, no markdown fences:\n"
        '{"constructions":[{"construction":"<the name verbatim>","rule":"...","examples":["...","..."]}]}\n'
        "Include EVERY construction, name copied verbatim so it can be matched back."
    )


def enrich_constructions(items: list[dict], runner=None, examples_per_construction: int = 3,
                         profile: Profile = Profile()) -> dict:
    """Return {construction: {"rule": str, "examples": [str, ...]}}. One batched call."""
    if not items:
        return {}
    runner = runner or (lambda p: run_claude_cli(p))
    prompt = build_construction_enrichment_prompt(items, examples_per_construction, profile)
    text = runner(prompt)
    try:
        payload = extract_json_object(text)
    except (ValueError, json.JSONDecodeError):
        text = runner(prompt + "\n\nReturn ONLY the JSON object. No other text.")
        payload = extract_json_object(text)
    out: dict = {}
    for c in payload.get("constructions", []):
        name = c.get("construction")
        if name:
            out[name] = {"rule": c.get("rule", ""), "examples": list(c.get("examples", []))}
    return out
```

`english_coach/constructions.py` — append:

```python
def enrich_construction_notes(vault, enricher, force: bool = False) -> int:
    """Fill in Rule + examples via `enricher` ([{"construction","rule","your_quote"}] ->
    {name: {"rule","examples"}}), keeping the evidence sections. Only notes without
    `enriched: true` are done unless force=True. Returns the count enriched."""
    folder = _dir(vault)
    if not folder.is_dir():
        return 0
    todo = []
    for note in sorted(folder.glob("*.md")):
        fm, body = read_note(note)
        if force or not fm.get("enriched"):
            todo.append((note, fm, parse_note_body(body)))
    if not todo:
        return 0
    items = [{"construction": fm.get("construction", note.stem),
              "rule": "" if p["rule"] == _NO_RULE else p["rule"],
              "your_quote": p["used"][0][0] if p["used"] else None} for note, fm, p in todo]
    data = enricher(items)
    count = 0
    for (note, fm, p), it in zip(todo, items):
        d = data.get(it["construction"])
        if not d:
            continue
        new_fm = dict(fm)
        new_fm["enriched"] = True
        write_note(note, new_fm, render_note_body(it["construction"], d.get("rule") or p["rule"],
                                                  list(d.get("examples") or p["examples"]),
                                                  p["used"], p["missed"]))
        count += 1
    return count
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --offline pytest -q --deselect tests/test_transcripts.py::test_coach_own_prompts_are_skipped_even_from_another_cwd`
Expected: all pass (the deselected test turns green in Task 6).

- [ ] **Step 5: Commit**

```bash
git add english_coach/coach_prompts.py english_coach/analyzer.py english_coach/constructions.py tests/test_analyzer.py tests/test_constructions.py tests/test_transcripts.py
git commit -m "feat: construction note enrichment and self-exclusion preambles"
```

---

### Task 6: Curator kinds

**Files:**
- Modify: `english_coach/curator.py`
- Test: `tests/test_curator.py`, `tests/test_transcripts.py` (from Task 5)

**Interfaces:**
- Consumes: `vault.read_curation_inventory(vault, folder, name_key)`, `vault.apply_curation(vault, updates, folder)` (Task 3); `CONSTRUCTION_CURATOR_PREAMBLE` (Task 5).
- Produces: `CurationKind(folder, name_key, preamble, noun, theme_examples, show_missed=False)`; `PHRASES`, `CONSTRUCTIONS`; `curator_system(profile, kind=PHRASES)`, `build_curation_prompt(inventory, max_active, profile=Profile(), kind=PHRASES)`, `curate(vault, runner=None, max_active=12, profile=Profile(), kind=PHRASES) -> int`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_curator.py`:

```python
from english_coach.curator import CONSTRUCTIONS, PHRASES


def test_phrase_prompt_unchanged_in_substance():
    p = build_curation_prompt([_inv("park it")], max_active=12)
    assert p.startswith("You curate a personal English phrasebook")
    assert "At most 12 phrases" in p
    assert "missed_count" not in p


def test_construction_prompt_wording_and_missed_count():
    inv = [dict(_inv("unless", status="active", priority=1, theme="conditions"), missed_count=4)]
    p = build_curation_prompt(inv, max_active=3, kind=CONSTRUCTIONS)
    assert p.startswith("You curate a personal list of English grammar constructions")
    assert "At most 3 grammar constructions" in p
    assert "missed_count: 4" in p
    assert "high missed_count" in p


def test_curate_constructions_folder_with_cap(tmp_path):
    from english_coach import constructions as cons
    for name in ("unless", "as long as", "in that case"):
        cons.ensure_construction_note(tmp_path, name, date(2026, 7, 1))
    reply = json.dumps({"phrases": [
        {"phrase": n, "status": "active", "priority": i + 1, "theme": "conditions"}
        for i, n in enumerate(("unless", "as long as", "in that case"))]})
    changed = curate(tmp_path, runner=lambda p: reply, max_active=2, kind=CONSTRUCTIONS)
    assert changed == 3
    statuses = {n: read_note(tmp_path / "Constructions" / f"{n}.md")[0]["status"]
                for n in ("unless", "as long as", "in that case")}
    assert statuses == {"unless": "active", "as long as": "active", "in that case": "backlog"}
    assert not (tmp_path / "Phrases").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --offline pytest -q tests/test_curator.py`
Expected: FAIL — `ImportError: cannot import name 'CONSTRUCTIONS'`.

- [ ] **Step 3: Implement in `english_coach/curator.py`**

Add imports `from dataclasses import dataclass` and extend `from english_coach.coach_prompts import CURATOR_PREAMBLE, CONSTRUCTION_CURATOR_PREAMBLE`. Add after the imports:

```python
@dataclass(frozen=True)
class CurationKind:
    folder: str
    name_key: str
    preamble: str
    noun: str
    theme_examples: str
    show_missed: bool = False


PHRASES = CurationKind("Phrases", "phrase", CURATOR_PREAMBLE, "phrases",
                       "'hedging', 'review feedback', 'asking for changes'")
CONSTRUCTIONS = CurationKind("Constructions", "construction", CONSTRUCTION_CURATOR_PREAMBLE,
                             "grammar constructions",
                             "'suggesting', 'expectations', 'hypotheticals', 'linking ideas'",
                             show_missed=True)
```

Replace `curator_system` and `build_curation_prompt`:

```python
def curator_system(profile: Profile, kind: CurationKind = PHRASES) -> str:
    return (
        f"{kind.preamble} for {profile.learner()}. "
        f"The learner can only actively practice a small set of {kind.noun} at a time. Decide which "
        f"{kind.noun} are 'active' (currently practicing) vs 'backlog' (parked for later), give each "
        "a priority (1 = practice first .. 5 = someday), and a short theme label that groups "
        f"related {kind.noun} (e.g. {kind.theme_examples})."
    )


def build_curation_prompt(inventory: list[dict], max_active: int,
                          profile: Profile = Profile(), kind: CurationKind = PHRASES) -> str:
    lines = []
    for it in inventory:
        missed = f" | missed_count: {it.get('missed_count', 0)}" if kind.show_missed else ""
        lines.append(
            f"- {it['phrase']} | status: {it['status']} | priority: {it.get('priority') or '-'}"
            f" | theme: {it.get('theme') or '-'} | reuse_count: {it['reuse_count']}{missed}"
            f" | introduced: {it.get('introduced') or '-'} | last_used: {it.get('last_used') or '-'}"
        )
    listing = "\n".join(lines)
    missed_rule = ("- Prefer activating items with a high missed_count: the learner keeps meeting "
                   "situations that need them.\n" if kind.show_missed else "")
    return (
        f"{curator_system(profile, kind)}\n\n"
        "Rules:\n"
        f"- At most {max_active} {kind.noun} may be 'active'.\n"
        "- Keep current assignments stable: change an item's status/priority/theme only when "
        "you have a concrete reason (near-duplicate of another item, stale and never reused, "
        "or a clearly higher-value newcomer deserving the slot).\n"
        "- Every item gets a priority 1-5 (1 = practice first) and a short theme (2-3 words).\n"
        "- Give related items the SAME theme label so they group together.\n"
        f"{missed_rule}\n"
        f"The current list (metadata shown):\n{listing}\n\n"
        "Output ONLY a single JSON object of exactly this shape — no prose, no markdown fences:\n"
        '{"phrases":[{"phrase":"<verbatim>","status":"active|backlog","priority":1,"theme":"..."}]}\n'
        "Include EVERY item listed, copied verbatim so it can be matched back."
    )
```

Replace `curate`:

```python
def curate(vault: Path, runner=None, max_active: int = 12,
          profile: Profile = Profile(), kind: CurationKind = PHRASES) -> int:
    """One full curation pass over the non-adopted notes of `kind`.

    Raises on LLM/parse failure — the caller decides fail-soft behavior.
    Returns the number of notes whose frontmatter changed."""
    from english_coach import vault as vault_mod

    inventory = vault_mod.read_curation_inventory(vault, folder=kind.folder, name_key=kind.name_key)
    if not inventory:
        return 0
    runner = runner or (lambda p: run_claude_cli(p))
    prompt = build_curation_prompt(inventory, max_active, profile, kind)
    text = runner(prompt)
    try:
        payload = extract_json_object(text)
    except (ValueError, json.JSONDecodeError):
        text = runner(prompt + "\n\nReturn ONLY the JSON object. No other text.")
        payload = extract_json_object(text)
    decisions = parse_curation(payload)
    updates = apply_guardrails(inventory, decisions, max_active)
    return vault_mod.apply_curation(vault, updates, folder=kind.folder)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --offline pytest -q`
Expected: all pass, including `test_transcripts.py::test_coach_own_prompts_are_skipped_even_from_another_cwd` and the existing `test_build_prompt_lists_inventory_and_rules` (`"stable"` and `"At most 12"` still present).

- [ ] **Step 5: Commit**

```bash
git add english_coach/curator.py tests/test_curator.py
git commit -m "feat: curator handles phrases and grammar constructions"
```

---

### Task 7: Orchestration — run, CLI, skeleton

**Files:**
- Modify: `english_coach/coach.py`, `english_coach/cli.py`, `english_coach/skeleton.py`
- Test: `tests/test_coach.py`, `tests/test_cli_run.py`, `tests/test_skeleton.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `coach.run(..., curator=None, construction_curator=None, construction_enricher=None) -> str`; `english-coach enrich --constructions`; skeleton creates and seeds `Constructions/`.

- [ ] **Step 1: Update the analyzer fakes and write the failing tests**

In `tests/test_coach.py`, change `FakeAnalyzer.analyze` to:

```python
    def analyze(self, prompts, phrasebook, known_patterns=(), constructions=()):
        self.called = True
        self.known_patterns = list(known_patterns)
        self.constructions = list(constructions)
        return self._analysis
```

In `tests/test_cli_run.py`, change `FakeAnalyzer.analyze` signature to `def analyze(self, prompts, phrasebook, known_patterns=(), constructions=()):`.

Append to `tests/test_coach.py`:

```python
from english_coach.frontmatter import read_note
from english_coach.models import Win


def test_run_seeds_constructions_into_existing_vault_and_passes_them(tmp_path):
    (tmp_path / "Phrases").mkdir()  # an existing vault without Constructions/
    analyzer = FakeAnalyzer(Analysis(wins=[], focus_pattern=None, recurring=[], new_phrases=[],
                                     reused_phrases=[], snapshot=[],
                                     construction_wins=[Win("be supposed to", "it's supposed to retry")]))
    status = run(_cfg(tmp_path), FakeSource([_p("Why isn't it retried here?")]), analyzer, now_utc=NOW)
    assert status == "wrote:2026-07-05"
    names = {c.construction for c in analyzer.constructions}
    assert "be supposed to" in names
    fm, _ = read_note(tmp_path / "Constructions" / "be supposed to.md")
    assert fm["reuse_count"] == 1
    daily_fm, _ = read_note(tmp_path / "Daily" / "2026-07-05.md")
    assert daily_fm["constructions_used"] == ["be supposed to"]


def test_construction_curator_and_enricher_are_called_and_fail_soft(tmp_path, capsys):
    calls = []

    def boom():
        calls.append("curator")
        raise RuntimeError("curator down")

    def enricher(items):
        calls.append("enricher")
        raise RuntimeError("enricher down")

    status = run(_cfg(tmp_path), FakeSource([_p("Why isn't it retried here?")]),
                 FakeAnalyzer(_empty_analysis()), now_utc=NOW,
                 construction_curator=boom, construction_enricher=enricher)
    assert status == "wrote:2026-07-05"
    assert calls == ["curator", "enricher"]
    err = capsys.readouterr().err
    assert "curator down" in err and "enricher down" in err
    assert read_watermark(tmp_path) is not None


def test_quiet_day_still_seeds_constructions(tmp_path):
    run(_cfg(tmp_path), FakeSource([_p("ok")]), FakeAnalyzer(_empty_analysis()), now_utc=NOW)
    assert (tmp_path / "Constructions" / "be supposed to.md").exists()
```

Append to `tests/test_skeleton.py`:

```python
def test_skeleton_creates_and_seeds_constructions(tmp_path):
    v = tmp_path / "vault"
    created = create_skeleton(v)
    assert (v / "Constructions" / "be supposed to.md").exists()
    assert "starter grammar constructions" in created
```

Append to `tests/test_cli_run.py`:

```python
def test_enrich_constructions_flag_only_enriches_constructions(tmp_path, monkeypatch):
    paths, cfg = _setup(tmp_path)
    seen = []
    monkeypatch.setattr(cli.vault, "enrich_phrase_notes", lambda *a, **k: seen.append("phrases") or 0)
    monkeypatch.setattr(cli.vault, "enrich_pattern_notes", lambda *a, **k: seen.append("patterns") or 0)
    monkeypatch.setattr(cli.constructions, "enrich_construction_notes",
                        lambda *a, **k: seen.append("constructions") or 0)
    monkeypatch.setattr(cli, "make_runner", lambda config, p: (lambda prompt: "{}"))
    assert cli.main(["enrich", "--constructions"], env={"ENGLISH_COACH_CONFIG_DIR": str(paths.config_dir)}) == 0
    assert seen == ["constructions"]
    seen.clear()
    assert cli.main(["enrich"], env={"ENGLISH_COACH_CONFIG_DIR": str(paths.config_dir)}) == 0
    assert seen == ["phrases", "patterns", "constructions"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --offline pytest -q tests/test_coach.py tests/test_cli_run.py tests/test_skeleton.py`
Expected: FAIL — no `Constructions/` folder, `TypeError: unexpected keyword argument 'construction_curator'`, `AttributeError: module 'english_coach.cli' has no attribute 'constructions'`.

- [ ] **Step 3: Implement**

`english_coach/coach.py` — add `from english_coach import constructions`. Change `run`'s signature to end with `include_today: bool = False, curator=None, construction_curator=None, construction_enricher=None) -> str:`. Right after the `if window.is_empty:` block, add:

```python
    constructions.seed_constructions(config.vault_path, introduced=window.days[-1],
                                     max_active=config.max_active_constructions)
```

In both the quiet branch and the main branch, replace `vault.recompute_reuse(config.vault_path, config.adopted_threshold)` with:

```python
        vault.recompute_reuse(config.vault_path, config.adopted_threshold,
                              config.construction_adopted_threshold)
```

(indentation per branch), and replace each `_run_curator(curator)` with:

```python
    _run_curator(curator, "phrase")
    _run_curator(construction_curator, "construction")
```

Replace the analysis call with:

```python
    phrasebook = vault.read_phrasebook(config.vault_path)
    known_patterns = vault.read_known_patterns(config.vault_path)
    cons = constructions.read_constructions(config.vault_path)
    analysis = analyzer.analyze(prompts, phrasebook, known_patterns, cons)
```

After the two existing `_run_enricher` lines add:

```python
    _run_enricher(constructions.enrich_construction_notes, config.vault_path,
                  construction_enricher, "construction")
```

Change `_run_curator` to:

```python
def _run_curator(curator, kind: str = "phrase") -> None:
    """Fail-soft: curation must never break the daily run."""
    if curator is None:
        return
    try:
        changed = curator()
        if changed:
            print(f"Curated {changed} {kind} note(s).")
    except Exception as exc:
        print(f"Curator failed (skipped): {exc}", file=sys.stderr)
```

`english_coach/cli.py` — imports become:

```python
from english_coach import coach, constructions, scheduler, vault
from english_coach.analyzer import (
    ClaudeAnalyzer, ClaudeCliAnalyzer, enrich_constructions, enrich_patterns, enrich_phrases,
    run_claude_cli,
)
from english_coach.curator import CONSTRUCTIONS, curate
```

In `execute_run`, the `coach.run(...)` call gains:

```python
                    construction_enricher=lambda items: enrich_constructions(
                        items, runner=runner, profile=prof),
                    construction_curator=lambda: curate(
                        config.vault_path, runner=runner,
                        max_active=config.max_active_constructions, profile=prof,
                        kind=CONSTRUCTIONS))
```

(move the closing parenthesis of the existing `curator=` lambda accordingly).

Replace the body of `cmd_enrich` with:

```python
def cmd_enrich(args, paths: AppPaths, env: dict) -> int:
    config = _load(paths, env, args)
    runner = make_runner(config, paths)
    prof = config.profile
    picked = args.phrases or args.patterns or args.constructions
    try:
        if args.phrases or not picked:
            n = vault.enrich_phrase_notes(
                config.vault_path, lambda items: enrich_phrases(items, runner=runner, profile=prof),
                force=args.force)
            print(f"Enriched {n} phrase note(s).")
        if args.patterns or not picked:
            n = vault.enrich_pattern_notes(
                config.vault_path, lambda items: enrich_patterns(items, runner=runner, profile=prof),
                force=args.force)
            print(f"Enriched {n} pattern note(s).")
        if args.constructions or not picked:
            n = constructions.enrich_construction_notes(
                config.vault_path,
                lambda items: enrich_constructions(items, runner=runner, profile=prof),
                force=args.force)
            print(f"Enriched {n} construction note(s).")
        return 0
    except Exception as exc:
        print(f"Enrich failed: {exc}", file=sys.stderr)
        return 1
```

In `build_parser`, after `enrich.add_argument("--patterns", action="store_true")` add `enrich.add_argument("--constructions", action="store_true")`, and change the enrich help to `"Add definitions/examples/rules to bare phrase, pattern and construction notes."`.

`english_coach/skeleton.py` — add `from datetime import date` and `from english_coach import constructions`; set `_FOLDERS = ("Daily", "Phrases", "Patterns", "Constructions")`; after the dashboard block in `create_skeleton` add:

```python
    if constructions.seed_constructions(vault, introduced=date.today()):
        created.append("starter grammar constructions")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --offline pytest -q`
Expected: all pass, including `test_second_run_is_noop` (seeding returns 0 the second time) and the existing `test_execute_run_writes_note_log_and_last_run` (its runner returns `{"phrases": []}`, which the construction curator/enricher treat as "nothing to change").

- [ ] **Step 5: Commit**

```bash
git add english_coach/coach.py english_coach/cli.py english_coach/skeleton.py tests/test_coach.py tests/test_cli_run.py tests/test_skeleton.py
git commit -m "feat: wire grammar constructions into run, enrich and init"
```

---

### Task 8: Privacy scan, packaging and docs

**Files:**
- Modify: `tests/test_no_personal_data.py`, `tests/test_skeleton.py`, `README.md`

**Interfaces:**
- Consumes: `english_coach/assets/constructions.toml` (Task 2).
- Produces: none (verification + docs).

- [ ] **Step 1: Extend the scans**

In `tests/test_no_personal_data.py` change `SCANNED` to:

```python
SCANNED = [ROOT / "README.md", ROOT / "pyproject.toml", *sorted((ROOT / "english_coach").rglob("*.py")),
           *sorted((ROOT / "english_coach" / "assets").glob("*.toml"))]
```

In `tests/test_skeleton.py::test_wheel_contains_obsidian_assets`, add `"english_coach/assets/constructions.toml",` to the tuple of expected files.

- [ ] **Step 2: Run the scans (including the slow wheel test)**

Run: `uv run --offline pytest -q tests/test_no_personal_data.py && uv run pytest -q -m slow tests/test_skeleton.py`
Expected: PASS. If `test_no_personal_or_internal_strings` fails, replace the offending starter example with a generic one; never add an exception.

- [ ] **Step 3: Update `README.md`**

In "## How it works", append this paragraph after the existing one:

```markdown
Besides phrases (vocabulary) and patterns (recurring mistakes), the coach tracks **grammar
constructions** — everyday native structures you rarely use, such as "be supposed to",
"What if we…?" or "end up + -ing". A starter list is seeded into `Constructions/`; the coach
keeps three active at a time, notes when you use one correctly, and shows a few of your own
sentences rewritten with it under **Try this construction** in the daily note. A construction
counts as adopted after you've used it on five different days.
```

In the `[limits]` block of "## Configuration", add:

```toml
max_active_constructions = 3
max_new_constructions = 1
construction_adopted_threshold = 5
```

In the "## Commands" table, change the `enrich` row to:

```markdown
| `english-coach enrich` | Adds definitions/examples/rules to bare phrase, pattern and construction notes (`--phrases`, `--patterns`, `--constructions` to pick). |
```

- [ ] **Step 4: Full suite**

Run: `uv run --offline pytest -q`
Expected: all pass, 3 skipped.

- [ ] **Step 5: Commit**

```bash
git add tests/test_no_personal_data.py tests/test_skeleton.py README.md
git commit -m "docs: grammar constructions; scan starter list for personal data"
```
