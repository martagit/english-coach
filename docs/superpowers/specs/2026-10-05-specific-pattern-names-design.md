# English Coach — Specific Pattern Names Design

Date: 2026-10-05
Status: Draft — awaiting review

## Goal

Make every pattern note teach **one learnable rule**, the way `Articles` does, instead of
catch-all buckets such as `Missing words` that collect unrelated mistakes (prepositions,
connectors, relative pronouns, articles, typos) under a symptom-based name.

### Problem

The analyzer names patterns by the surface symptom ("a word is missing"), not by the rule the
learner needs. `read_known_patterns` then feeds that name back into every analysis prompt with
"reuse verbatim when it applies", so a broad bucket keeps attracting anything loosely related.
The resulting note has a mushy Rule and examples that cannot be studied together.

### Success criteria

- New analyses name patterns after a rule; one sentence of advice fixes every example under a
  name. Catch-all names are not coined, and typos / one-off vocabulary slips are not filed as
  patterns.
- `english-coach enrich --resplit` audits existing pattern notes, previews a plan, and with
  `--apply` moves each example of a broad note into a specific note (keeping its original date
  tag) or drops it, then moves the broad note to the vault's `.trash/` (or, if some examples stay, trims it after backing it up there). `--apply` asks for confirmation of the printed plan.
- Links in old daily notes that pointed at a removed note are rewritten to the note each
  example moved to; daily notes stay clickable and correct.
- Old vaults and old analyzer output keep working; nothing is written without `--apply`.

### Decisions made during brainstorming

| Topic | Decision |
|---|---|
| Note layout | Many small notes, one rule each (no umbrella notes with sub-rule sections) |
| Prevention | Prompt guidance only; no hard-coded block list in `parse_analysis` |
| Curated starter pattern list | Not now (possible follow-up if names still drift) |
| Existing broad notes | One-off LLM re-split via `enrich --resplit`, preview by default |
| Old daily-note links | Rewrite per example; dropped examples become plain text |

### Non-goals

- Umbrella notes or section links (`[[Prepositions#for]]`).
- A curated / per-language pattern taxonomy.
- Changing Phrases or Constructions.
- Pruning patterns with few examples.

## Part 1 — Prevention: naming rule in the analysis prompt

`build_analysis_prompt` (`english_coach/analyzer.py`) replaces the current "short 2-4 word name"
paragraph with guidance that:

1. **Names the rule, not the symptom.** Test: "Could one sentence of advice fix every example
   filed under this name?" Good: "Verb + preposition", "Relative pronouns", "Linking clauses",
   "Articles". Bad: "Missing words", "Word choice", "Grammar", "Wrong word", "Typos".
2. **Reuses a known name only when the example truly fits that pattern's rule** (the rule is
   already listed next to each known name); a loose fit gets a new specific name.
3. **Skips non-patterns:** typos and one-off vocabulary slips go in neither `focus_pattern` nor
   `recurring`.

The existing "copy known names verbatim, put detail in 'explanation'" instruction stays.

**Tests** (`tests/test_analyzer.py`): the prompt contains the one-sentence test, the
catch-all examples, the "truly fits its rule" reuse condition and the skip-typos instruction.

## Part 2 — Re-split of existing notes

### CLI

`english-coach enrich --resplit [--apply] [--vault PATH]` in `cli.py`, next to the existing
`--phrases/--patterns/--constructions` flags. `--resplit` runs alone (not part of the default
"enrich everything" run). Without `--apply` it prints the plan and writes nothing.

### Audit call (`analyzer.py`)

`build_pattern_resplit_prompt(items, profile)` / `resplit_patterns(items, runner, profile)`,
mirroring `enrich_patterns` (one batched call, JSON-only output, one retry on bad JSON).

Input: every pattern note as `{"pattern", "rule", "examples": [(before, after), ...]}`, plus the
naming rule from Part 1.

Output shape:

```json
{"notes": [
  {"pattern": "Articles", "action": "keep"},
  {"pattern": "Missing words", "action": "split", "examples": [
    {"before": "<verbatim>", "target": "Verb + preposition"},
    {"before": "<verbatim>", "target": "Articles"},
    {"before": "<verbatim>", "target": null}
  ]}
]}
```

`target: null` means drop. Parsing is defensive: unknown pattern names and `before` strings that
do not match an example of that note are ignored; a split note whose examples are not all
covered is left untouched (reported as "skipped: incomplete plan") so no example is ever lost.
A `target` equal to the note's own name means the example stays. A note where every example stays is kept; a note that would be fully emptied cannot receive examples (the sending note is skipped).

### Plan preview

Printed per split note, one line per example: `"<before, truncated>" → <target> (new|existing)`
or `→ drop`. Kept notes are summarised in one line. Ends with "Run again with --apply to write
these changes."

### Apply (`vault.py`)

`resplit_pattern_notes(vault, plan, enricher) -> ResplitResult`:

1. For each split note, for each example with a target: `ensure_pattern_note(target)` and add
   the pair with its **original date tag** via a small helper
   `append_pattern_examples_tagged(vault, pattern, rows: [(before, after, tag)])`
   (shares dedup/render logic with `append_pattern_examples`).
2. Re-link daily notes (below), then move each emptied note to `.trash/`; a note where some examples stay is backed up to `.trash/` first and trimmed to the staying examples.
3. Rewrite daily-note links (below).
4. Run `enrich_pattern_notes(vault, enricher)` so newly created notes get a Rule (it only
   touches un-enriched notes). Existing target notes keep their Rule.

### Daily-note link rewrite (`vault.py`)

For every `Daily/*.md` containing `[[<removed note name>]]`:

- **Recurring patterns table rows** `| [[Old]] | before | after |`: match the row's `before`
  cell (unescape `\|`, collapse whitespace) against the plan's `before` strings for that note.
  Matched with a target → `[[Target]]`; matched as drop or unmatched → plain text `Old`.
- **Focus pattern line** `**[[Old]]** — …`: the target that most of that note's examples in this
  daily note's focus table went to (ties: first in table order); if none map, plain text.
- Nothing else in the daily note changes; frontmatter is untouched.

Link targets use `note_name()` so they match how `_link` renders.

### Result

`ResplitResult` counts notes split, examples moved, examples dropped, notes created, daily notes
rewritten; `cmd_enrich` prints it.

## Testing

- `test_analyzer.py`: prompt content (Part 1); resplit prompt lists every note and example;
  resplit parsing ignores unknown names / unmatched befores; retry on bad JSON.
- `test_vault_notes.py` (or new `test_vault_resplit.py`), with fake plans:
  - examples land in target notes with original date tags, deduped against existing examples;
  - new notes are created and passed to the enricher; existing notes keep their Rule;
  - the broad note is moved to `.trash/`; kept notes are untouched;
  - incomplete plan → note left untouched and reported;
  - daily notes: recurring rows re-linked per example, dropped/unmatched → plain text, focus
    line → majority target, unrelated content and frontmatter unchanged;
  - preview mode writes nothing.
- `test_cli_run.py`: `enrich --resplit` without `--apply` makes no file changes.
