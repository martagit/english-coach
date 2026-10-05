# English Coach — Inline Fix Highlighting Design

Date: 2026-10-05
Status: Draft — awaiting review

## Goal

Make every before → after correction readable at a glance. Today each one shows two full
sentences side by side, and the learner has to compare them word by word to find the one or two
words that changed. Instead, show **one** sentence with the change marked inline:

> I can paste ~~to~~ **into the** team channel · _09-25_

Also keep pattern Rules in step with their examples, and shorten date tags.

### Success criteria

- Every place that shows a correction uses the inline format:
  - pattern notes;
  - the "Try it next time" list in construction notes;
  - the daily Focus pattern, Recurring patterns and Try this construction tables.
- The original "before" and "after" can always be recovered from the rendered text, so
  deduplication, enrichment and the re-split keep working.
- Existing notes are reformatted automatically on the next `run`. No Claude call is made, and
  re-running changes nothing.
- When `enrich --resplit --apply` adds examples to a note or removes them, that note's Rule is
  rewritten.
- Range tags like `2026-09-25_to_09-27` show as `09-25–09-27`.

### Decisions made during brainstorming

| Topic | Decision |
|---|---|
| Format | Option A: highlighted corrected sentence (not trimmed fragments, not two-line cards) |
| Scope | Everywhere: pattern notes, construction notes, all three daily tables |
| Existing notes | Reformatted automatically on the next run, including old daily notes |
| Storage of "before" | Rebuilt from the markup; no hidden comments or frontmatter |
| Stale Rules | The re-split clears `enriched` on notes whose examples changed |

### Non-goals

- Trimming long sentences to the part around the change.
- Highlighting inside Wins, phrase notes or construction "You used it" quotes (no correction there).
- An LLM-written diff; the diff is computed in code.

## Fix markup (`english_coach/fix_markup.py`, new)

### Rendering: `render_fix(before: str, after: str) -> str`

1. Tokenise both into words (`\w+` plus `'` inside words), single punctuation characters and
   whitespace runs.
2. Run `difflib.SequenceMatcher` over the non-whitespace tokens.
3. Equal chunks are copied as they are. A deleted chunk becomes `~~old~~` and an inserted chunk
   `**new**`. A replaced chunk becomes `~~old~~ **new**`. Markers always hug the text: no space
   just inside `~~` or `**`, which Markdown requires.
4. **Fallback:** if the token similarity ratio is below 0.5, render `~~before~~ → **after**`.
5. Literal `*` and `~` in the learner's text are escaped as `\*` and `\~`, so they can't be
   mistaken for markup.
6. If before and after are identical, render the text unmarked.

Examples (from the learner's vault):

| before | after | rendered |
|---|---|---|
| I can paste to team channel | I can paste into the team channel | I can paste ~~to~~ **into the** team channel |
| Draft an explanation what happened | Draft an explanation of what happened | Draft an explanation **of** what happened |
| every day one ticket by component is created | every day, one ticket per component is created | every day**,** one ticket ~~by~~ **per** component is created |

### Parsing: `parse_fix(text: str) -> tuple[str, str]`

- **before** = the text with each `**…**` removed and each `~~…~~` unwrapped.
- **after** = the text with each `~~…~~` removed and each `**…**` unwrapped.
- The ` → ` between the two halves of a fallback rendering is removed.
- Escapes are undone, and whitespace is collapsed to single spaces.

**Round-trip contract:** `parse_fix(render_fix(b, a)) == (norm(b), norm(a))`, where `norm`
collapses whitespace. Any comparison of examples (deduplication in `append_pattern_examples_tagged`,
the re-split's matching) compares normalised pairs.

## Where it is used

| Place | New format | Read back by |
|---|---|---|
| Pattern notes (`vault._render_pattern_note`) | `- <fix>  · _tag_` | `_parse_pattern_examples` |
| Construction notes, "Try it next time" (`constructions._missed_line`) | `- <fix>  · _tag_` | `_MISSED_RE` → new-format parser |
| Daily Focus pattern table | `\| fix \|` (one column) | `resplit` daily re-link |
| Daily Recurring patterns table | `\| pattern \| fix \|` | `resplit` daily re-link |
| Daily Try this construction table | `\| construction \| fix \|` | nothing |

Table cells still escape `|` (`_cell`).

**Parsers accept both formats.** A list line matching the old `- ✗ b → ✓ a` regex is read as
before. Any other `- ` line in the examples section is read with `parse_fix`. In daily tables
the re-link takes "before" from the first data cell if the header has a `before` column (old
format), or from `parse_fix(fix cell)` if it has a `fix` column.

## Short date tags

`vault._short_date` also shortens range labels: `YYYY-MM-DD_to_MM-DD` → `MM-DD–MM-DD`. Single
days stay `MM-DD`. Old long tags in existing notes are shortened when the notes are reformatted.

## Reformatting existing notes

`vault.reformat_notes(vault) -> int` (new; construction notes via a helper in
`constructions.py`):

- **Pattern notes:** parse, then re-render with `_render_pattern_note`. The Rule, frontmatter and
  title are kept.
- **Construction notes:** rewrite only the "Try it next time" section with `_edit_section`; the
  learner's other sections are untouched.
- **Daily notes:** in the three sections only, convert old-header tables (`| before | after |`,
  `| pattern | before | after |`, `| construction | you wrote | try |`) to the new columns.
  Every other line and the frontmatter stay unchanged.
- A file is written only if its content changed. Returns the number of files written.

`coach.run` calls it at the start of every run, before the window check, fail-soft like the
enrichers: an error is printed and the run continues. Once everything is converted it is a
no-op.

## Rule refresh after a re-split

`resplit.apply_resplit` clears `enriched` on every existing note that received examples and on
every note trimmed to its staying examples. The `enrich_pattern_notes` call at the end of apply
then rewrites their Rules along with the new notes' Rules.

## Testing

- `tests/test_fix_markup.py`:
  - the three example renderings above;
  - pure insertion and pure deletion;
  - punctuation-only changes;
  - the fallback for unrelated sentences;
  - identical sentences;
  - escaping of `*` and `~`;
  - round-trip for all of these.
- Pattern and construction notes:
  - render in the new format;
  - old-format notes still parse;
  - deduplication works across formats (an old-format line and a new example with the same
    pair aren't duplicated).
- Daily notes:
  - new tables render;
  - `reformat_notes` converts old tables in all three sections;
  - unrelated lines and frontmatter are untouched;
  - a second call writes nothing.
- `resplit`:
  - daily re-link works on new-format `fix` cells and old cells;
  - apply clears `enriched` on receiving and trimmed notes.
- `coach.run`:
  - reformatting runs, and its failure doesn't stop the run.
- `_short_date`: range labels.
