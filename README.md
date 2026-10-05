# English Coach

English Coach turns the prompts you type into Claude Code into a daily English-coaching
journal, right inside an Obsidian vault. Once a day it looks at what you wrote, and builds
out notes for the wins, one focus pattern to work on, before → after fixes for the rough
edges, phrases worth practicing, and a dashboard that ties it all together — so improving
your English is a side effect of the work you were already doing.

## Requirements

- [Claude Code](https://docs.claude.com/claude-code), logged in.
- [`uv`](https://docs.astral.sh/uv/) — Python itself is installed automatically by `uv`.
- [Obsidian](https://obsidian.md/), to view the vault.

## Quick start

```
uv tool install git+https://github.com/martagit/english-coach
english-coach init
```

Then open the vault folder in Obsidian (see below).

### First time in Obsidian

The dashboard's tables are built by the [Dataview](https://github.com/blacksmithgu/obsidian-dataview)
community plugin. You don't need to install it: `init` puts a copy into the vault
(`.obsidian/plugins/dataview/`) and enables it.

1. In Obsidian, choose **Open folder as vault** and pick the vault folder
   (default `~/english-coach-vault`).
2. Obsidian asks whether you trust the author of this vault, because it contains a community
   plugin. Choose **Trust author and enable plugins**.
3. Open **English Coaching.md**: the tables fill in after the first analyzed day.

If you chose restricted mode instead, the dashboard shows raw `dataview` code blocks. Fix it
under **Settings → Community plugins**: turn off *Restricted mode*, then switch **Dataview** on.

## How it works

English Coach reads your local Claude Code transcripts (`~/.claude/projects/**/*.jsonl`) —
only the prompts you typed yourself; tool output, subagent traffic, and the coach's own
analysis calls are all skipped. Once a day it analyzes every completed day since the last
run, so if your machine was off it simply catches up next time it runs. Each run is a single
Claude call for the day's analysis, plus a few small calls to enrich phrase/pattern notes and
curate the vault.

Besides phrases (vocabulary) and patterns (recurring mistakes), the coach tracks **grammar
constructions** — everyday native structures you rarely use, such as "be supposed to",
"What if we…?" or "end up + -ing". A starter list is seeded into `Constructions/`; the coach
keeps three active at a time, notes when you use one correctly, and shows a few of your own
sentences rewritten with it under **Try this construction** in the daily note. A construction
counts as adopted after you've used it on five different days.

Each pattern note covers one rule ("Verb + preposition", "Articles"), and every correction
shows as one sentence with the change marked: paste ~~to~~ **into the** team channel.

## Privacy

Transcripts are read and parsed entirely on your machine. The text of that day's prompts is
sent to Claude for analysis — either through your Claude Code login (CLI backend) or your own
API key (API backend). Enrichment, curation and `enrich --resplit` also send excerpts already
in your vault (your example sentences and the notes' Rules). Nothing else leaves your machine.

## Cost

With the default `cli` backend, analysis runs through `claude -p` and counts against your
existing Claude subscription usage. With the `api` backend the main daily analysis uses API
credits billed to your `ANTHROPIC_API_KEY`. Either way, set `model` in `config.toml` to a
cheaper model if you want to reduce cost.

Phrase/pattern enrichment and curation always use the Claude Code CLI (`claude -p`), even with
`backend = "api"` — only the main daily analysis uses the API. So even on the API backend you
need Claude Code installed and logged in, and those small calls count against your Claude
subscription usage.

## Commands

| Command | What it does |
|---|---|
| `english-coach init` | Interactive setup: prerequisites, vault, learner profile, backend, first backfill, schedule. |
| `english-coach run` | The daily job: analyzes completed days since the last run. Flags: `--backfill-days`, `--from`/`--to`, `--include-today`, `--config-dir`, `--claude-config-dir`. |
| `english-coach enrich` | Adds definitions/examples/rules to bare phrase, pattern and construction notes (`--phrases`, `--patterns`, `--constructions` to pick; `--force` regenerates all of them, not just bare ones). |
| `english-coach enrich --resplit` | Audits pattern notes and previews splitting broad ones (e.g. "Missing words") into one-rule notes; add `--apply` to confirm and move the examples, re-link old daily notes and move the broad note to the vault's `.trash/`. Safe to re-run any time. |
| `english-coach doctor [--ping]` | Checks that everything is set up; `--ping` also makes a tiny test call to Claude (the only way it checks your login). |
| `english-coach schedule [--time HH:MM]` | Registers (or updates) the daily OS job. |
| `english-coach unschedule` | Removes the daily OS job. |

Run any command with `--help` for the full flag list (e.g. `english-coach init --help`).

## Configuration

Config lives in an OS-standard per-user directory (override with `ENGLISH_COACH_CONFIG_DIR`):

| OS | Location |
|---|---|
| Windows | `%APPDATA%\english-coach\` |
| macOS | `~/Library/Application Support/english-coach/` |
| Linux | `~/.config/english-coach/` |

`config.toml`:

```toml
vault_path = "~/english-coach-vault"
timezone = "Europe/London"          # detected at init, user-confirmable
backend = "cli"                     # "cli" | "api"
model = "claude-opus-5-5"           # used by api backend; passed to cli via --model
schedule_time = "07:00"

[profile]
native_language = "Spanish"         # empty = not specified
context = "software developer"     # one line; shapes examples and idiom choice

[limits]
adopted_threshold = 3
max_active = 12
max_new_phrases = 2
max_active_constructions = 3
max_new_constructions = 1
construction_adopted_threshold = 5
```

The watermark that tracks how far analysis has progressed is not in `config.toml` — it lives
in `<vault>/.coach-state.json`, next to the vault itself.

Secrets: set `ANTHROPIC_API_KEY` as an environment variable, or let `init` write it to
`secrets.toml` next to `config.toml` (only needed for `backend = "api"`).

Other environment variables:
- `ENGLISH_COACH_CONFIG_DIR` — override the config directory above.
- `ENGLISH_COACH_CLAUDE` — override the path to the `claude` executable.

## Scheduling details

| OS | Mechanism | Daily trigger | Catch-up |
|---|---|---|---|
| Windows | Task Scheduler task "English Coach" | Daily at `schedule_time` | Also fires at logon (5-minute delay); running twice a day is harmless. |
| macOS | `~/Library/LaunchAgents/io.github.english-coach.plist` (launchd) | `StartCalendarInterval` at `schedule_time` | `RunAtLoad`: also runs at login — and once immediately whenever you register the job with `schedule` or `init`. That first run is harmless; it's driven by the same watermark as every other run. |
| Linux | `~/.config/systemd/user/english-coach.{service,timer}` (systemd user timer) | `OnCalendar` at `schedule_time` | `Persistent=true`: a missed day runs the next time you log in. For a machine that should catch up even before anyone logs in (e.g. a headless box), run `loginctl enable-linger $USER` once so your user session starts at boot. |

If Linux has no systemd user session available, `schedule`/`init` print a crontab line to add
yourself instead of registering anything.

Scheduled jobs capture your current `PATH` (so they can find `claude`) at the moment you run
`schedule`. If you later move, reinstall, or upgrade `claude` to a new location, re-run
`english-coach schedule` to refresh it. If `ENGLISH_COACH_CONFIG_DIR` or `CLAUDE_CONFIG_DIR` is
set when you run `schedule`, the job gets them as `run --config-dir` / `--claude-config-dir`
flags, since scheduled jobs don't see your shell environment. For the same reason, with
`backend = "api"`, `init` offers to save an `ANTHROPIC_API_KEY` from your shell to
`secrets.toml` so scheduled runs can use it (the key is never written into scheduler files).

## Limits

Claude Code deletes transcripts older than `cleanupPeriodDays` (default 30) on startup, so
backfill can never reach further back than that. The transcript format is not a public API —
if Claude Code changes it, `doctor` is designed to notice and warn rather than silently
producing empty days.

## Troubleshooting

Run `english-coach doctor`. It checks that `claude` is on PATH, that transcripts exist, that
the config and vault are valid, that the schedule is registered, and reports the last run's
result. Whether `claude` is actually logged in is checked only with `--ping`, which makes a
tiny real Claude call. Logs live at
`logs/coach.log` inside the config directory above.

## Upgrade

```
uv tool upgrade english-coach
```

If the version number hasn't changed (e.g. you installed from a branch or a local folder),
force a fresh build instead:

```
uv tool install --reinstall git+https://github.com/martagit/english-coach
```

Your config, vault and schedule are kept — the scheduled job keeps pointing at the same
`english-coach` executable. New vault folders and notes (such as `Constructions/`) are created
on the next run; run `english-coach doctor` to confirm everything is in place.

After upgrading, the next run reformats older notes to the inline format. If an older pattern
note collects unrelated mistakes (e.g. "Missing words"), run `english-coach enrich --resplit`
to preview splitting it, and `english-coach enrich --patterns --force` to rewrite all pattern
Rules.

## Uninstall

```
english-coach unschedule
uv tool uninstall english-coach
```

Then delete the config directory (see **Configuration**) if you want to remove secrets and
logs too. The vault itself is a normal folder of Markdown files — it's yours to keep, move, or
delete as you like.

## License

MIT — see [LICENSE](LICENSE). This project bundles the
[Obsidian Dataview](https://github.com/blacksmithgu/obsidian-dataview) plugin (MIT, ©
Michael Brenan) under `english_coach/assets/obsidian/plugins/dataview/`; its bundled LICENSE
notice was written from this project's own MIT license text, since no upstream LICENSE file
was retrievable at the time.
