"""Split broad pattern notes ("Missing words") into one-rule notes.

plan_resplit asks the model to audit every pattern note and validates the answer;
apply_resplit moves the examples, re-links old daily notes and moves the broad notes to .trash/.
"""
from __future__ import annotations

import re
import shutil
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from english_coach.frontmatter import read_note, write_note
from english_coach.vault import (
    _extract_rule, _parse_pattern_examples, _render_pattern_note, append_pattern_examples_tagged,
    enrich_pattern_notes,
    ensure_pattern_note, note_name,
)


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


@dataclass
class ResplitResult:
    notes_split: int = 0
    moved: int = 0
    dropped: int = 0
    created: int = 0
    dailies: int = 0
    enriched: int = 0


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
    # Notes the model wants emptied (no example stays) can't receive examples.
    emptied = {_key(p) for p, _, _, _ in notes
               if p in raw and not any(_stays(t, p) for t in raw[p].values())}
    for pattern, path, _, examples in notes:
        if pattern not in raw:
            plan.kept.append(pattern)
            continue
        moves, reason = _moves(pattern, examples, raw[pattern], existing, emptied)
        if reason:
            plan.skipped.append((pattern, reason))
        elif all(_stays(m.target, pattern) for m in moves):
            plan.kept.append(pattern)
        else:
            plan.splits.append(NoteSplit(pattern, path, moves))
    return plan


def _stays(target, pattern: str) -> bool:
    """An example whose target is its own note stays where it is."""
    return isinstance(target, str) and bool(note_name(target)) and _key(target) == _key(pattern)


def _moves(pattern, examples, answer, existing, emptied):
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
            if _key(target) != _key(pattern) and _key(target) in emptied:
                return [], f"target is being emptied: {target}"
        moves.append(Move(b, a, t, target))
    return moves, ""


def _short(text: str, width: int = 60) -> str:
    return text if len(text) <= width else text[:width - 3] + "…"


def format_plan(plan: ResplitPlan, vault: Path) -> str:
    folder = Path(vault) / "Patterns"
    lines = []
    for s in plan.splits:
        stay = sum(_stays(m.target, s.pattern) for m in s.moves)
        lines.append(f"{s.pattern} → split" + (f" ({stay} stays)" if stay else ""))
        for m in s.moves:
            if _stays(m.target, s.pattern):
                continue
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


_ROW_RE = re.compile(r'^\|\s*\[\[(?P<name>[^\]]+)\]\]\s*\|(?P<rest>.*)$')  # tolerates aligned tables
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


def apply_resplit(vault: Path, plan: ResplitPlan, enricher) -> ResplitResult:
    """Move each split note's examples to their targets (keeping date tags), delete the
    note to .trash/ after re-linking daily notes, then write Rules for the new notes."""
    res = ResplitResult()
    if not plan.splits:
        return res
    folder = Path(vault) / "Patterns"
    for s in plan.splits:  # back up notes that will be trimmed, before anything is written
        if any(_stays(m.target, s.pattern) for m in s.moves):
            shutil.copy2(s.path, _trash_path(vault, s.path))
    for s in plan.splits:
        rows: dict[str, list[tuple[str, str, str]]] = {}
        for m in s.moves:
            if _stays(m.target, s.pattern):
                continue
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
    # Re-link before removing anything: a failure here leaves the broad notes in place,
    # so a re-run can finish (re-appending is deduplicated).
    moves: dict[str, dict] = {}
    for s in plan.splits:
        targets = {_norm(m.before): s.path.stem if _stays(m.target, s.pattern) else m.target
                   for m in s.moves}
        moves[note_name(s.pattern)] = targets
        moves[s.path.stem] = targets  # a note renamed in Obsidian is linked by its file name
    res.dailies = rewrite_daily_links(vault, moves)
    for s in plan.splits:
        if any(_stays(m.target, s.pattern) for m in s.moves):
            _trim(vault, s)
        else:
            s.path.rename(_trash_path(vault, s.path))
        res.notes_split += 1
    res.enriched = enrich_pattern_notes(vault, enricher)
    return res


def _trim(vault: Path, s: NoteSplit) -> None:
    """Remove the examples that moved away (the original was backed up to `.trash/`)."""
    fm, body = read_note(s.path)
    gone = {(m.before, m.after) for m in s.moves if not _stays(m.target, s.pattern)}
    pairs = [p for p in _parse_pattern_examples(body) if (p[0], p[1]) not in gone]
    write_note(s.path, fm, _render_pattern_note(s.pattern, _extract_rule(body), pairs))


def _trash_path(vault: Path, path: Path) -> Path:
    """A free name in the vault's `.trash/` (Obsidian's own trash): notes are moved or
    backed up there instead of deleted, so hand-written content can be recovered."""
    trash = Path(vault) / ".trash"
    trash.mkdir(exist_ok=True)
    dest, n = trash / path.name, 0
    while dest.exists():
        n += 1
        dest = trash / f"{path.stem} {n}{path.suffix}"
    return dest
