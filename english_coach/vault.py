from __future__ import annotations

import re
import sys
from pathlib import Path

from english_coach.fix_markup import parse_fix, render_fix, text_key
from english_coach.models import Analysis, Window
from english_coach.window import note_basename
from english_coach.frontmatter import write_note

_INVALID = re.compile(r'[\\/:*?"<>|\[\]#^]')


def note_name(phrase: str) -> str:
    return _INVALID.sub("", phrase).strip()


def construction_key(name: str) -> str:
    """Tolerant identity for construction names the model may re-type ('...' for '…',
    a curly apostrophe for a straight one). Case still matters."""
    return note_name(name.replace("...", "…").replace("’", "'")).strip()


def _link(phrase: str) -> str:
    return f"[[{note_name(phrase)}]]"


def _cell(text: str) -> str:
    return str(text).replace("|", "\\|")


def render_daily_body(analysis: Analysis) -> str:
    lines: list[str] = []

    lines.append("## Wins")
    if analysis.wins:
        for w in analysis.wins:
            lines.append(f"- {_link(w.phrase)} — \"{w.quote}\"")
    else:
        lines.append("- (none this time)")
    lines.append("")

    lines.append("## Focus pattern")
    fp = analysis.focus_pattern
    if fp:
        lines.append(f"**{_link(fp.pattern)}** — {fp.explanation}")
        lines.append("")
        lines.append("| fix |")
        lines.append("| --- |")
        for ex in fp.examples:
            lines.append(f"| {_cell(render_fix(ex.before, ex.after))} |")
    else:
        lines.append("(none this time)")
    lines.append("")

    lines.append("## Recurring patterns")
    if analysis.recurring:
        lines.append("| pattern | fix |")
        lines.append("| --- | --- |")
        for r in analysis.recurring:
            lines.append(f"| {_link(r.pattern)} | {_cell(render_fix(r.before, r.after))} |")
    else:
        lines.append("(none this time)")
    lines.append("")

    lines.append("## New phrases")
    if analysis.new_phrases:
        for np in analysis.new_phrases:
            lines.append(f"- {_link(np.phrase)} — {np.meaning} (e.g. \"{np.example}\")")
    else:
        lines.append("- (none this time)")
    lines.append("")

    lines.append("## Constructions used")
    if analysis.construction_wins:
        for w in analysis.construction_wins:
            lines.append(f"- {_link(w.phrase)} — \"{w.quote}\"")
    else:
        lines.append("- (none this time)")
    lines.append("")

    lines.append("## Try this construction")
    if analysis.missed_constructions:
        lines.append("| construction | fix |")
        lines.append("| --- | --- |")
        for m in analysis.missed_constructions:
            lines.append(f"| {_link(m.construction)} | {_cell(render_fix(m.before, m.after))} |")
    else:
        lines.append("(none this time)")
    lines.append("")

    if analysis.new_constructions:
        lines.append("## New constructions")
        for nc in analysis.new_constructions:
            lines.append(f"- {_link(nc.construction)} — {nc.rule} (e.g. \"{nc.example}\")")
        lines.append("")

    lines.append("## Snapshot")
    if analysis.snapshot:
        for s in analysis.snapshot:
            lines.append(f"- {s}")
    else:
        lines.append("- (none this time)")

    return "\n".join(lines)


_CELL_SEP = re.compile(r'(?<!\\)\|')
# Old daily table header → (new header, number of leading cells kept as they are)
_OLD_TABLES = {("before", "after"): ("| fix |", 0),
               ("pattern", "before", "after"): ("| pattern | fix |", 1),
               ("construction", "you wrote", "try"): ("| construction | fix |", 1)}


_COACH_SECTIONS = {"Focus pattern", "Recurring patterns", "Try this construction"}


def _cells(row: str) -> list[str]:
    return [c.strip() for c in _CELL_SEP.split(row.strip()[1:-1])]


def reformat_daily_body(body: str) -> str:
    """Convert old before/after daily tables (also column-aligned ones) to the inline-fix
    columns. Every other line is left alone; already-converted tables are unchanged."""
    out: list[str] = []
    keep = None  # leading cells kept as they are, while inside an old table
    section = ""
    for line in body.split("\n"):
        s = line.strip()
        if s.startswith("## "):
            section = s[3:].strip()
        is_row = s.startswith("|") and s.endswith("|") and len(s) > 1
        hdr = tuple(_cells(s)) if is_row else ()
        if hdr in _OLD_TABLES and section in _COACH_SECTIONS:
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


def write_daily_note(vault: Path, window: Window, prompt_count: int, analysis: Analysis) -> Path:
    basename = note_basename(window.days)
    path = Path(vault) / "Daily" / f"{basename}.md"
    frontmatter = {
        "from": window.days[0],
        "to": window.days[-1],
        "prompt_count": prompt_count,
        "reused": list(analysis.reused_phrases),
        "constructions_used": list(dict.fromkeys(w.phrase for w in analysis.construction_wins)),
        "constructions_missed": [m.construction for m in analysis.missed_constructions],
    }
    write_note(path, frontmatter, render_daily_body(analysis))
    return path


from datetime import date as _date

from english_coach.frontmatter import read_note


def ensure_phrase_note(vault: Path, phrase: str, introduced: _date,
                       meaning: str = "", example: str = "") -> Path:
    path = Path(vault) / "Phrases" / f"{note_name(phrase)}.md"
    if path.exists():
        return path
    frontmatter = {
        "phrase": phrase,
        "introduced": introduced,
        "status": "backlog",
        "reuse_count": 0,
        "tags": ["phrase"],
    }
    body_lines = [f"# {phrase}", ""]
    if meaning:
        body_lines.append(meaning)
    if example:
        body_lines += ["", f"> {example}"]
    write_note(path, frontmatter, "\n".join(body_lines))
    return path


_RULE_MARKER = "**Rule:**"
_EX_HEADER = "## Before → after"
_EX_RE = re.compile(r'^- ✗ (?P<before>.+?) → ✓ (?P<after>.+?)(?:\s+·\s+_(?P<tag>.+?)_)?$')
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


def _short_date(label: str) -> str:
    m = re.match(r'^\d{4}-(\d{2}-\d{2})(?:_to_(\d{2}-\d{2}))?$', label or "")
    if not m:
        return label or ""
    return f"{m.group(1)}–{m.group(2)}" if m.group(2) else m.group(1)


def _extract_rule(body: str) -> str:
    for line in body.splitlines():
        s = line.strip()
        if s.startswith(_RULE_MARKER):
            return s[len(_RULE_MARKER):].strip()
    # Old-format fallback: first real paragraph after the title.
    for line in body.splitlines():
        s = line.strip()
        if s and not s.startswith("#") and not s.startswith("|") and s != "## Examples":
            return s
    return "(rule to be added)"


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


def _render_pattern_note(pattern: str, rule: str, pairs: list[tuple[str, str, str]]) -> str:
    lines = [f"# {pattern}", "", f"{_RULE_MARKER} {rule}", "", _EX_HEADER]
    if pairs:
        lines += [example_line(b, a, t) for b, a, t in pairs]
    else:
        lines.append("_(no examples yet)_")
    return "\n".join(lines)


def ensure_pattern_note(vault: Path, pattern: str, description: str = "") -> Path:
    path = Path(vault) / "Patterns" / f"{note_name(pattern)}.md"
    if path.exists():
        return path
    body = _render_pattern_note(pattern, description or "(rule to be added)", [])
    write_note(path, {"pattern": pattern, "tags": ["pattern"]}, body)
    return path


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
    seen = {(text_key(b), text_key(a)) for b, a, _ in pairs}
    new = []
    for b, a, t in rows:
        b, a = b.strip(), a.strip()
        if (text_key(b), text_key(a)) not in seen:
            seen.add((text_key(b), text_key(a)))
            new.append((b, a, t))
    if not new:
        return
    lines = body.split("\n")
    try:
        i = next(k for k, line in enumerate(lines) if line.strip() == _EX_HEADER)
    except StopIteration:  # old dated-table note: rebuild it in the current format
        write_note(path, fm, _render_pattern_note(pattern, _extract_rule(body), pairs + new))
        return
    # Insert at the end of the examples section, keeping the learner's own lines and sections.
    j = i + 1
    while j < len(lines) and not lines[j].strip().startswith("#"):
        j += 1
    while j > i + 1 and not lines[j - 1].strip():
        j -= 1
    kept = [line for line in lines[i + 1:j] if line.strip() != "_(no examples yet)_"]
    lines[i + 1:j] = kept + [example_line(b, a, t) for b, a, t in new]
    write_note(path, fm, "\n".join(lines))


def read_known_patterns(vault: Path) -> list[tuple[str, str]]:
    """(name, rule) for every pattern note — the analyzer reuses these names verbatim."""
    folder = Path(vault) / "Patterns"
    if not folder.is_dir():
        return []
    out: list[tuple[str, str]] = []
    for path in sorted(folder.glob("*.md")):
        fm, body = read_note(path)
        rule = _extract_rule(body)
        out.append((fm.get("pattern") or path.stem,
                    "" if rule == "(rule to be added)" else rule))
    return out


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
            try:
                fm, body = read_note(path)
                new = convert(body)
                if new == body:
                    continue
                if fm:
                    write_note(path, fm, new)
                else:
                    path.write_text(new.strip() + "\n", encoding="utf-8")
                count += 1
            except Exception as exc:  # one unreadable note must not block the rest
                print(f"Reformat skipped {folder}/{path.name}: {exc}", file=sys.stderr)
    return count


def write_quiet_note(vault: Path, window: Window) -> Path:
    basename = note_basename(window.days)
    path = Path(vault) / "Daily" / f"{basename}.md"
    frontmatter = {
        "from": window.days[0],
        "to": window.days[-1],
        "prompt_count": 0,
        "reused": [],
        "constructions_used": [],
        "constructions_missed": [],
    }
    write_note(path, frontmatter, "Quiet day — no substantive prompts to coach.")
    return path


def apply_analysis_notes(vault: Path, analysis: Analysis, introduced: _date, day_label: str) -> None:
    for np in analysis.new_phrases:
        ensure_phrase_note(vault, np.phrase, introduced=introduced,
                           meaning=np.meaning, example=np.example)
    if analysis.focus_pattern:
        fp = analysis.focus_pattern
        ensure_pattern_note(vault, fp.pattern, fp.explanation)
        append_pattern_examples(vault, fp.pattern,
                                [(ex.before, ex.after) for ex in fp.examples], day_label)
    for r in analysis.recurring:
        ensure_pattern_note(vault, r.pattern)
        append_pattern_examples(vault, r.pattern, [(r.before, r.after)], day_label)
    from english_coach import constructions  # local: constructions imports this module
    constructions.apply_construction_notes(vault, analysis, introduced, day_label)


from english_coach.models import PhraseInfo


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


def read_phrasebook(vault: Path) -> list[PhraseInfo]:
    phrases_dir = Path(vault) / "Phrases"
    out: list[PhraseInfo] = []
    if not phrases_dir.exists():
        return out
    for pnote in sorted(phrases_dir.glob("*.md")):
        fm, _ = read_note(pnote)
        out.append(PhraseInfo(
            phrase=fm.get("phrase", pnote.stem),
            status=fm.get("status", "backlog"),
            reuse_count=int(fm.get("reuse_count", 0)),
        ))
    return out


_DASHBOARD = """# English Coaching

Your automated English-coaching vault. The curator keeps a small active set;
everything else waits in the backlog. Open the graph view to see how days,
phrases, constructions and patterns connect.

## Currently practicing

```dataview
TABLE priority, theme, reuse_count, last_used
FROM "Phrases"
WHERE status = "active"
SORT priority ASC
```

## By theme

```dataview
TABLE rows.file.link AS phrases
FROM "Phrases"
WHERE status = "active" OR status = "backlog"
GROUP BY theme
```

## Backlog

```dataview
TABLE priority, theme, introduced
FROM "Phrases"
WHERE status = "backlog"
SORT priority ASC
LIMIT 15
```

## Adopted

```dataview
TABLE reuse_count, last_used
FROM "Phrases"
WHERE status = "adopted"
SORT reuse_count DESC
```

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

## Recent days

```dataview
TABLE prompt_count, reused, constructions_used
FROM "Daily"
SORT to DESC
LIMIT 14
```
"""


def write_dashboard(vault: Path) -> Path:
    path = Path(vault) / "English Coaching.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_DASHBOARD, encoding="utf-8")
    return path


# --- Phrase enrichment (definition + sample usage) --------------------------

_DEF_MARKER = "**Definition:**"


def read_phrase_entries(vault: Path) -> list[dict]:
    """One entry per phrase note: name, phrase, any real quote, and whether it's
    already enriched (has a Definition section)."""
    phrases_dir = Path(vault) / "Phrases"
    out: list[dict] = []
    if not phrases_dir.exists():
        return out
    for pnote in sorted(phrases_dir.glob("*.md")):
        fm, body = read_note(pnote)
        quote = None
        for line in body.splitlines():
            s = line.strip()
            if s.startswith(">"):
                quote = s.lstrip(">").strip().strip('"')
                break
        out.append({
            "note_name": pnote.stem,
            "phrase": fm.get("phrase", pnote.stem),
            "your_quote": quote,
            "enriched": _DEF_MARKER in body,
        })
    return out


# --- Curation (status/priority/theme lifecycle) ------------------------------


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


def apply_curation(vault: Path, updates: dict[str, dict], folder: str = "Phrases") -> int:
    """Apply curator decisions: updates maps note_name -> {status, priority, theme}.

    Frontmatter-only; adopted notes and unknown note names are skipped. Returns
    the number of notes whose frontmatter actually changed."""
    phrases_dir = Path(vault) / folder
    count = 0
    for name, upd in updates.items():
        path = phrases_dir / f"{name}.md"
        if not path.exists():
            continue
        fm, body = read_note(path)
        if fm.get("status") == "adopted":
            continue
        new_fm = dict(fm)
        new_fm["status"] = upd["status"]
        new_fm["priority"] = upd["priority"]
        new_fm["theme"] = upd["theme"]
        if new_fm != fm:
            write_note(path, new_fm, body)
            count += 1
    return count


def write_enriched_phrase_note(vault: Path, note_name: str, phrase: str,
                               definition: str, examples: list[str],
                               your_quote: str | None = None) -> Path:
    """Rewrite a phrase note body to the rich flashcard format, keeping its frontmatter."""
    path = Path(vault) / "Phrases" / f"{note_name}.md"
    fm, _ = read_note(path)
    lines = [f"# {phrase}", "", f"{_DEF_MARKER} {definition}", "", "**Examples**"]
    lines += [f"- {ex}" for ex in examples]
    if your_quote:
        lines.append(f'- *(you said)* "{your_quote}"')
    write_note(path, fm, "\n".join(lines))
    return path


_WIN_RE = re.compile(r'^- \[\[(?P<phrase>.+?)\]\]\s*[—-]+\s*"(?P<quote>.+)"\s*$')


def collect_win_quotes(vault: Path) -> dict:
    """Map note_name -> a genuinely real quote of the user's, harvested from the
    'Wins' lines of daily notes (those quote the user's actual prompts). Later
    days overwrite earlier ones, so the most recent real usage wins."""
    daily = Path(vault) / "Daily"
    out: dict = {}
    if not daily.exists():
        return out
    for note in sorted(daily.glob("*.md")):
        _, body = read_note(note)
        for line in body.splitlines():
            m = _WIN_RE.match(line.strip())
            if m:
                out[note_name(m.group("phrase"))] = m.group("quote")
    return out


def enrich_phrase_notes(vault: Path, enricher, force: bool = False, examples_per_phrase: int = 3) -> int:
    """Fill in Definition + example sentences for phrase notes.

    `enricher` is a callable taking [{"phrase","your_quote"}] and returning
    {phrase: {"definition", "examples"}}. By default only notes without a
    Definition are (re)generated; `force=True` regenerates all. The '(you said)'
    line is sourced only from real daily-note Wins quotes, never from AI-generated
    example text. Returns the count enriched.
    """
    entries = read_phrase_entries(vault)
    todo = entries if force else [e for e in entries if not e["enriched"]]
    if not todo:
        return 0
    win_quotes = collect_win_quotes(vault)
    data = enricher([{"phrase": e["phrase"], "your_quote": win_quotes.get(e["note_name"])} for e in todo])
    count = 0
    for e in todo:
        d = data.get(e["phrase"])
        if not d:
            continue
        write_enriched_phrase_note(vault, e["note_name"], e["phrase"],
                                   d.get("definition", ""), d.get("examples", []),
                                   win_quotes.get(e["note_name"]))
        count += 1
    return count


def enrich_pattern_notes(vault: Path, enricher, force: bool = False) -> int:
    """Regenerate the Rule for pattern notes (and migrate old dated-table notes to
    the study-card list format). `enricher` takes
    [{"pattern","description","examples":[(before,after),...]}] and returns
    {pattern: {"rule"}}. Only un-enriched notes are done unless force=True.
    Returns the count enriched."""
    pat_dir = Path(vault) / "Patterns"
    if not pat_dir.exists():
        return 0
    entries = []
    for note in sorted(pat_dir.glob("*.md")):
        fm, body = read_note(note)
        entries.append({"note": note, "pattern": fm.get("pattern", note.stem),
                        "fm": fm, "body": body, "enriched": bool(fm.get("enriched"))})
    todo = entries if force else [e for e in entries if not e["enriched"]]
    if not todo:
        return 0
    items = [{"pattern": e["pattern"], "description": _extract_rule(e["body"]),
              "examples": [(b, a) for b, a, _ in _parse_pattern_examples(e["body"])]} for e in todo]
    data = enricher(items)
    count = 0
    for e in todo:
        d = data.get(e["pattern"])
        if not d:
            continue
        pairs = _parse_pattern_examples(e["body"])
        fm = dict(e["fm"])
        fm["enriched"] = True
        write_note(e["note"], fm, _render_pattern_note(e["pattern"], d.get("rule", ""), pairs))
        count += 1
    return count
