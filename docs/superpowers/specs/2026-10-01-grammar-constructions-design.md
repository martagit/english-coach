# English Coach — Grammar Constructions Design

Date: 2026-10-01
Status: Draft — awaiting review

## Goal

Teach the learner **grammar constructions they never use** — not mistakes (Patterns already cover
those) and not vocabulary (Phrases cover that), but everyday native structures such as
"be supposed to", "What if we…?", "end up + -ing", cleft sentences ("What I don't get is…").

The coach tracks a small active set, notices when the learner uses one correctly, and shows a few
of the learner's own plain sentences rewritten with an active construction ("missed
opportunities").

### Success criteria

- A new `Constructions/` folder with one note per construction, same lifecycle as Phrases
  (`backlog` → `active` → `adopted`), curated by the same curator logic with its own cap.
- Each daily note shows **Constructions used** (real quotes) and **Try this construction**
  (before → after rewrites of the learner's real sentences).
- Existing vaults get a starter set seeded automatically on the next run; no manual step.
- Old analyzer output without the new keys still parses (no crash, empty sections).
- Nothing personal in the shipped starter list (`test_no_personal_data.py` stays green).

### Decisions made during brainstorming

| Topic | Decision |
|---|---|
| Storage | Separate `Constructions/` folder, not a `kind` field on Phrases |
| Detection | Model-judged inside the existing analysis call; no regex |
| Missed opportunities | Shown and counted, but never reduce progress |
| New constructions | Starter list + at most 1 proposed per run, grounded in the learner's text |
| Active cap | 3 (separate from the phrase cap of 12) |
| Adoption | Used correctly on 5 distinct daily notes (phrases stay at 3) |

### Non-goals

- Regex/heuristic detection of constructions.
- Changing Patterns or Phrases behaviour.
- Penalising missed opportunities or demoting constructions because of them.
- Grammar exercises/quizzes.

## Data model (`models.py`)

```python
@dataclass(frozen=True)
class MissedConstruction:
    construction: str   # exact construction name from the list given to the model
    before: str         # learner's real sentence, verbatim
    after: str          # same sentence rewritten using the construction

@dataclass(frozen=True)
class NewConstruction:
    construction: str   # short name, e.g. "end up + -ing"
    rule: str           # 1-2 sentences: form and when natives use it
    example: str        # learner's sentence rewritten with it

@dataclass(frozen=True)
class ConstructionInfo:
    construction: str
    status: str
    reuse_count: int
    rule: str
```

`Analysis` gains three fields, all defaulting to empty lists (`field(default_factory=list)`) so
existing call sites and tests keep working:

- `construction_wins: list[Win]` — `Win(phrase=<construction name>, quote=<verbatim quote>)`
- `missed_constructions: list[MissedConstruction]`
- `new_constructions: list[NewConstruction]`

The daily frontmatter's `constructions_used` is derived from `construction_wins` (distinct names).

## Analyzer (`analyzer.py`)

`build_analysis_prompt` and `ClaudeAnalyzer.analyze` / `ClaudeCliAnalyzer.analyze` take a new
`constructions: list[ConstructionInfo] = ()` argument. The prompt gets a new block after the
phrasebook:

```
Grammar constructions the learner is practicing (name | status | rule):
- be supposed to | active | ...
...
```

Instructions added to the prompt:

- `construction_wins`: for any listed non-adopted construction the learner **actually used
  correctly**, the construction name verbatim + the verbatim quote. Subset of the list only.
- `missed_constructions`: at most 3, **only for `active` constructions**, only where the rewrite
  is clearly more natural than what the learner wrote (not merely different). `before` is a
  verbatim quote; `after` keeps the meaning.
- `new_constructions`: at most `max_new_constructions` (default 1); only an everyday native
  construction that the learner's prompts show they avoid; never a variant of a listed one, of a
  phrasebook phrase, or of a known pattern. Empty list is fine.

Both output-shape definitions are updated — `ANALYSIS_TOOL["input_schema"]` (API backend) and
`_CLI_JSON_INSTRUCTION` (CLI backend). The three new keys are **not** in `required`, and the CLI
instruction text changes from "all six keys required" to list the six required keys and the three
optional ones.

`parse_analysis` reads the new keys with `.get(key, [])`, skips malformed items individually,
drops `construction_wins` / `missed_constructions` whose name is not in the provided construction
list, truncates `missed_constructions` to 3 and `new_constructions` to `max_new_constructions`.
To filter by name, `parse_analysis` gets an optional `known_constructions: set[str] | None`
(None = no filtering, keeps existing tests unchanged).

### Construction enrichment

New `enrich_constructions(items, runner, profile)` mirroring `enrich_phrases`: one batched call,
input `[{"construction", "rule", "your_quote"}]`, output
`{construction: {"rule": str, "examples": [str, str, str]}}`. New preamble
`CONSTRUCTION_ENRICH_PREAMBLE = "You explain everyday English grammar constructions"`.

## Coach prompts (`coach_prompts.py`)

Add `CONSTRUCTION_ENRICH_PREAMBLE` and `CONSTRUCTION_CURATOR_PREAMBLE` (see curator) to
`COACH_PROMPT_PREFIXES` so the transcript reader keeps excluding the coach's own calls.

## Vault (`vault.py`)

### Construction notes — `Constructions/<name>.md`

```markdown
---
construction: be supposed to
introduced: 2026-10-01
status: backlog
reuse_count: 0
missed_count: 0
tags: [construction]
---
# be supposed to

**Rule:** Use "be supposed to + verb" for what should happen according to a plan, design or
expectation.

**Examples**
- The job is supposed to retry three times before it gives up.
- ...

## You used it
- "..."  · _10-01_

## Try it next time
- ✗ ... → ✓ ...  · _10-01_
```

Functions:

- `ensure_construction_note(vault, name, introduced, rule="", example="")` — create if missing
  (status `backlog`), like `ensure_phrase_note`.
- `append_construction_evidence(vault, name, used_quotes, missed_pairs, day_label)` — append to
  "You used it" / "Try it next time", deduplicated, keeping frontmatter.
- `read_constructions(vault) -> list[ConstructionInfo]` — rule parsed from the `**Rule:**` line.
- `seed_constructions(vault, introduced)` — if `Constructions/` is missing or contains no `.md`
  files, create one note per starter entry (see Starter list). Never re-creates notes the user
  deleted once the folder has any note.
- `apply_analysis_notes` also creates notes for `new_constructions` and appends evidence for
  `construction_wins` and `missed_constructions`.

### Daily note

Frontmatter gains `constructions_used: [names]` and `constructions_missed: [names]` (one entry per
missed item, duplicates allowed so the count is real). Body gains two sections between
"New phrases" and "Snapshot":

```markdown
## Constructions used
- [[be supposed to]] — "Isn't it supposed to be cancelled here?"

## Try this construction
| construction | you wrote | try |
| --- | --- | --- |
| [[What if we…]] | compare to the option to inherit from IEntity | What if we just inherited from IEntity? |
```

Plus a "New constructions" bullet list when `new_constructions` is non-empty. Empty sections
render "(none this time)" like the existing ones. Quiet notes get empty lists.

### Reuse recomputation

`recompute_reuse` is generalised to an internal helper
`_recompute(vault, folder, daily_key, threshold, missed_key=None)` and called twice:

- Phrases: folder `Phrases`, key `reused`, threshold `adopted_threshold` (unchanged behaviour).
- Constructions: folder `Constructions`, key `constructions_used`, threshold
  `construction_adopted_threshold`; also writes `missed_count` from `constructions_missed`.

`recompute_reuse(vault, adopted_threshold, construction_adopted_threshold=5)` keeps its current
signature working.

### Dashboard

New sections after "Adopted":

```
## Constructions — practicing
TABLE priority, theme, reuse_count, missed_count, last_used
FROM "Constructions" WHERE status = "active" SORT priority ASC

## Constructions — backlog
TABLE priority, theme FROM "Constructions" WHERE status = "backlog" SORT priority ASC LIMIT 15

## Constructions — adopted
TABLE reuse_count, last_used FROM "Constructions" WHERE status = "adopted" SORT reuse_count DESC
```

"Recent days" adds the `constructions_used` column. `write_dashboard` already overwrites on every
run, so existing vaults pick this up automatically.

## Curator (`curator.py`)

The curator becomes item-kind aware via a small `CurationKind` dataclass:

```python
@dataclass(frozen=True)
class CurationKind:
    folder: str          # "Phrases" | "Constructions"
    name_key: str        # "phrase" | "construction"
    preamble: str        # CURATOR_PREAMBLE | CONSTRUCTION_CURATOR_PREAMBLE
    noun: str            # "phrases" | "grammar constructions"
    theme_examples: str
```

`PHRASES` and `CONSTRUCTIONS` constants. `build_curation_prompt`, `curate`,
`vault.read_curation_inventory` and `vault.apply_curation` take `kind=PHRASES` by default, so
existing callers and tests are unchanged. The JSON shape keeps the `"phrases"` list key and
`"phrase"` item key for both kinds (internal protocol, avoids a second parser). Construction
themes: e.g. "suggesting", "expectations", "hypotheticals", "linking ideas", "softening".
`CONSTRUCTION_CURATOR_PREAMBLE = "You curate a personal list of English grammar constructions"`.

Construction curation additionally sends `missed_count` so the curator can favour constructions
the learner keeps missing.

## Starter list (`english_coach/assets/constructions.toml`)

Generic, no personal sentences. ~15 entries, each `name`, `rule`, `example`, `priority`, `theme`:

1. be supposed to — expectations
2. What if we…? — suggesting
3. How about + -ing? — suggesting
4. Is it worth + -ing? — suggesting
5. end up + -ing / with — results
6. What I don't get is… / The thing is… (cleft) — emphasis
7. …, which + verb (linking a whole clause) — linking ideas
8. I'd rather (not) / I'd rather we… — preferences
9. should have / shouldn't have + past participle — hindsight
10. unless — conditions
11. as long as — conditions
12. in that case / otherwise — conditions
13. make sure (that) — instructions
14. …, right? (confirmation tag) — softening
15. Second conditional (If we merged…, would…) — hypotheticals
16. get + object + -ing / past participle (get it working) — results

Seeding sets the top 3 by priority to `active`, the rest `backlog`. Loaded with `tomllib` via
`importlib.resources` (already used for Obsidian assets); shipped automatically: hatchling packages
every file under `english_coach/`, as it already does for the Obsidian assets.

## Orchestration (`coach.py`, `cli.py`, `config.py`, `skeleton.py`)

`coach.run` order with prompts:

1. `vault.seed_constructions(...)` (also on quiet days)
2. read phrasebook, patterns, **constructions**
3. `analyzer.analyze(prompts, phrasebook, known_patterns, constructions)`
4. write daily note, apply analysis notes, `recompute_reuse` (both kinds)
5. phrase curator, **construction curator** (each fail-soft independently)
6. dashboard
7. phrase/pattern/**construction** enrichers (fail-soft)

`run` gets `construction_curator=None, construction_enricher=None` keyword args.

`Config` gains `max_active_constructions=3`, `max_new_constructions=1`,
`construction_adopted_threshold=5`, read from / saved to `[limits]`.

`cli.py` wires the new curator/enricher in `execute_run`; `english-coach enrich` gains
`--constructions` (and the no-flag default enriches all three kinds).

`skeleton._FOLDERS` adds `Constructions`; `create_skeleton` seeds the starter list.

## Error handling

- Construction curator / enricher failures are fail-soft (stderr message), same as today.
- Malformed construction items in analyzer output are dropped individually.
- Missing/corrupt starter asset: seeding raises — it is a packaging bug and tests cover it.

## Testing

New/extended tests (pytest, existing fakes/injected runners):

- `test_analyzer.py`: prompt contains the constructions block and the active-only rule; parsing
  with and without the new keys; unknown construction names dropped; caps enforced; CLI JSON
  instruction mentions the new keys.
- `test_vault_constructions.py` (new): seed creates notes once and not again; seeded active count
  = 3; `ensure_construction_note` idempotent; evidence appended and deduplicated; daily note
  sections + frontmatter; `recompute_reuse` counts `constructions_used`, writes `missed_count`,
  adopts at 5, phrase behaviour unchanged.
- `test_curator.py`: construction kind prompt wording, cap of 3, `missed_count` in the listing.
- `test_transcripts.py`: new preambles are skipped.
- `test_cli_run.py` / `test_coach.py`: run wires construction curator/enricher; curator failure
  is fail-soft.
- `test_config.py`: new limits load/save with defaults.
- `test_skeleton.py`: `Constructions/` created and seeded.
- `test_no_personal_data.py`: extend `SCANNED` to include `english_coach/assets/*.toml`.
