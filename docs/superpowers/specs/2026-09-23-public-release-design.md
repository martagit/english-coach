# English Coach — Public Release Design

Date: 2026-09-23
Status: Draft — awaiting review

## Goal

Publish a public, open-source version of English Coach on GitHub that **anyone** who uses
Claude Code can set up in a few minutes on Windows, macOS, or Linux.

English Coach reads the prompts a user typed into Claude Code, sends them to Claude for
analysis once a day, and maintains an Obsidian vault of daily coaching notes, phrase notes,
grammar-pattern notes, and a Dataview dashboard.

### Success criteria

- A new user goes from zero to a populated vault with **two commands** (after installing `uv`
  and Obsidian):
  1. `uv tool install git+https://github.com/<owner>/english-coach`
  2. `english-coach init`
- No Docker, no Langfuse, no MCP config, no hardcoded paths, no API key required by default.
- Daily runs happen automatically and catch up after the machine was off.
- Works on Windows, macOS, and Linux; CI proves it on all three.
- Nothing user-specific (paths, native language, personal seed patterns) remains in the code.

### Decisions made during brainstorming

| Topic | Decision |
|---|---|
| Audience | Public, anyone (not company-internal) |
| Prompt source | Local Claude Code transcripts only; Langfuse removed |
| Install | `uv tool install` + interactive `english-coach init` wizard |
| Scheduling | OS-native scheduler, registered by `init` |
| Dataview | Bundled in the vault skeleton, pinned version |
| Repo | New folder / fresh git repo (`english-coach-public`); the existing private copy stays untouched |

### Non-goals

- Langfuse or any other remote prompt source.
- A Claude Code plugin / slash command (possible later as a thin layer).
- Changing the coaching logic itself (analyzer JSON schema, curator guardrails, note formats).
- Supporting prompts from tools other than Claude Code.

## Architecture

```
english_coach/
  cli.py            # `english-coach` entry point, subcommands
  config.py         # TOML config + secrets, OS-standard locations
  transcripts.py    # NEW — reads ~/.claude/projects/**/*.jsonl  (replaces langfuse_client.py)
  filtering.py      # existing noise filters, unchanged
  window.py         # existing watermark/window logic
  state.py          # existing watermark state
  lock.py           # NEW — single-instance run lock
  analyzer.py       # existing; system prompt now built from learner profile
  curator.py        # existing, unchanged
  vault.py          # existing; seeding no longer uses personal content
  init_wizard.py    # NEW — `init` flow
  doctor.py         # NEW — health checks
  scheduler/
    __init__.py     # common interface: install(time), remove(), status()
    windows.py      # Task Scheduler
    macos.py        # launchd user agent
    linux.py        # systemd user timer (cron fallback: print line only)
  assets/
    vault/          # dashboard template + .obsidian/ with pinned Dataview
```

Existing modules not listed (`models.py`, `frontmatter.py`) move over unchanged.
`langfuse_client.py` and the MCP-json credential loading are deleted. `seed.py`'s personal
patterns and idioms are removed; a new vault starts empty.

### Units and interfaces

- **`transcripts.read_prompts(projects_dir, start_utc, end_utc, exclude_cwd) -> list[UserPrompt]`**
  Pure function over the filesystem; returns prompts in the window, plus skip counters for
  `doctor`. Knows nothing about the vault or the LLM.
- **`scheduler.<os>`** — each module implements `install(time: str, command: list[str])`,
  `remove()`, `status() -> ScheduleStatus`. Each also exposes a pure `render(...)` that
  returns the task XML / plist / unit text so it can be tested without registering anything.
- **`lock.run_lock(path)`** — context manager; raises `AlreadyRunning` if held by a live run.
- **`config.load() / config.save()`** — the only place that knows file locations.

## Configuration

Location: OS config directory via the `platformdirs` package (`user_config_dir("english-coach")`, new dependency)
(`%APPDATA%\english-coach\`, `~/Library/Application Support/english-coach/`,
`~/.config/english-coach/`).

`config.toml`:

```toml
vault_path = "~/english-coach-vault"
timezone = "Europe/Warsaw"          # detected at init, user-confirmable
backend = "cli"                     # "cli" | "api"
model = "claude-opus-5-5"           # used by api backend; passed to cli via --model
schedule_time = "07:00"

[profile]
native_language = "Polish"          # empty = not specified
context = "software developer"      # one line; shapes examples and idiom choice

[limits]
adopted_threshold = 3
max_active = 12
max_new_phrases = 2
```

Secrets: `ANTHROPIC_API_KEY` env var, else `secrets.toml` next to `config.toml`, created with
user-only permissions (chmod 600 on POSIX; default per-user ACL under `%APPDATA%` on Windows).
Only needed for `backend = "api"`.

Other files in the config dir: `state.json` (watermark), `run.lock`, `logs/coach.log`
(rotating), `workdir/` (the dedicated cwd for `claude -p`, see below).

CLI flags (`--vault`, `--backend`, …) override config values for a single run.

## Transcript source

Scan `~/.claude/projects/**/*.jsonl`. Skip files whose mtime is older than the window start.

A line is a **user prompt** only if all hold:

- `type == "user"`
- `isSidechain` is falsy (excludes subagent traffic)
- `isMeta` and `isCompactSummary` are falsy
- `message.content` is a string, or a list containing only `text` (and optionally `image`)
  blocks — lists containing `tool_result` are excluded; only text blocks are kept
- the text does not start with `<command-`, `<local-command-`, or `<system-reminder>`
- `cwd` is not the coach's own `workdir/`

Deduplicate by `uuid` (resumed/forked sessions can replay history). Bucket by the line's
`timestamp`, converted to the configured timezone. Then apply the existing `filtering.py` rules.

Defensive parsing: malformed JSON lines or missing fields are skipped and counted, never fatal.
The counts are written to the run log and surfaced by `doctor`, so a Claude Code format change
is visible rather than silently yielding empty days.

Retention note (documented in README): Claude Code deletes transcripts older than
`cleanupPeriodDays` (default 30) at startup. Daily runs are unaffected; backfill is limited to
what remains on disk.

### Self-exclusion for the CLI backend

The CLI backend runs `claude -p` with `cwd = <config dir>/workdir/`. Those calls create
transcripts too; the reader skips any line whose `cwd` equals that directory, so the coach
never analyzes its own analysis prompts.

## Commands

- **`english-coach init`** — interactive wizard (below). Idempotent.
- **`english-coach run`** — the daily job: today's `coach.py` behavior. Flags kept:
  `--backfill-days N`, `--from/--to`, `--include-today`, `--backend`, `--vault`.
- **`english-coach enrich [--phrases] [--patterns] [--force]`** — replaces `--enrich-*` flags.
- **`english-coach doctor`** — checks: `claude` on PATH and authenticated; transcripts dir
  exists and has recent files; config valid; vault exists; schedule installed and next/last run;
  last run result and skip counters from the log.
- **`english-coach schedule [--time HH:MM]` / `english-coach unschedule`** — (re)register or
  remove the OS job.

## `init` flow

1. **Prereqs** — verify `claude` on PATH and logged in (tiny `claude -p` ping, run from
   `workdir/`), and that `~/.claude/projects` has transcripts. On failure: explain the fix, stop.
2. **Vault path** — default `~/english-coach-vault`. Existing folder is reused, never
   overwritten.
3. **Learner profile** — native language, one-line context (default "software developer").
4. **Timezone** — auto-detect, confirm.
5. **Backend** — `cli` default. If `api`: prompt for key → `secrets.toml`, or note the env var.
6. **Vault skeleton** — `Daily/`, `Phrases/`, `Patterns/`, dashboard note, `.obsidian/` with
   community plugins enabled and Dataview (pinned version) under `.obsidian/plugins/dataview/`.
   Existing files are left alone.
7. **First backfill** — offer last N days (default 7). Show prompt count found before calling
   Claude. Runs the normal `run` path.
8. **Schedule** — ask time (default 07:00), register the OS job.
9. **Summary** — print config/vault/log locations and "Open this folder in Obsidian → trust
   plugins when asked".

Non-interactive: `--yes`, `--vault`, `--native-language`, `--context`, `--timezone`,
`--backend`, `--backfill-days`, `--no-schedule`, `--time`.

## Scheduling

The scheduled command is the absolute path of the installed `english-coach` executable with
`run` (resolved at `init`, because schedulers run with a minimal PATH).

| OS | Mechanism | Daily trigger | Catch-up |
|---|---|---|---|
| Windows | Task Scheduler, task "English Coach", current user, interactive token | Daily at `schedule_time` | Logon trigger with 5-min delay + `StartWhenAvailable` (ports current `Register-Task.ps1` logic) |
| macOS | `~/Library/LaunchAgents/io.github.english-coach.plist` | `StartCalendarInterval` | `RunAtLoad` (login); launchd runs a missed interval after wake |
| Linux | `~/.config/systemd/user/english-coach.{service,timer}` | `OnCalendar=*-*-* HH:MM` | `Persistent=true` |

Linux without systemd user sessions: `init` prints a crontab line (`@reboot` + daily) instead
of editing crontab.

Running twice in a day is harmless: the watermark makes the second run a no-op.

## Learner profile in the analyzer

The analyzer system prompt currently hardcodes a specific native language and tech stack.
It becomes a template:

> You are an encouraging English teacher for a {native_language}-native {context} who wants
> to …

When `native_language` is empty the clause is omitted. When set, the prompt additionally asks
the model to watch for calques and interference typical for that language. The rest of the
prompt, the JSON schema, and the curator are unchanged.

## Run data flow

1. Acquire `run.lock` (another live holder → log and exit 0; stale = PID gone or older than
   30 min → take over).
2. Compute window from watermark to end of yesterday (existing logic).
3. Empty window → exit 0.
4. Read prompts. None → write quiet note (existing behavior).
5. Analyze (CLI or API backend).
6. Render daily note, phrase/pattern notes, curator, enrichment, recompute reuse, dashboard
   (existing behavior).
7. Advance watermark only after all steps succeed (unless `--include-today`).
8. Release lock.

## Error handling

- `claude` missing, not logged in, timeout, or API error → log, exit non-zero, watermark
  unchanged; next scheduled run retries.
- Transcripts dir missing → clear error pointing at `doctor`.
- Unparseable config → error naming the file and line.
- All scheduled-run output goes to `logs/coach.log` (rotating); `doctor` shows the last result.

## Testing

- **transcripts**: `.jsonl` fixtures with one line per entry kind (typed prompt, tool_result,
  sidechain, meta, compact summary, command, system-reminder, self-cwd, duplicate uuid,
  malformed JSON, cross-midnight timestamps).
- **config**: load/save round-trip, overrides, secrets precedence.
- **lock**: held / stale-PID / stale-age.
- **scheduler**: snapshot tests of `render()` output per OS; `install/remove` tested only on
  the matching CI OS, behind a marker, against a throwaway task name.
- **init**: scripted answers, temp home/config dirs; asserts files created and idempotency.
- **analyzer prompt**: profile substitution incl. empty native language.
- Existing analyzer/curator/vault tests carry over.
- **CI**: GitHub Actions matrix — windows-latest, macos-latest, ubuntu-latest; `uv sync` +
  `uv run pytest`.

## Repository and release hygiene

- Fresh repo at `C:\Tools\english-coach-public`, clean initial history; no copy of the private
  repo's git history, `.superpowers/sdd/`, or internal plans/specs.
- MIT license (plus Dataview's MIT license notice in the bundled plugin folder).
- README: what it does, screenshot of the dashboard, 2-command quickstart, **privacy note**
  (reads local Claude Code transcripts; sends that day's prompts to Claude for analysis),
  **cost note** (uses the user's Claude subscription via CLI, or API credits), retention note,
  `doctor` troubleshooting, uninstall (`unschedule`, `uv tool uninstall english-coach`, delete
  config dir).
- Pre-publish check: grep for personal names, absolute user paths, company names, keys.
- `pyproject.toml`: `[project.scripts] english-coach = "english_coach.cli:main"`, package data
  includes `assets/`.

## Open questions

None blocking. GitHub owner/repo name to be filled in at publish time.
