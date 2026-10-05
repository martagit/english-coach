"""Split broad pattern notes ("Missing words") into one-rule notes.

plan_resplit asks the model to audit every pattern note and validates the answer;
apply_resplit moves the examples, deletes the broad notes and re-links old daily notes.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from english_coach.frontmatter import read_note, write_note
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
