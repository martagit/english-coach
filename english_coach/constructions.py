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
