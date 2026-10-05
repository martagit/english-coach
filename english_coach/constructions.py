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
from english_coach.fix_markup import text_key
from english_coach.vault import (
    _short_date, construction_key, example_line, note_name, parse_example_line,
    reformat_example_lines,
)

FOLDER = "Constructions"
_RULE = "**Rule:**"
_NO_RULE = "(rule to be added)"
_EXAMPLES = "**Examples**"
_USED = "## You used it"
_MISSED = "## Try it next time"
_PLACEHOLDERS = {_EXAMPLES: "_(no examples yet)_", _USED: "_(not yet)_", _MISSED: "_(nothing yet)_"}
_USED_RE = re.compile(r'^- "(?P<quote>.+)"(?:\s+·\s+_(?P<tag>.+?)_)?$')


def _dir(vault) -> Path:
    return Path(vault) / FOLDER


def _path(vault, name: str) -> Path:
    return _dir(vault) / f"{note_name(name)}.md"


def _tag(t: str) -> str:
    return f"  · _{t}_" if t else ""


def load_starter() -> list[dict]:
    text = (files("english_coach") / "assets" / "constructions.toml").read_text(encoding="utf-8")
    return tomllib.loads(text)["construction"]


def _used_line(q: str, t: str) -> str:
    return f'- "{q}"{_tag(t)}'


def _missed_line(b: str, a: str, t: str) -> str:
    return example_line(b, a, t)


def render_note_body(name, rule, examples, used, missed) -> str:
    lines = [f"# {name}", "", f"{_RULE} {rule or _NO_RULE}", "", _EXAMPLES]
    lines += [f"- {e}" for e in examples] or [_PLACEHOLDERS[_EXAMPLES]]
    lines += ["", _USED]
    lines += [_used_line(q, t) for q, t in used] or [_PLACEHOLDERS[_USED]]
    lines += ["", _MISSED]
    lines += [_missed_line(b, a, t) for b, a, t in missed] or [_PLACEHOLDERS[_MISSED]]
    return "\n".join(lines)


def _edit_section(lines: list[str], header: str, items: list[str], append: bool) -> None:
    """Replace (or extend) the lines under `header` in place, leaving every other
    line of the note — including the learner's own sections — untouched."""
    try:
        i = next(k for k, line in enumerate(lines) if line.strip() == header)
    except StopIteration:
        lines += ["", header, *items]
        return
    j = i + 1
    while j < len(lines) and not lines[j].lstrip().startswith(("#", "**")):
        j += 1
    kept = [line for line in lines[i + 1:j]
            if line.strip() and line.strip() not in _PLACEHOLDERS.values()] if append else []
    new = kept + items or [_PLACEHOLDERS[header]]
    lines[i + 1:j] = new + ([""] if j < len(lines) else [])


def _set_rule(lines: list[str], rule: str) -> None:
    for k, line in enumerate(lines):
        if line.strip().startswith(_RULE):
            lines[k] = f"{_RULE} {rule}"
            return
    lines[1:1] = ["", f"{_RULE} {rule}"]


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
        elif section == "missed" and s.startswith("- ") and (p := parse_example_line(s)):
            missed.append(p)
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
    seen_missed = {(text_key(b), text_key(a)) for b, a, _ in p["missed"]}
    new_used, new_missed = [], []
    for q in used_quotes:
        q = q.strip()
        if q and q not in seen_used:
            seen_used.add(q)
            new_used.append(_used_line(q, tag))
    for b, a in missed_pairs:
        b, a = b.strip(), a.strip()
        if b and a and (text_key(b), text_key(a)) not in seen_missed:
            seen_missed.add((text_key(b), text_key(a)))
            new_missed.append(_missed_line(b, a, tag))
    if not (new_used or new_missed):
        return
    # Edit in place: the learner may have written their own notes in this file.
    lines = body.splitlines()
    if new_used:
        _edit_section(lines, _USED, new_used, append=True)
    if new_missed:
        _edit_section(lines, _MISSED, new_missed, append=True)
    write_note(path, fm, "\n".join(lines))


def reformat_construction_body(body: str) -> str:
    """Convert old `✗ b → ✓ a` lines in "Try it next time" to the inline format, in place."""
    return reformat_example_lines(body, _MISSED)


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


def enrich_construction_notes(vault, enricher, force: bool = False) -> int:
    """Fill in Rule + examples via `enricher` ([{"construction","rule","your_quote"}] ->
    {name: {"rule","examples"}}), editing those two parts in place so evidence and the
    learner's own notes survive. Only notes without `enriched: true` are done unless
    force=True. Returns the count enriched."""
    folder = _dir(vault)
    if not folder.is_dir():
        return 0
    todo = []
    for note in sorted(folder.glob("*.md")):
        fm, body = read_note(note)
        if force or not fm.get("enriched"):
            todo.append((note, fm, body, parse_note_body(body)))
    if not todo:
        return 0
    items = [{"construction": fm.get("construction", note.stem),
              "rule": "" if p["rule"] == _NO_RULE else p["rule"],
              "your_quote": p["used"][0][0] if p["used"] else None} for note, fm, _, p in todo]
    # The model may re-type names ('...' for '…'), so match on the tolerant key.
    data = {construction_key(k): v for k, v in enricher(items).items()}
    count = 0
    for (note, fm, body, _), it in zip(todo, items):
        d = data.get(construction_key(it["construction"]))
        if not d:
            continue
        lines = body.splitlines()
        if d.get("rule"):
            _set_rule(lines, d["rule"])
        if d.get("examples"):
            _edit_section(lines, _EXAMPLES, [f"- {e}" for e in d["examples"]], append=False)
        new_fm = dict(fm)
        new_fm["enriched"] = True
        write_note(note, new_fm, "\n".join(lines))
        count += 1
    return count
