# English Coach Public Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the private, Langfuse-based English Coach into a public, cross-platform tool that installs with `uv tool install …` + `english-coach init`, reads local Claude Code transcripts, and runs daily via the OS scheduler.

**Architecture:** Copy the existing `english_coach` package into the fresh repo, then replace the Langfuse source with a local transcript reader, replace hardcoded paths with a TOML config in the OS config dir, template all LLM prompts from a learner profile, and add an `english-coach` CLI with `init / run / enrich / doctor / schedule / unschedule`. Coaching logic (analyzer schema, curator, vault rendering) is preserved.

**Tech Stack:** Python ≥3.11, uv, hatchling, pytest, `platformdirs`, `tomli-w`, `tzlocal`, `anthropic`, `pyyaml`; Windows Task Scheduler (`schtasks /XML`), macOS launchd, Linux systemd user timers; GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-23-public-release-design.md`

## Global Constraints

- Repo: `C:\Tools\english-coach-public`. Source of the code to port: `C:\Tools\english-coach` (read-only — never modify it).
- `requires-python = ">=3.11"`; TOML read with stdlib `tomllib`, written with `tomli-w`.
- Config dir: `platformdirs.user_config_dir("english-coach", appauthor=False, roaming=True)`, overridable with env `ENGLISH_COACH_CONFIG_DIR`.
- Transcripts dir: `$CLAUDE_CONFIG_DIR/projects` if set, else `~/.claude/projects`.
- Watermark stays where it is today: `<vault>/.coach-state.json` (existing `state.py`, unchanged). *(Clarifies the spec, which listed `state.json` in the config dir — keeping it in the vault means moving the vault keeps its history.)*
- Default model `claude-opus-5-5`; default backend `cli`; default schedule `07:00`; default vault `~/english-coach-vault`; default context `software developer`; default native language empty.
- CLI backend always runs `claude -p` with `cwd = <config dir>/workdir`; the transcript reader excludes that cwd.
- No user-specific strings anywhere in `english_coach/`, `README.md`, `pyproject.toml` (no personal names, company names, `C:\Users\…` paths, "Polish-native", ".NET").
- Console output must be ASCII-safe for status markers (`[OK]` / `[FAIL]`), because Windows consoles may be cp1252.
- Every task ends with `uv run pytest` fully green.
- Commit messages end with: `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`

## Review Focus

1. **Transcript being written right now** — the last line of an active session file can be a half-written JSON line; it must be skipped and counted, never crash the run. → Task 2 test `test_partial_last_line_is_skipped_and_counted`.
2. **Prompts near local midnight** — a prompt at 23:30 Warsaw time is "yesterday" even though it is 21:30 UTC; the window must bucket by the configured timezone. → Task 2 test `test_local_midnight_boundary_uses_window`.
3. **Paths with spaces** (e.g. `C:\Users\Jane Doe\…\python.exe`) in the scheduled command must survive quoting in Task XML, plist, and systemd `ExecStart`. → Task 7 tests `test_*_quotes_paths_with_spaces`.
4. **Re-running `init`** on an existing config/vault must not overwrite notes or config, and previous answers become the defaults. → Task 9 test `test_init_rerun_keeps_existing_and_uses_previous_answers`.
5. **Installed wheel missing bundled assets** (Dataview plugin, dashboard) — works from source but breaks after `uv tool install`. → Task 6 test `test_wheel_contains_obsidian_assets`.

---

### Task 1: Bootstrap the public repo with the existing code

**Files:**
- Create: `english_coach/` (copied), `tests/` (copied), `pyproject.toml`, `.gitignore`, `LICENSE`
- Do NOT copy: `.venv`, `.git`, `.superpowers`, `.claude`, `.pytest_cache`, `docs/`, `Register-Task.ps1`, `README.md`, `uv.lock`

**Interfaces:**
- Consumes: nothing.
- Produces: an installable package `english_coach` with the unchanged private code; green test suite as a baseline.

- [ ] **Step 1: Copy the package and tests**

```bash
cd /c/Tools/english-coach-public
cp -r ../english-coach/english_coach ../english-coach/tests .
find english_coach tests -name __pycache__ -type d -prune -exec rm -rf {} +
ls english_coach tests
```
Expected: the 13 modules (`analyzer.py … window.py`) and 15 test files listed.

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "english-coach"
version = "0.1.0"
description = "Turns your Claude Code prompts into a daily English-coaching Obsidian vault."
license = "MIT"
requires-python = ">=3.11"
dependencies = [
    "anthropic>=0.40",
    "pyyaml>=6.0",
    "tzdata>=2024.1",
    "httpx>=0.27",
    "platformdirs>=4.0",
    "tomli-w>=1.0",
    "tzlocal>=5.0",
]

[dependency-groups]
dev = ["pytest>=8.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["english_coach"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["integration: touches the real OS scheduler (opt-in via EC_SCHEDULER_IT=1)"]
```
(`httpx` stays until Task 5 deletes the Langfuse client.)

- [ ] **Step 3: Write `.gitignore`**

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
dist/
build/
*.egg-info/
.superpowers/
.claude/
```

- [ ] **Step 4: Write `LICENSE`** — standard MIT text, `Copyright (c) 2026 English Coach contributors`.

- [ ] **Step 5: Install and run the baseline tests**

Run: `uv sync && uv run pytest -q`
Expected: all tests PASS (same count as the private repo). If anything fails, stop and report — the baseline must be green before changes.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: import english_coach package and tests as baseline

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Transcript reader

**Files:**
- Create: `english_coach/transcripts.py`
- Test: `tests/test_transcripts.py`

**Interfaces:**
- Consumes: `english_coach.models.UserPrompt(text: str, timestamp_utc: datetime)`.
- Produces:
  - `default_projects_dir(env: dict | None = None) -> Path`
  - `@dataclass ReadStats(files_scanned: int = 0, lines_read: int = 0, malformed: int = 0, prompts: int = 0)`
  - `prompt_from_entry(entry: dict, exclude_cwd: Path | None = None) -> UserPrompt | None`
  - `read_prompts(projects_dir: Path, start_utc: datetime, end_utc: datetime, exclude_cwd: Path | None = None, stats: ReadStats | None = None) -> list[UserPrompt]` — sorted by timestamp; raises `FileNotFoundError` if `projects_dir` is missing.
  - `class TranscriptSource(projects_dir: Path, exclude_cwd: Path | None = None)` with `fetch_prompts(start_utc, end_utc) -> list[UserPrompt]` and attribute `last_stats: ReadStats`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_transcripts.py
import json
import os
import time
from datetime import datetime, timezone, date
from pathlib import Path

import pytest

from english_coach.transcripts import (
    ReadStats, TranscriptSource, default_projects_dir, prompt_from_entry, read_prompts,
)
from english_coach.window import compute_window

T0 = datetime(2026, 7, 5, 0, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 7, 6, 0, 0, tzinfo=timezone.utc)


def _entry(text="How should we name this?", ts="2026-07-05T09:00:00Z", **extra):
    e = {"type": "user", "uuid": extra.pop("uuid", f"u-{text}-{ts}"), "timestamp": ts,
         "cwd": "/home/me/proj", "sessionId": "s1", "isSidechain": False,
         "message": {"role": "user", "content": text}}
    e.update(extra)
    return e


def _write(dir_: Path, name: str, lines: list) -> Path:
    dir_.mkdir(parents=True, exist_ok=True)
    p = dir_ / name
    p.write_text("\n".join(l if isinstance(l, str) else json.dumps(l) for l in lines) + "\n",
                 encoding="utf-8")
    return p


def test_typed_string_prompt_is_kept():
    p = prompt_from_entry(_entry())
    assert p.text == "How should we name this?"
    assert p.timestamp_utc == datetime(2026, 7, 5, 9, tzinfo=timezone.utc)


def test_text_block_list_is_joined():
    e = _entry(message={"role": "user", "content": [
        {"type": "text", "text": "first"}, {"type": "image", "source": {}},
        {"type": "text", "text": "second"}]})
    assert prompt_from_entry(e).text == "first\nsecond"


@pytest.mark.parametrize("entry", [
    _entry(type="assistant"),
    _entry(isSidechain=True),
    _entry(isMeta=True),
    _entry(isCompactSummary=True),
    _entry(message={"role": "user", "content": [{"type": "tool_result", "content": "x"}]}),
    _entry(text="<command-name>/clear</command-name>"),
    _entry(text="<local-command-stdout>ok</local-command-stdout>"),
    _entry(text="<system-reminder>injected</system-reminder>"),
    _entry(text="   "),
    _entry(ts="not-a-date"),
    _entry(message="not a dict"),
])
def test_non_prompt_entries_are_rejected(entry):
    assert prompt_from_entry(entry) is None


def test_exclude_cwd_rejects_coach_own_calls(tmp_path):
    work = tmp_path / "workdir"
    e = _entry(cwd=str(work))
    assert prompt_from_entry(e, exclude_cwd=work) is None
    assert prompt_from_entry(e, exclude_cwd=tmp_path / "other") is not None


def test_read_prompts_filters_window_dedupes_and_sorts(tmp_path):
    proj = tmp_path / "projects"
    _write(proj / "C--a", "s1.jsonl", [
        _entry("later", "2026-07-05T15:00:00Z", uuid="a"),
        _entry("earlier", "2026-07-05T08:00:00Z", uuid="b"),
        _entry("out of window", "2026-07-04T08:00:00Z", uuid="c"),
    ])
    _write(proj / "C--b", "s2.jsonl", [_entry("later", "2026-07-05T15:00:00Z", uuid="a")])  # replayed
    out = read_prompts(proj, T0, T1)
    assert [p.text for p in out] == ["earlier", "later"]


def test_partial_last_line_is_skipped_and_counted(tmp_path):
    proj = tmp_path / "projects"
    _write(proj / "C--a", "s1.jsonl", [_entry("complete"), '{"type": "user", "mess'])
    stats = ReadStats()
    out = read_prompts(proj, T0, T1, stats=stats)
    assert [p.text for p in out] == ["complete"]
    assert stats.malformed == 1
    assert stats.files_scanned == 1
    assert stats.prompts == 1


def test_files_untouched_since_window_start_are_skipped(tmp_path):
    proj = tmp_path / "projects"
    old = _write(proj / "C--a", "old.jsonl", [_entry("in window but file is old")])
    past = T0.timestamp() - 3600
    os.utime(old, (past, past))
    stats = ReadStats()
    assert read_prompts(proj, T0, T1, stats=stats) == []
    assert stats.files_scanned == 0


def test_local_midnight_boundary_uses_window(tmp_path):
    # 2026-07-05 23:30 Warsaw == 21:30 UTC -> belongs to Sunday 07-05.
    # 2026-07-06 00:30 Warsaw == 22:30 UTC on 07-05 -> belongs to Monday (today), excluded.
    proj = tmp_path / "projects"
    _write(proj / "C--a", "s.jsonl", [
        _entry("sunday late", "2026-07-05T21:30:00Z", uuid="1"),
        _entry("monday early", "2026-07-05T22:30:00Z", uuid="2"),
    ])
    now = datetime(2026, 7, 6, 5, tzinfo=timezone.utc)
    w = compute_window(now, None, "Europe/Warsaw", backfill_days=1)
    assert w.days == [date(2026, 7, 5)]
    out = read_prompts(proj, w.start_utc, w.end_utc)
    assert [p.text for p in out] == ["sunday late"]


def test_missing_projects_dir_raises_with_hint(tmp_path):
    with pytest.raises(FileNotFoundError, match="doctor"):
        read_prompts(tmp_path / "nope", T0, T1)


def test_default_projects_dir_honors_claude_config_dir(tmp_path):
    assert default_projects_dir({"CLAUDE_CONFIG_DIR": str(tmp_path)}) == tmp_path / "projects"
    assert default_projects_dir({}) == Path.home() / ".claude" / "projects"


def test_transcript_source_records_stats(tmp_path):
    proj = tmp_path / "projects"
    _write(proj / "C--a", "s.jsonl", [_entry("hello there")])
    src = TranscriptSource(proj)
    assert [p.text for p in src.fetch_prompts(T0, T1)] == ["hello there"]
    assert src.last_stats.prompts == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_transcripts.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'english_coach.transcripts'`.

- [ ] **Step 3: Implement `english_coach/transcripts.py`**

```python
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from english_coach.models import UserPrompt

# Lines Claude Code writes as "user" but that the human did not type.
_SKIP_PREFIXES = ("<command-", "<local-command-", "<system-reminder>")


@dataclass
class ReadStats:
    files_scanned: int = 0
    lines_read: int = 0
    malformed: int = 0
    prompts: int = 0


def default_projects_dir(env: dict | None = None) -> Path:
    env = os.environ if env is None else env
    base = env.get("CLAUDE_CONFIG_DIR")
    return (Path(base) if base else Path.home() / ".claude") / "projects"


def _text_of(content) -> str | None:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        parts = [b.get("text", "") for b in content
                 if isinstance(b, dict) and b.get("type") == "text"]
        return "\n".join(p for p in parts if p) or None
    return None


def _parse_ts(raw) -> datetime | None:
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (AttributeError, ValueError):
        return None


def _same_dir(a, b) -> bool:
    return os.path.normcase(os.path.normpath(str(a))) == os.path.normcase(os.path.normpath(str(b)))


def prompt_from_entry(entry: dict, exclude_cwd: Path | None = None) -> UserPrompt | None:
    if entry.get("type") != "user":
        return None
    if entry.get("isSidechain") or entry.get("isMeta") or entry.get("isCompactSummary"):
        return None
    cwd = entry.get("cwd")
    if exclude_cwd is not None and cwd and _same_dir(cwd, exclude_cwd):
        return None
    msg = entry.get("message")
    if not isinstance(msg, dict):
        return None
    text = _text_of(msg.get("content"))
    if not text or not text.strip() or text.lstrip().startswith(_SKIP_PREFIXES):
        return None
    ts = _parse_ts(entry.get("timestamp"))
    if ts is None:
        return None
    return UserPrompt(text=text, timestamp_utc=ts)


def read_prompts(projects_dir: Path, start_utc: datetime, end_utc: datetime,
                 exclude_cwd: Path | None = None, stats: ReadStats | None = None) -> list[UserPrompt]:
    projects_dir = Path(projects_dir)
    if not projects_dir.is_dir():
        raise FileNotFoundError(
            f"Claude Code transcripts folder not found: {projects_dir}. "
            "Run `english-coach doctor` for help.")
    stats = stats if stats is not None else ReadStats()
    start_ts = start_utc.timestamp()
    seen: set = set()
    out: list[UserPrompt] = []
    for path in sorted(projects_dir.rglob("*.jsonl")):
        try:
            if path.stat().st_mtime < start_ts:
                continue  # nothing appended since the window began
        except OSError:
            continue
        stats.files_scanned += 1
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                stats.lines_read += 1
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    stats.malformed += 1  # e.g. a line Claude Code is still writing
                    continue
                if not isinstance(entry, dict):
                    stats.malformed += 1
                    continue
                prompt = prompt_from_entry(entry, exclude_cwd)
                if prompt is None or not (start_utc <= prompt.timestamp_utc <= end_utc):
                    continue
                key = entry.get("uuid") or (entry.get("sessionId"), entry.get("timestamp"), prompt.text)
                if key in seen:
                    continue  # resumed/forked sessions replay history
                seen.add(key)
                out.append(prompt)
    out.sort(key=lambda p: p.timestamp_utc)
    stats.prompts = len(out)
    return out


class TranscriptSource:
    def __init__(self, projects_dir: Path, exclude_cwd: Path | None = None):
        self._projects_dir = Path(projects_dir)
        self._exclude_cwd = exclude_cwd
        self.last_stats = ReadStats()

    def fetch_prompts(self, start_utc: datetime, end_utc: datetime) -> list[UserPrompt]:
        self.last_stats = ReadStats()
        return read_prompts(self._projects_dir, start_utc, end_utc,
                            self._exclude_cwd, self.last_stats)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_transcripts.py -q` → PASS. Then `uv run pytest -q` → all PASS.

- [ ] **Step 5: Commit**

```bash
git add english_coach/transcripts.py tests/test_transcripts.py
git commit -m "feat: read user prompts from local Claude Code transcripts

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Single-instance run lock

**Files:**
- Create: `english_coach/lock.py`
- Test: `tests/test_lock.py`

**Interfaces:**
- Produces: `class AlreadyRunning(RuntimeError)`; `run_lock(path: Path, stale_after_s: int = 1800, now=time.time)` context manager; `pid_alive(pid: int) -> bool`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_lock.py
import json
import os

import pytest

from english_coach import lock as lk


def test_lock_is_exclusive_and_released(tmp_path):
    p = tmp_path / "run.lock"
    with lk.run_lock(p):
        assert p.exists()
        with pytest.raises(lk.AlreadyRunning):
            with lk.run_lock(p):
                pass
    assert not p.exists()


def test_lock_released_on_exception(tmp_path):
    p = tmp_path / "run.lock"
    with pytest.raises(ValueError):
        with lk.run_lock(p):
            raise ValueError("boom")
    assert not p.exists()


def test_stale_by_age_is_taken_over(tmp_path):
    p = tmp_path / "run.lock"
    p.write_text(json.dumps({"pid": os.getpid(), "started": 1000.0}))
    with lk.run_lock(p, stale_after_s=60, now=lambda: 5000.0):
        assert json.loads(p.read_text())["started"] == 5000.0


def test_stale_by_dead_pid_is_taken_over(tmp_path, monkeypatch):
    p = tmp_path / "run.lock"
    p.write_text(json.dumps({"pid": 999999, "started": 5000.0}))
    monkeypatch.setattr(lk, "pid_alive", lambda pid: False)
    with lk.run_lock(p, now=lambda: 5001.0):
        pass


def test_corrupt_lock_is_stale(tmp_path):
    p = tmp_path / "run.lock"
    p.write_text("garbage")
    with lk.run_lock(p):
        pass


def test_pid_alive_for_self():
    assert lk.pid_alive(os.getpid()) is True
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_lock.py -q` → FAIL (module missing).

- [ ] **Step 3: Implement `english_coach/lock.py`**

```python
from __future__ import annotations

import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path


class AlreadyRunning(RuntimeError):
    pass


def pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _is_stale(path: Path, stale_after_s: int, now) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        pid, started = int(data["pid"]), float(data["started"])
    except (OSError, ValueError, KeyError, TypeError):
        return True
    return (now() - started) > stale_after_s or not pid_alive(pid)


def _create(path: Path, now) -> None:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"pid": os.getpid(), "started": now()}, fh)


@contextmanager
def run_lock(path: Path, stale_after_s: int = 1800, now=time.time):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _create(path, now)
    except FileExistsError:
        if not _is_stale(path, stale_after_s, now):
            raise AlreadyRunning(f"Another english-coach run holds {path}")
        path.unlink(missing_ok=True)
        try:
            _create(path, now)
        except FileExistsError:
            raise AlreadyRunning(f"Another english-coach run holds {path}")
    try:
        yield
    finally:
        path.unlink(missing_ok=True)
```

- [ ] **Step 4: Run tests** — `uv run pytest -q` → all PASS.

- [ ] **Step 5: Commit** — `git add english_coach/lock.py tests/test_lock.py && git commit -m "feat: single-instance run lock with stale detection" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"`

---

### Task 4: Learner profile, prompt templating, patterns from the vault

Removes every hardcoded learner description and the personal seed content.

**Files:**
- Create: `english_coach/profile.py`, `tests/test_profile.py`
- Modify: `english_coach/config.py` (add `profile` field only), `english_coach/analyzer.py`, `english_coach/curator.py`, `english_coach/vault.py`, `english_coach/coach.py`
- Delete: `english_coach/seed.py`, `tests/test_seed.py`
- Modify tests: `tests/test_analyzer.py`, `tests/test_vault_notes.py`, `tests/test_coach.py`, `tests/test_curator.py` (only where noted)

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) Profile(native_language: str = "", context: str = "software developer")` with `learner() -> str` and `interference_hint() -> str`.
  - `Config.profile: Profile` (last field, default `Profile()`).
  - `analyzer.system_prompt(profile: Profile) -> str`
  - `build_analysis_prompt(prompts, phrasebook, max_new_phrases=2, known_patterns=(), profile=Profile())`
  - `ClaudeAnalyzer.analyze(prompts, phrasebook, known_patterns=())`, `ClaudeCliAnalyzer.analyze(prompts, phrasebook, known_patterns=())` — both use `config.profile`.
  - `build_enrichment_prompt(items, examples_per_phrase=3, profile=Profile())`, `enrich_phrases(items, runner=None, examples_per_phrase=3, profile=Profile())`
  - `build_pattern_enrichment_prompt(items, profile=Profile())`, `enrich_patterns(items, runner=None, profile=Profile())`
  - `curator.build_curation_prompt(inventory, max_active, profile=Profile())`, `curate(vault, runner=None, max_active=12, profile=Profile())`
  - `run_claude_cli(prompt, model=None, timeout=300, cwd=None) -> str`
  - `vault.read_known_patterns(vault: Path) -> list[tuple[str, str]]` — `(pattern name, rule or "")` from `Patterns/*.md`.
  - `vault.seed_vault` is **removed**.

- [ ] **Step 1: Write failing tests for the profile**

```python
# tests/test_profile.py
from english_coach.profile import Profile


def test_learner_with_language():
    assert Profile("Polish", "software developer").learner() == "a Polish-native software developer"


def test_learner_uses_an_before_vowel():
    assert Profile("Italian", "data engineer").learner() == "an Italian-native data engineer"


def test_learner_without_language_and_blank_context():
    assert Profile("", "  ").learner() == "a software developer"
    assert Profile("", "architect").learner() == "an architect"


def test_interference_hint_only_with_language():
    assert "Spanish" in Profile("Spanish").interference_hint()
    assert Profile().interference_hint() == ""
```

- [ ] **Step 2: Run** — `uv run pytest tests/test_profile.py -q` → FAIL (module missing).

- [ ] **Step 3: Implement `english_coach/profile.py`**

```python
from __future__ import annotations

from dataclasses import dataclass

_DEFAULT_CONTEXT = "software developer"


def _article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


@dataclass(frozen=True)
class Profile:
    native_language: str = ""
    context: str = _DEFAULT_CONTEXT

    def _ctx(self) -> str:
        return self.context.strip() or _DEFAULT_CONTEXT

    def learner(self) -> str:
        lang = self.native_language.strip()
        phrase = f"{lang}-native {self._ctx()}" if lang else self._ctx()
        return f"{_article(phrase)} {phrase}"

    def interference_hint(self) -> str:
        lang = self.native_language.strip()
        if not lang:
            return ""
        return (f"Watch especially for calques and interference typical of {lang} speakers "
                "(word order, articles, prepositions, literal translations).")
```

- [ ] **Step 4: Add `profile` to the current `Config`** — in `english_coach/config.py` add `from english_coach.profile import Profile` and append as the **last** dataclass field:

```python
    profile: Profile = field(default_factory=Profile)
```

- [ ] **Step 5: Update tests that pin old behavior (they will fail after Step 6)**

In `tests/test_analyzer.py`, replace `test_build_prompt_includes_prompts_and_phrasebook` with:

```python
def test_build_prompt_includes_prompts_phrasebook_and_known_patterns():
    text = build_analysis_prompt(
        [UserPrompt("Why we need here the reference?", None)],
        [PhraseInfo("park it", "learning", 0)],
        known_patterns=[("Articles", "a/an/the usage")],
    )
    assert "Why we need here the reference?" in text
    assert "park it" in text
    assert "- Articles: a/an/the usage" in text


def test_build_prompt_without_known_patterns_says_none_yet():
    text = build_analysis_prompt([UserPrompt("Hello team", None)], [])
    assert "(none yet)" in text


def test_prompts_use_profile_not_hardcoded_learner():
    from english_coach.profile import Profile
    from english_coach.analyzer import build_pattern_enrichment_prompt
    from english_coach.curator import build_curation_prompt
    prof = Profile("German", "QA engineer")
    texts = [
        build_analysis_prompt([UserPrompt("x y z", None)], [], profile=prof),
        build_enrichment_prompt([{"phrase": "park it", "your_quote": None}], profile=prof),
        build_pattern_enrichment_prompt([{"pattern": "Articles", "description": "", "examples": []}],
                                        profile=prof),
        build_curation_prompt([], 12, profile=prof),
    ]
    for t in texts:
        assert "a German-native QA engineer" in t
        assert "Polish" not in t and ".NET" not in t


def test_run_claude_cli_passes_cwd(monkeypatch, tmp_path):
    import english_coach.analyzer as az
    seen = {}

    class P:
        returncode = 0
        stdout = '{"result": "hi"}'
        stderr = ""

    def fake_run(cmd, **kw):
        seen.update(kw)
        return P()

    monkeypatch.setattr(az.subprocess, "run", fake_run)
    assert az.run_claude_cli("hello", cwd=tmp_path) == "hi"
    assert seen["cwd"] == tmp_path
```

Also in `tests/test_analyzer.py` change `_cfg()` to keep working (unchanged for now — positional Config still valid).

In `tests/test_vault_notes.py`: delete `test_seed_vault_creates_patterns_and_phrases`, remove `seed_vault` from the import list, and add:

```python
def test_read_known_patterns_from_vault(tmp_path):
    from english_coach.vault import read_known_patterns, ensure_pattern_note
    ensure_pattern_note(tmp_path, "Articles", "a/an/the usage")
    ensure_pattern_note(tmp_path, "Question formation")  # no rule yet
    assert read_known_patterns(tmp_path) == [("Articles", "a/an/the usage"),
                                             ("Question formation", "")]


def test_read_known_patterns_empty_vault(tmp_path):
    from english_coach.vault import read_known_patterns
    assert read_known_patterns(tmp_path) == []
```

In `tests/test_coach.py` change `FakeAnalyzer.analyze` to:

```python
    def analyze(self, prompts, phrasebook, known_patterns=()):
        self.called = True
        self.known_patterns = list(known_patterns)
        return self._analysis
```

Delete `tests/test_seed.py`.

- [ ] **Step 6: Run to verify the new tests fail** — `uv run pytest -q` → the new tests FAIL (unknown kwargs `known_patterns` / `profile` / `cwd`, missing `read_known_patterns`).

- [ ] **Step 7: Update `english_coach/analyzer.py`**

Replace the `from english_coach.seed import KNOWN_PATTERNS` import with `from english_coach.profile import Profile`. Replace `_SYSTEM` and `build_analysis_prompt` with:

```python
def system_prompt(profile: Profile) -> str:
    hint = profile.interference_hint()
    return (
        f"You are an encouraging English teacher for {profile.learner()} who wants to "
        "sound more fluent and natural in English. You analyze the learner's own Claude Code "
        "prompts. Ground EVERY point in a direct quote of their actual words. Be concise and "
        "aware of the idioms of their field. Never fabricate: if a section has nothing real, "
        "return it empty." + (f" {hint}" if hint else "")
    )


def build_analysis_prompt(prompts: list[UserPrompt], phrasebook: list[PhraseInfo],
                          max_new_phrases: int = 2, known_patterns=(),
                          profile: Profile = Profile()) -> str:
    patterns = "\n".join(f"- {name}: {desc}" if desc else f"- {name}"
                         for name, desc in known_patterns) or "- (none yet)"
    book = "\n".join(f"- {p.phrase} (status: {p.status}, reuse_count: {p.reuse_count})"
                     for p in phrasebook) or "- (empty)"
    joined = "\n\n".join(f"[{i + 1}] {p.text}" for i, p in enumerate(prompts))
    return (
        f"{system_prompt(profile)}\n\n"
        "Known recurring patterns for this user:\n"
        f"{patterns}\n\n"
        "Current phrasebook (taught phrases — detect which were reused today):\n"
        f"{book}\n\n"
        "The user's prompts for the period:\n"
        f"{joined}\n\n"
        "Analyze and call report_analysis. reused_phrases must be a subset of the phrasebook "
        "phrase names that the user actually reused correctly. Pick ONE highest-value focus_pattern.\n"
        "For every 'pattern' field (in focus_pattern and recurring), use the EXACT short name "
        "from the 'Known recurring patterns' list above when it applies — copied verbatim, NOT "
        "expanded or paraphrased into a sentence. Only coin a new short 2-4 word name (e.g. "
        "\"Articles\", \"Question formation\") if the issue is genuinely not in that list. Put "
        "the detailed guidance in 'explanation', never in the name.\n"
        f"For new_phrases: propose AT MOST {max_new_phrases}, and only if genuinely high-value "
        "for this user — an empty list is a fine answer. Never re-teach anything already in the "
        "phrasebook above, including close variants of it."
    )
```

In both `ClaudeAnalyzer.analyze` and `ClaudeCliAnalyzer.analyze`, change the signature to `analyze(self, prompts, phrasebook, known_patterns=())` and build the prompt with
`build_analysis_prompt(prompts, phrasebook, self._config.max_new_phrases, known_patterns, self._config.profile)`.

Replace `_resolve_claude` and `run_claude_cli` with:

```python
def _resolve_claude() -> str:
    """Locate the claude CLI even when PATH is stripped (e.g. under a scheduler).

    Order: ENGLISH_COACH_CLAUDE env override -> PATH -> the standard native-install
    location ~/.local/bin/claude(.exe) -> bare "claude".
    """
    override = os.environ.get("ENGLISH_COACH_CLAUDE")
    if override:
        return override
    found = shutil.which("claude")
    if found:
        return found
    for name in ("claude.exe", "claude"):
        guess = os.path.join(os.path.expanduser("~"), ".local", "bin", name)
        if os.path.exists(guess):
            return guess
    return "claude"


def run_claude_cli(prompt: str, model: str | None = None, timeout: int = 300, cwd=None) -> str:
    """Run a one-shot `claude -p` and return the model's text reply.

    Pure text-in / JSON-out with no tools (`--allowedTools ""`), so no permission
    prompts. Forces UTF-8 decoding (Windows text mode would otherwise use cp1252
    and mangle em-dashes/curly quotes). `cwd` is the coach's own work dir, so the
    transcript reader can exclude these calls from analysis.
    """
    cli = _resolve_claude()
    # Pass the prompt on STDIN, not as a CLI arg — Windows caps command lines at
    # ~32,767 chars (WinError 206), and a full day of prompts easily exceeds that.
    cmd = [cli, "-p", "--output-format", "json", "--allowedTools", ""]
    if model:
        cmd += ["--model", model]
    extra = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout, cwd=cwd, **extra)
    if proc.returncode != 0:
        raise RuntimeError(
            f"claude CLI failed (exit {proc.returncode}): {(proc.stderr or '').strip()[:500]}"
        )
    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return proc.stdout  # not the JSON envelope; treat raw stdout as the reply
    if isinstance(envelope, dict):
        if envelope.get("is_error"):
            raise RuntimeError(f"claude CLI returned an error result: {str(envelope)[:300]}")
        return envelope.get("result", "")
    return proc.stdout
```
(add `import sys` at the top.)

Replace `_ENRICH_SYSTEM` + `build_enrichment_prompt` + `enrich_phrases` signature:

```python
def enrich_system(profile: Profile) -> str:
    return (
        f"You write concise flashcard content for an English learner who is {profile.learner()}. "
        "Definitions are one plain-English sentence. Example sentences must sound natural in "
        f"the learner's working context ({profile._ctx()}) — the kind of thing they would "
        "actually say to a colleague or write in a work message."
    )


def build_enrichment_prompt(items: list[dict], examples_per_phrase: int = 3,
                            profile: Profile = Profile()) -> str:
    """items: [{"phrase": str, "your_quote": str | None}]."""
    lines = []
    for it in items:
        q = it.get("your_quote")
        suffix = f'   (the learner actually used it: "{q}")' if q else ""
        lines.append(f"- {it['phrase']}{suffix}")
    listing = "\n".join(lines)
    return (
        f"{enrich_system(profile)}\n\n"
        f"For EACH phrase below, write a one-sentence definition and {examples_per_phrase} "
        f"example sentences in the learner's working context ({profile._ctx()}). Do NOT reuse "
        "the learner's own quoted sentence as an example — write fresh ones.\n\n"
        f"Phrases:\n{listing}\n\n"
        "Output ONLY a single JSON object of exactly this shape — no prose, no markdown fences:\n"
        '{"phrases":[{"phrase":"<the phrase verbatim>","definition":"...","examples":["...","..."]}]}\n'
        "Include EVERY phrase listed, with the phrase copied verbatim so it can be matched back."
    )
```
and in `enrich_phrases` add the `profile: Profile = Profile()` parameter and call `build_enrichment_prompt(items, examples_per_phrase, profile)`.

Replace `_PATTERN_SYSTEM` with:

```python
def pattern_system(profile: Profile) -> str:
    return (
        f"You explain English grammar rules concisely for {profile.learner()}. Each 'rule' is "
        "1-2 plain-English sentences: state the rule and the specific mistake to watch for. "
        "Ground it in the learner's own before/after fixes when given."
    )
```
and change `build_pattern_enrichment_prompt(items, profile: Profile = Profile())` to start with `f"{pattern_system(profile)}\n\n"`; `enrich_patterns(items, runner=None, profile: Profile = Profile())` calls `build_pattern_enrichment_prompt(items, profile)`.

- [ ] **Step 8: Update `english_coach/curator.py`**

Replace `_CURATOR_SYSTEM` with a function and thread `profile` through:

```python
from english_coach.profile import Profile


def curator_system(profile: Profile) -> str:
    return (
        f"You curate a personal English phrasebook for {profile.learner()}. "
        "The learner can only actively practice a small set of phrases at a time. Decide which "
        "phrases are 'active' (currently practicing) vs 'backlog' (parked for later), give each "
        "a priority (1 = practice first .. 5 = someday), and a short theme label that groups "
        "related phrases (e.g. 'hedging', 'review feedback', 'asking for changes')."
    )
```
`build_curation_prompt(inventory, max_active, profile: Profile = Profile())` starts with `f"{curator_system(profile)}\n\n"`. `curate(vault, runner=None, max_active=12, profile: Profile = Profile())` calls `build_curation_prompt(inventory, max_active, profile)`.

- [ ] **Step 9: Update `english_coach/vault.py`**

Remove `from english_coach.seed import KNOWN_PATTERNS, TAUGHT_IDIOMS` and delete `seed_vault`. Add (next to `ensure_pattern_note`):

```python
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
```

- [ ] **Step 10: Update `english_coach/coach.py` `run()`**

Delete the two lines `today_local_date = …` and `vault.seed_vault(…)`. Replace `analysis = analyzer.analyze(prompts, phrasebook)` with:

```python
    known_patterns = vault.read_known_patterns(config.vault_path)
    analysis = analyzer.analyze(prompts, phrasebook, known_patterns)
```

- [ ] **Step 11: Delete seed module** — `git rm english_coach/seed.py tests/test_seed.py`

- [ ] **Step 12: Run everything** — `uv run pytest -q` → all PASS. Then `grep -rn "Polish\|\.NET\|C#" english_coach/` → no output.

- [ ] **Step 13: Commit** — `git add -A && git commit -m "feat: learner profile drives all prompts; known patterns come from the vault" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"`

---

### Task 5: TOML config, run log, and the `english-coach` CLI (`run`, `enrich`)

Replaces Langfuse + hardcoded paths. After this task the tool works end-to-end from a config file.

**Files:**
- Rewrite: `english_coach/config.py`, `tests/test_config.py`
- Create: `english_coach/runlog.py`, `english_coach/cli.py`, `english_coach/__main__.py`, `tests/test_runlog.py`, `tests/test_cli_run.py`
- Modify: `english_coach/coach.py` (source instead of Langfuse; delete `main`, `_DEFAULT_*`), `english_coach/filtering.py` (delete `extract_user_prompts`, `_parse_ts`), `tests/test_coach.py`, `tests/test_filtering.py`, `tests/test_analyzer.py` (`_cfg`), `pyproject.toml`
- Delete: `english_coach/langfuse_client.py`, `tests/test_langfuse_client.py`

**Interfaces:**
- Consumes: `TranscriptSource`, `default_projects_dir`, `ReadStats` (Task 2); `run_lock`, `AlreadyRunning` (Task 3); `Profile`, `run_claude_cli(..., cwd=)`, profile-aware `curate/enrich_*` (Task 4).
- Produces:
  - `config.APP_NAME = "english-coach"`, `config.DEFAULT_MODEL = "claude-opus-5-5"`, `config.DEFAULT_VAULT = Path.home() / "english-coach-vault"`
  - `@dataclass(frozen=True) AppPaths(config_dir: Path)` with properties `config_file, secrets_file, lock_file, log_file, last_run_file, workdir` and `AppPaths.default(env: dict | None = None) -> AppPaths`
  - `@dataclass(frozen=True) Config(vault_path: Path, timezone: str = "UTC", backend: str = "cli", model: str = DEFAULT_MODEL, schedule_time: str = "07:00", profile: Profile = Profile(), adopted_threshold: int = 3, max_active: int = 12, max_new_phrases: int = 2, anthropic_api_key: str = "")` (key has `repr=False`)
  - `class ConfigError(RuntimeError)`; `load_config(paths: AppPaths, env: dict) -> Config`; `save_config(paths: AppPaths, config: Config) -> None`; `save_api_key(paths: AppPaths, key: str) -> None`
  - `runlog.run_log(log_file: Path)` context manager (tees stdout/stderr to the log, rotates at 512 KB, keeps 3); `runlog.write_last_run(path: Path, status: str, stats: ReadStats | None, now: datetime | None = None)`; `runlog.read_last_run(path: Path) -> dict | None`
  - `coach.run(config, source, analyzer, now_utc, backfill_days=1, override_from=None, override_to=None, enricher=None, pattern_enricher=None, include_today=False, curator=None) -> str` — `source.fetch_prompts(start_utc, end_utc)`; statuses `"empty" | "quiet" | "wrote:<label>"`.
  - `cli.build_parser() -> argparse.ArgumentParser`; `cli.main(argv: list[str] | None = None, env: dict | None = None) -> int`; `cli.execute_run(config: Config, paths: AppPaths, env: dict, *, backfill_days=1, override_from=None, override_to=None, include_today=False, now_utc=None, analyzer=None, source=None, runner=None) -> tuple[int, str]` — returns `(exit_code, status)`, where status may also be `"locked"` or `"error"`.
  - Console script `english-coach = "english_coach.cli:main"`.

- [ ] **Step 1: Write the failing config tests (replace the whole file)**

```python
# tests/test_config.py
import os
import sys
from pathlib import Path

import pytest

from english_coach.config import (
    AppPaths, Config, ConfigError, DEFAULT_MODEL, load_config, save_api_key, save_config,
)
from english_coach.profile import Profile


def _paths(tmp_path) -> AppPaths:
    return AppPaths(tmp_path / "cfg")


def test_app_paths_layout(tmp_path):
    p = _paths(tmp_path)
    assert p.config_file == tmp_path / "cfg" / "config.toml"
    assert p.secrets_file == tmp_path / "cfg" / "secrets.toml"
    assert p.lock_file == tmp_path / "cfg" / "run.lock"
    assert p.log_file == tmp_path / "cfg" / "logs" / "coach.log"
    assert p.last_run_file == tmp_path / "cfg" / "last_run.json"
    assert p.workdir == tmp_path / "cfg" / "workdir"


def test_app_paths_env_override(tmp_path):
    assert AppPaths.default({"ENGLISH_COACH_CONFIG_DIR": str(tmp_path)}).config_dir == tmp_path


def test_save_then_load_round_trip(tmp_path):
    p = _paths(tmp_path)
    cfg = Config(vault_path=tmp_path / "vault", timezone="Europe/Warsaw", backend="api",
                 schedule_time="06:30", profile=Profile("Polish", "tester"), max_active=8)
    save_config(p, cfg)
    loaded = load_config(p, env={})
    assert loaded == cfg


def test_defaults(tmp_path):
    p = _paths(tmp_path)
    p.config_dir.mkdir(parents=True)
    p.config_file.write_text('vault_path = "~/v"\n', encoding="utf-8")
    cfg = load_config(p, env={})
    assert cfg.vault_path == Path.home() / "v"
    assert cfg.backend == "cli" and cfg.model == DEFAULT_MODEL
    assert cfg.profile == Profile()
    assert (cfg.max_active, cfg.max_new_phrases, cfg.adopted_threshold) == (12, 2, 3)


def test_missing_config_tells_user_to_init(tmp_path):
    with pytest.raises(ConfigError, match="english-coach init"):
        load_config(_paths(tmp_path), env={})


def test_invalid_toml_names_the_file(tmp_path):
    p = _paths(tmp_path)
    p.config_dir.mkdir(parents=True)
    p.config_file.write_text("vault_path = \n", encoding="utf-8")
    with pytest.raises(ConfigError, match="config.toml"):
        load_config(p, env={})


def test_invalid_backend_rejected(tmp_path):
    p = _paths(tmp_path)
    p.config_dir.mkdir(parents=True)
    p.config_file.write_text('vault_path = "v"\nbackend = "gpt"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="backend"):
        load_config(p, env={})


def test_api_key_env_wins_over_secrets_file(tmp_path):
    p = _paths(tmp_path)
    save_config(p, Config(vault_path=tmp_path))
    save_api_key(p, "sk-ant-file")
    assert load_config(p, env={}).anthropic_api_key == "sk-ant-file"
    assert load_config(p, env={"ANTHROPIC_API_KEY": "sk-ant-env"}).anthropic_api_key == "sk-ant-env"


def test_api_key_not_in_repr_or_config_file(tmp_path):
    p = _paths(tmp_path)
    save_config(p, Config(vault_path=tmp_path, anthropic_api_key="sk-ant-secret"))
    assert "sk-ant-secret" not in p.config_file.read_text(encoding="utf-8")
    assert "sk-ant-secret" not in repr(Config(vault_path=tmp_path, anthropic_api_key="sk-ant-secret"))


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_secrets_file_is_user_only(tmp_path):
    p = _paths(tmp_path)
    save_api_key(p, "sk-ant-x")
    assert (os.stat(p.secrets_file).st_mode & 0o777) == 0o600
```

- [ ] **Step 2: Run** — `uv run pytest tests/test_config.py -q` → FAIL (imports).

- [ ] **Step 3: Rewrite `english_coach/config.py`**

```python
from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import platformdirs
import tomli_w

from english_coach.profile import Profile

APP_NAME = "english-coach"
DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_VAULT = Path.home() / "english-coach-vault"
_BACKENDS = ("cli", "api")


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class AppPaths:
    config_dir: Path

    @classmethod
    def default(cls, env: dict | None = None) -> "AppPaths":
        env = os.environ if env is None else env
        override = env.get("ENGLISH_COACH_CONFIG_DIR")
        if override:
            return cls(Path(override))
        return cls(Path(platformdirs.user_config_dir(APP_NAME, appauthor=False, roaming=True)))

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.toml"

    @property
    def secrets_file(self) -> Path:
        return self.config_dir / "secrets.toml"

    @property
    def lock_file(self) -> Path:
        return self.config_dir / "run.lock"

    @property
    def log_file(self) -> Path:
        return self.config_dir / "logs" / "coach.log"

    @property
    def last_run_file(self) -> Path:
        return self.config_dir / "last_run.json"

    @property
    def workdir(self) -> Path:
        return self.config_dir / "workdir"


@dataclass(frozen=True)
class Config:
    vault_path: Path
    timezone: str = "UTC"
    backend: str = "cli"
    model: str = DEFAULT_MODEL
    schedule_time: str = "07:00"
    profile: Profile = field(default_factory=Profile)
    adopted_threshold: int = 3
    max_active: int = 12
    max_new_phrases: int = 2
    anthropic_api_key: str = field(default="", repr=False)


def _read_toml(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from exc


def _api_key(paths: AppPaths, env: dict) -> str:
    if env.get("ANTHROPIC_API_KEY"):
        return env["ANTHROPIC_API_KEY"]
    if paths.secrets_file.exists():
        return str(_read_toml(paths.secrets_file).get("ANTHROPIC_API_KEY", ""))
    return ""


def load_config(paths: AppPaths, env: dict) -> Config:
    path = paths.config_file
    if not path.exists():
        raise ConfigError(f"No config at {path}. Run `english-coach init` first.")
    data = _read_toml(path)
    if "vault_path" not in data:
        raise ConfigError(f"{path}: missing 'vault_path'.")
    backend = data.get("backend", "cli")
    if backend not in _BACKENDS:
        raise ConfigError(f"{path}: backend must be one of {_BACKENDS}, got {backend!r}.")
    prof = data.get("profile", {})
    lim = data.get("limits", {})
    return Config(
        vault_path=Path(data["vault_path"]).expanduser(),
        timezone=data.get("timezone", "UTC"),
        backend=backend,
        model=data.get("model", DEFAULT_MODEL),
        schedule_time=data.get("schedule_time", "07:00"),
        profile=Profile(prof.get("native_language", ""),
                        prof.get("context", Profile().context)),
        adopted_threshold=int(lim.get("adopted_threshold", 3)),
        max_active=int(lim.get("max_active", 12)),
        max_new_phrases=int(lim.get("max_new_phrases", 2)),
        anthropic_api_key=_api_key(paths, env),
    )


def save_config(paths: AppPaths, config: Config) -> None:
    data = {
        "vault_path": str(config.vault_path),
        "timezone": config.timezone,
        "backend": config.backend,
        "model": config.model,
        "schedule_time": config.schedule_time,
        "profile": {"native_language": config.profile.native_language,
                    "context": config.profile.context},
        "limits": {"adopted_threshold": config.adopted_threshold,
                   "max_active": config.max_active,
                   "max_new_phrases": config.max_new_phrases},
    }
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.config_file.write_text(tomli_w.dumps(data), encoding="utf-8")


def save_api_key(paths: AppPaths, key: str) -> None:
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.secrets_file.write_text(tomli_w.dumps({"ANTHROPIC_API_KEY": key}), encoding="utf-8")
    if sys.platform != "win32":
        os.chmod(paths.secrets_file, 0o600)
```

- [ ] **Step 4: Write failing run-log tests**

```python
# tests/test_runlog.py
import sys
from datetime import datetime, timezone

from english_coach.runlog import read_last_run, run_log, write_last_run
from english_coach.transcripts import ReadStats


def test_run_log_tees_stdout_and_stderr(tmp_path, capsys):
    log = tmp_path / "logs" / "coach.log"
    with run_log(log):
        print("hello out")
        print("hello err", file=sys.stderr)
    text = log.read_text(encoding="utf-8")
    assert "hello out" in text and "hello err" in text and "=== run" in text
    captured = capsys.readouterr()
    assert "hello out" in captured.out


def test_run_log_rotates(tmp_path):
    log = tmp_path / "coach.log"
    log.write_text("x" * 600_000, encoding="utf-8")
    with run_log(log):
        print("fresh")
    assert (tmp_path / "coach.log.1").exists()
    assert "fresh" in log.read_text(encoding="utf-8")


def test_run_log_survives_missing_console(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)  # pythonw.exe has no console
    with run_log(tmp_path / "coach.log"):
        print("still logged")
    assert "still logged" in (tmp_path / "coach.log").read_text(encoding="utf-8")


def test_last_run_round_trip(tmp_path):
    p = tmp_path / "last_run.json"
    assert read_last_run(p) is None
    write_last_run(p, "wrote:2026-07-05", ReadStats(3, 40, 1, 12),
                   now=datetime(2026, 7, 6, 5, tzinfo=timezone.utc))
    data = read_last_run(p)
    assert data["status"] == "wrote:2026-07-05"
    assert data["stats"]["malformed"] == 1
    assert data["finished_at"].startswith("2026-07-06T05:00")
```

- [ ] **Step 5: Implement `english_coach/runlog.py`**

```python
from __future__ import annotations

import io
import json
import sys
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

_MAX_BYTES = 512_000
_BACKUPS = 3


class _Tee(io.TextIOBase):
    def __init__(self, *streams):
        self._streams = [s for s in streams if s is not None]

    def write(self, s):
        for st in self._streams:
            try:
                st.write(s)
            except (UnicodeEncodeError, ValueError):
                st.write(s.encode("ascii", "replace").decode("ascii"))
        return len(s)

    def flush(self):
        for st in self._streams:
            st.flush()


def _rotate(log_file: Path) -> None:
    if not log_file.exists() or log_file.stat().st_size < _MAX_BYTES:
        return
    for i in range(_BACKUPS, 0, -1):
        src = log_file if i == 1 else log_file.with_name(f"{log_file.name}.{i - 1}")
        dst = log_file.with_name(f"{log_file.name}.{i}")
        if src.exists():
            src.replace(dst)


@contextmanager
def run_log(log_file: Path):
    log_file = Path(log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    _rotate(log_file)
    with log_file.open("a", encoding="utf-8") as fh:
        fh.write(f"\n=== run {datetime.now().isoformat(timespec='seconds')} ===\n")
        out, err = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = _Tee(out, fh), _Tee(err, fh)
        try:
            yield
        finally:
            sys.stdout, sys.stderr = out, err


def write_last_run(path: Path, status: str, stats=None, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"finished_at": now.isoformat(), "status": status,
                                "stats": asdict(stats) if stats is not None else None},
                               indent=2), encoding="utf-8")


def read_last_run(path: Path) -> dict | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
```

- [ ] **Step 6: Rewire `coach.py`, `filtering.py` and their tests**

In `english_coach/coach.py`:
- Delete imports of `argparse`, `Path`, `load_config`, `LangfuseClient`, `ClaudeAnalyzer`, `ClaudeCliAnalyzer`, `enrich_phrases`, `enrich_patterns`, `extract_user_prompts`; delete `_DEFAULT_VAULT`, `_DEFAULT_MCP`, `_parse_date`, `main`, and the `if __name__ == "__main__":` block.
- Change the signature's second parameter from `langfuse` to `source`; delete the `is_reachable` block (the `"down"` status no longer exists).
- Replace the two lines that fetch traces and filter with:

```python
    prompts = filter_prompts(source.fetch_prompts(window.start_utc, window.end_utc))
```
- Keep `from english_coach.filtering import filter_prompts`.

In `english_coach/filtering.py` delete `_parse_ts`, `extract_user_prompts`, and the now-unused `datetime`/`timezone` import. In `tests/test_filtering.py` delete `test_extract_pulls_user_content_with_utc_timestamp` and drop `extract_user_prompts` from the import.

In `tests/test_coach.py`:
- `_cfg` becomes `return Config(vault_path=tmp_path, timezone="Europe/Warsaw")`.
- Replace `FakeLangfuse` with:

```python
from english_coach.models import UserPrompt


def _p(text, ts="2026-07-05T09:00:00+00:00"):
    return UserPrompt(text=text, timestamp_utc=datetime.fromisoformat(ts))


class FakeSource:
    def __init__(self, prompts):
        self._prompts = prompts

    def fetch_prompts(self, start_utc, end_utc):
        return self._prompts
```
- Delete `test_run_returns_down_when_unreachable` and `test_main_rejects_partial_override`.
- In every remaining test replace `traces = [{"input": {"role": "user", "content": X}, "timestamp": T}]` with `prompts = [_p(X, T)]` (convert `"...Z"` to `"...+00:00"`), and `FakeLangfuse(traces)` / `FakeLangfuse([])` with `FakeSource(prompts)` / `FakeSource([])`.
- Add:

```python
def test_run_passes_vault_patterns_to_analyzer(tmp_path):
    from english_coach.vault import ensure_pattern_note
    ensure_pattern_note(tmp_path, "Articles", "a/an/the usage")
    analyzer = FakeAnalyzer(_empty_analysis())
    run(_cfg(tmp_path), FakeSource([_p("Why we need here the reference?")]), analyzer, now_utc=NOW)
    assert analyzer.known_patterns == [("Articles", "a/an/the usage")]
```

In `tests/test_analyzer.py` change `_cfg()` to `return Config(vault_path=Path("."))`.

Delete the Langfuse client: `git rm english_coach/langfuse_client.py tests/test_langfuse_client.py`, and remove `"httpx>=0.27",` from `pyproject.toml` dependencies.

- [ ] **Step 7: Write failing CLI tests**

```python
# tests/test_cli_run.py
from datetime import date, datetime, timezone

from english_coach import cli
from english_coach.config import AppPaths, Config, save_config
from english_coach.models import Analysis, UserPrompt
from english_coach.runlog import read_last_run

NOW = datetime(2026, 7, 6, 5, tzinfo=timezone.utc)


class FakeSource:
    def __init__(self, prompts):
        from english_coach.transcripts import ReadStats
        self._prompts = prompts
        self.last_stats = ReadStats(prompts=len(prompts))

    def fetch_prompts(self, start_utc, end_utc):
        return self._prompts


class FakeAnalyzer:
    def analyze(self, prompts, phrasebook, known_patterns=()):
        return Analysis(wins=[], focus_pattern=None, recurring=[], new_phrases=[],
                        reused_phrases=[], snapshot=["ok"])


def _setup(tmp_path):
    paths = AppPaths(tmp_path / "cfg")
    cfg = Config(vault_path=tmp_path / "vault", timezone="Europe/Warsaw")
    save_config(paths, cfg)
    return paths, cfg


def _prompt():
    return UserPrompt("Why we need here the reference?", datetime(2026, 7, 5, 9, tzinfo=timezone.utc))


def test_execute_run_writes_note_log_and_last_run(tmp_path):
    paths, cfg = _setup(tmp_path)
    code, status = cli.execute_run(cfg, paths, env={}, now_utc=NOW, source=FakeSource([_prompt()]),
                                   analyzer=FakeAnalyzer(), runner=lambda p: '{"phrases": []}')
    assert (code, status) == (0, "wrote:2026-07-05")
    assert (cfg.vault_path / "Daily" / "2026-07-05.md").exists()
    assert "Wrote report" in paths.log_file.read_text(encoding="utf-8")
    assert read_last_run(paths.last_run_file)["status"] == "wrote:2026-07-05"
    assert not paths.lock_file.exists()


def test_execute_run_skips_when_locked(tmp_path):
    from english_coach.lock import run_lock
    paths, cfg = _setup(tmp_path)
    with run_lock(paths.lock_file):
        code, status = cli.execute_run(cfg, paths, env={}, now_utc=NOW,
                                       source=FakeSource([]), analyzer=FakeAnalyzer())
    assert (code, status) == (0, "locked")


def test_execute_run_failure_returns_1_and_keeps_watermark(tmp_path):
    from english_coach.state import read_watermark
    paths, cfg = _setup(tmp_path)

    class Boom(FakeAnalyzer):
        def analyze(self, *a, **k):
            raise RuntimeError("claude CLI failed")

    code, status = cli.execute_run(cfg, paths, env={}, now_utc=NOW,
                                   source=FakeSource([_prompt()]), analyzer=Boom())
    assert (code, status) == (1, "error")
    assert read_watermark(cfg.vault_path) is None
    assert "claude CLI failed" in paths.log_file.read_text(encoding="utf-8")


def test_main_run_without_config_explains_init(tmp_path, capsys):
    code = cli.main(["run"], env={"ENGLISH_COACH_CONFIG_DIR": str(tmp_path / "none")})
    assert code == 1
    assert "english-coach init" in capsys.readouterr().err


def test_main_rejects_partial_override(tmp_path):
    paths, _ = _setup(tmp_path)
    env = {"ENGLISH_COACH_CONFIG_DIR": str(paths.config_dir)}
    assert cli.main(["run", "--from", "2026-06-30"], env=env) == 1
```

- [ ] **Step 8: Implement `english_coach/cli.py` and `english_coach/__main__.py`**

```python
# english_coach/cli.py
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

from english_coach import coach, vault
from english_coach.analyzer import (
    ClaudeAnalyzer, ClaudeCliAnalyzer, enrich_patterns, enrich_phrases, run_claude_cli,
)
from english_coach.config import AppPaths, Config, ConfigError, load_config
from english_coach.curator import curate
from english_coach.lock import AlreadyRunning, run_lock
from english_coach.runlog import run_log, write_last_run
from english_coach.transcripts import TranscriptSource, default_projects_dir


def _parse_date(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


def make_runner(config: Config, paths: AppPaths):
    paths.workdir.mkdir(parents=True, exist_ok=True)
    return lambda prompt: run_claude_cli(prompt, model=config.model, cwd=paths.workdir)


def execute_run(config: Config, paths: AppPaths, env: dict, *, backfill_days: int = 1,
                override_from: date | None = None, override_to: date | None = None,
                include_today: bool = False, now_utc: datetime | None = None,
                analyzer=None, source=None, runner=None) -> tuple[int, str]:
    runner = runner or make_runner(config, paths)
    if analyzer is None:
        analyzer = (ClaudeAnalyzer(config) if config.backend == "api"
                    else ClaudeCliAnalyzer(config, runner=runner))
    source = source or TranscriptSource(default_projects_dir(env), exclude_cwd=paths.workdir)
    prof = config.profile
    with run_log(paths.log_file):
        try:
            with run_lock(paths.lock_file):
                status = coach.run(
                    config, source, analyzer, now_utc=now_utc or datetime.now(timezone.utc),
                    backfill_days=backfill_days, override_from=override_from,
                    override_to=override_to, include_today=include_today,
                    enricher=lambda items: enrich_phrases(items, runner=runner, profile=prof),
                    pattern_enricher=lambda items: enrich_patterns(items, runner=runner, profile=prof),
                    curator=lambda: curate(config.vault_path, runner=runner,
                                           max_active=config.max_active, profile=prof))
            code = 0
        except AlreadyRunning:
            print("Another english-coach run is in progress — skipping.")
            code, status = 0, "locked"
        except Exception as exc:  # scheduled runs must fail quietly and retry next time
            print(f"Run failed: {exc}", file=sys.stderr)
            code, status = 1, "error"
    if status != "locked":
        write_last_run(paths.last_run_file, status, getattr(source, "last_stats", None))
    return code, status


def _load(paths: AppPaths, env: dict, args) -> Config:
    config = load_config(paths, env)
    if getattr(args, "vault", None):
        config = replace(config, vault_path=Path(args.vault).expanduser())
    if getattr(args, "backend", None):
        config = replace(config, backend=args.backend)
    return config


def cmd_run(args, paths: AppPaths, env: dict) -> int:
    if bool(args.from_date) != bool(args.to_date):
        print("Error: --from and --to must be given together.", file=sys.stderr)
        return 1
    config = _load(paths, env, args)
    code, _ = execute_run(config, paths, env, backfill_days=args.backfill_days,
                          override_from=_parse_date(args.from_date),
                          override_to=_parse_date(args.to_date),
                          include_today=args.include_today)
    return code


def cmd_enrich(args, paths: AppPaths, env: dict) -> int:
    config = _load(paths, env, args)
    runner = make_runner(config, paths)
    prof = config.profile
    do_phrases = args.phrases or not args.patterns
    do_patterns = args.patterns or not args.phrases
    try:
        if do_phrases:
            n = vault.enrich_phrase_notes(
                config.vault_path, lambda items: enrich_phrases(items, runner=runner, profile=prof),
                force=args.force)
            print(f"Enriched {n} phrase note(s).")
        if do_patterns:
            n = vault.enrich_pattern_notes(
                config.vault_path, lambda items: enrich_patterns(items, runner=runner, profile=prof),
                force=args.force)
            print(f"Enriched {n} pattern note(s).")
        return 0
    except Exception as exc:
        print(f"Enrich failed: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="english-coach",
        description="Daily English coaching from your Claude Code prompts, in an Obsidian vault.")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Analyze completed days since the last run.")
    run.add_argument("--vault", default=None)
    run.add_argument("--backend", choices=["cli", "api"], default=None)
    run.add_argument("--backfill-days", type=int, default=1)
    run.add_argument("--from", dest="from_date", default=None)
    run.add_argument("--to", dest="to_date", default=None)
    run.add_argument("--include-today", action="store_true",
                     help="Also process today's prompts so far (does not advance the watermark).")
    run.set_defaults(func=cmd_run)

    enrich = sub.add_parser("enrich", help="Add definitions/examples/rules to bare notes.")
    enrich.add_argument("--vault", default=None)
    enrich.add_argument("--phrases", action="store_true")
    enrich.add_argument("--patterns", action="store_true")
    enrich.add_argument("--force", action="store_true", help="Regenerate ALL notes.")
    enrich.set_defaults(func=cmd_enrich)
    return parser


def main(argv: list[str] | None = None, env: dict | None = None) -> int:
    env = dict(os.environ) if env is None else env
    args = build_parser().parse_args(argv)
    paths = AppPaths.default(env)
    try:
        return args.func(args, paths, env)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 1
```

```python
# english_coach/__main__.py
from english_coach.cli import main

raise SystemExit(main())
```

Add to `pyproject.toml`:

```toml
[project.scripts]
english-coach = "english_coach.cli:main"
```

- [ ] **Step 9: Run everything** — `uv sync && uv run pytest -q` → all PASS. Then `uv run english-coach --help` → shows `run` and `enrich`.

- [ ] **Step 10: Commit** — `git add -A && git commit -m "feat: TOML config, run log, english-coach CLI; drop Langfuse" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"`

---

### Task 6: Vault skeleton with bundled Dataview

**Files:**
- Create: `english_coach/assets/__init__.py` (empty), `english_coach/assets/obsidian/community-plugins.json`, `english_coach/assets/obsidian/app.json`, `english_coach/assets/obsidian/plugins/dataview/{main.js,manifest.json,styles.css,LICENSE}`
- Create: `english_coach/skeleton.py`, `tests/test_skeleton.py`

**Interfaces:**
- Consumes: `vault.write_dashboard(vault: Path) -> Path`.
- Produces: `skeleton.DATAVIEW_VERSION: str`; `skeleton.create_skeleton(vault: Path) -> list[str]` — returns human-readable list of what was created; never overwrites notes or an existing `.obsidian/` config (only adds the Dataview plugin + enables it if missing).

Assets are stored as `assets/obsidian/` (no leading dot) so wheel packaging cannot drop them as hidden files; they are copied to `<vault>/.obsidian/`.

- [ ] **Step 1: Fetch the pinned Dataview release**

```bash
cd /c/Tools/english-coach-public
V=0.5.68
D=english_coach/assets/obsidian/plugins/dataview
mkdir -p "$D"
for f in main.js manifest.json styles.css; do
  curl -fsSL -o "$D/$f" "https://github.com/blacksmithgu/obsidian-dataview/releases/download/$V/$f"
done
curl -fsSL -o "$D/LICENSE" "https://raw.githubusercontent.com/blacksmithgu/obsidian-dataview/$V/LICENSE"
grep '"version"' "$D/manifest.json"
```
Expected: `"version": "0.5.68"`. If a download 404s, STOP and ask the user which Dataview release to pin (do not hunt for alternatives). Whatever version is pinned, set `DATAVIEW_VERSION` in Step 4 to match.

- [ ] **Step 2: Write the Obsidian config assets**

`english_coach/assets/obsidian/community-plugins.json`:
```json
["dataview"]
```
`english_coach/assets/obsidian/app.json`:
```json
{"promptDelete": true}
```
`english_coach/assets/__init__.py`: empty file.

- [ ] **Step 3: Write failing tests**

```python
# tests/test_skeleton.py
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from english_coach.skeleton import DATAVIEW_VERSION, create_skeleton


def test_creates_folders_dashboard_and_obsidian(tmp_path):
    v = tmp_path / "vault"
    created = create_skeleton(v)
    for d in ("Daily", "Phrases", "Patterns"):
        assert (v / d).is_dir()
    assert (v / "English Coaching.md").exists()
    manifest = json.loads((v / ".obsidian/plugins/dataview/manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == DATAVIEW_VERSION
    assert json.loads((v / ".obsidian/community-plugins.json").read_text()) == ["dataview"]
    assert created  # reports what it did


def test_existing_notes_and_obsidian_config_are_kept(tmp_path):
    v = tmp_path / "vault"
    (v / "Phrases").mkdir(parents=True)
    (v / "Phrases" / "park it.md").write_text("mine", encoding="utf-8")
    (v / ".obsidian").mkdir()
    (v / ".obsidian" / "app.json").write_text('{"mine": 1}', encoding="utf-8")
    (v / ".obsidian" / "community-plugins.json").write_text('["calendar"]', encoding="utf-8")
    create_skeleton(v)
    assert (v / "Phrases" / "park it.md").read_text(encoding="utf-8") == "mine"
    assert (v / ".obsidian" / "app.json").read_text(encoding="utf-8") == '{"mine": 1}'
    assert json.loads((v / ".obsidian/community-plugins.json").read_text()) == ["calendar", "dataview"]
    assert (v / ".obsidian/plugins/dataview/main.js").exists()


def test_second_run_is_noop(tmp_path):
    v = tmp_path / "vault"
    create_skeleton(v)
    assert create_skeleton(v) == []


@pytest.mark.slow
def test_wheel_contains_obsidian_assets(tmp_path):
    root = Path(__file__).resolve().parents[1]
    subprocess.run(["uv", "build", "--wheel", "--out-dir", str(tmp_path)], cwd=root, check=True)
    wheel = next(tmp_path.glob("*.whl"))
    names = zipfile.ZipFile(wheel).namelist()
    for f in ("english_coach/assets/obsidian/plugins/dataview/main.js",
              "english_coach/assets/obsidian/plugins/dataview/manifest.json",
              "english_coach/assets/obsidian/community-plugins.json"):
        assert f in names
```
Add `"slow: builds the wheel"` to the `markers` list in `pyproject.toml`.

- [ ] **Step 4: Implement `english_coach/skeleton.py`**

```python
from __future__ import annotations

import json
import shutil
from importlib.resources import as_file, files
from pathlib import Path

from english_coach import vault as vault_mod

DATAVIEW_VERSION = "0.5.68"
_FOLDERS = ("Daily", "Phrases", "Patterns")


def create_skeleton(vault: Path) -> list[str]:
    vault = Path(vault)
    created: list[str] = []
    for name in _FOLDERS:
        d = vault / name
        if not d.is_dir():
            d.mkdir(parents=True)
            created.append(f"folder {name}/")
    if not (vault / "English Coaching.md").exists():
        vault_mod.write_dashboard(vault)
        created.append("dashboard 'English Coaching.md'")

    obsidian = vault / ".obsidian"
    with as_file(files("english_coach") / "assets" / "obsidian") as src:
        if not obsidian.exists():
            shutil.copytree(src, obsidian)
            created.append(f".obsidian/ with Dataview {DATAVIEW_VERSION}")
            return created
        plugin = obsidian / "plugins" / "dataview"
        if not plugin.exists():
            shutil.copytree(src / "plugins" / "dataview", plugin)
            created.append(f"Dataview {DATAVIEW_VERSION} plugin")
    enabled_file = obsidian / "community-plugins.json"
    enabled = json.loads(enabled_file.read_text(encoding="utf-8")) if enabled_file.exists() else []
    if "dataview" not in enabled:
        enabled.append("dataview")
        enabled_file.write_text(json.dumps(enabled), encoding="utf-8")
        created.append("enabled Dataview")
    return created
```

- [ ] **Step 5: Run** — `uv run pytest -q` → all PASS (including the slow wheel test).

- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat: vault skeleton with bundled Dataview" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"`

---

### Task 7: OS scheduler (Windows, macOS, Linux) + `schedule` / `unschedule`

**Files:**
- Create: `english_coach/scheduler/__init__.py`, `english_coach/scheduler/windows.py`, `english_coach/scheduler/macos.py`, `english_coach/scheduler/linux.py`
- Create: `tests/test_scheduler.py`
- Modify: `english_coach/cli.py` (add two subcommands)

**Interfaces:**
- Consumes: `AppPaths`, `Config`, `load_config`, `save_config` (Task 5).
- Produces:
  - `scheduler.ScheduleStatus(installed: bool, detail: str)` (frozen dataclass)
  - `class scheduler.SchedulerUnavailable(RuntimeError)` — message contains manual instructions.
  - `scheduler.scheduled_command() -> list[str]` — `[<python>, "-m", "english_coach", "run"]`, preferring `pythonw.exe` next to `sys.executable` on Windows.
  - `scheduler.install(time_hhmm: str, log_dir: Path, command: list[str] | None = None, run=subprocess.run) -> str` (returns a human-readable summary), `scheduler.remove(run=subprocess.run) -> None`, `scheduler.status(run=subprocess.run) -> ScheduleStatus`.
  - Per OS pure renderers: `windows.render_task_xml(command, time_hhmm, user) -> str`; `macos.render_plist(command, time_hhmm, log_dir) -> bytes`; `linux.render_service(command) -> str`, `linux.render_timer(time_hhmm) -> str`, `linux.render_crontab(command, time_hhmm) -> str`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_scheduler.py
import os
import plistlib
import subprocess
import sys
from pathlib import Path

import pytest

from english_coach.scheduler import linux, macos, windows

SPACEY = [r"C:\Users\Jane Doe\AppData\Roaming\uv\tools\english-coach\Scripts\pythonw.exe",
          "-m", "english_coach", "run"]
POSIX_SPACEY = ["/Users/Jane Doe/.local/share/uv/tools/english-coach/bin/python",
                "-m", "english_coach", "run"]


class FakeRun:
    def __init__(self, returncode=0, stdout=""):
        self.calls = []
        self._rc, self._out = returncode, stdout

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        return subprocess.CompletedProcess(cmd, self._rc, self._out, "")


# --- Windows -----------------------------------------------------------------

def test_task_xml_has_daily_and_logon_triggers():
    xml = windows.render_task_xml(SPACEY, "07:05", r"DOMAIN\jane")
    assert "<StartBoundary>2026-01-01T07:05:00</StartBoundary>" in xml
    assert "<DaysInterval>1</DaysInterval>" in xml
    assert "<LogonTrigger>" in xml and "<Delay>PT5M</Delay>" in xml
    assert "<StartWhenAvailable>true</StartWhenAvailable>" in xml
    assert "<LogonType>InteractiveToken</LogonType>" in xml
    assert r"<UserId>DOMAIN\jane</UserId>" in xml


def test_task_xml_quotes_paths_with_spaces():
    xml = windows.render_task_xml(SPACEY, "07:00", "u")
    assert f"<Command>{SPACEY[0]}</Command>" in xml
    assert "<Arguments>-m english_coach run</Arguments>" in xml


def test_task_xml_escapes_xml_chars():
    xml = windows.render_task_xml([r"C:\A&B\python.exe", "-m", "english_coach", "run"], "07:00", "u")
    assert r"C:\A&amp;B\python.exe" in xml


def test_windows_install_calls_schtasks_with_xml(tmp_path):
    run = FakeRun()
    windows.install("07:00", SPACEY, run=run, user="u", tmp_dir=tmp_path)
    cmd = run.calls[0]
    assert cmd[:4] == ["schtasks", "/Create", "/TN", windows.TASK_NAME]
    xml_path = Path(cmd[cmd.index("/XML") + 1])
    assert xml_path.read_bytes()[:2] in (b"\xff\xfe", b"\xfe\xff")  # UTF-16 with BOM


# --- macOS -------------------------------------------------------------------

def test_plist_has_calendar_interval_and_run_at_load(tmp_path):
    data = plistlib.loads(macos.render_plist(POSIX_SPACEY, "07:05", tmp_path))
    assert data["Label"] == macos.LABEL
    assert data["ProgramArguments"] == POSIX_SPACEY  # list form: spaces need no quoting
    assert data["StartCalendarInterval"] == {"Hour": 7, "Minute": 5}
    assert data["RunAtLoad"] is True


def test_macos_install_writes_agent_and_bootstraps(tmp_path):
    run = FakeRun()
    macos.install("07:00", tmp_path / "logs", POSIX_SPACEY, run=run, home=tmp_path, uid=501)
    agent = tmp_path / "Library" / "LaunchAgents" / f"{macos.LABEL}.plist"
    assert agent.exists()
    assert ["launchctl", "bootstrap", "gui/501", str(agent)] in run.calls


# --- Linux -------------------------------------------------------------------

def test_service_quotes_paths_with_spaces():
    unit = linux.render_service(POSIX_SPACEY + ["50%"])
    assert 'ExecStart="/Users/Jane Doe/.local/share/uv/tools/english-coach/bin/python" ' in unit
    assert '"50%%"' in unit  # systemd specifier escaping


def test_timer_is_daily_and_persistent():
    timer = linux.render_timer("07:05")
    assert "OnCalendar=*-*-* 07:05:00" in timer
    assert "Persistent=true" in timer
    assert "WantedBy=timers.target" in timer


def test_crontab_fallback_lines():
    text = linux.render_crontab(POSIX_SPACEY, "07:05")
    assert text.splitlines()[0].startswith("5 7 * * * ")
    assert "@reboot" in text
    assert "'/Users/Jane Doe/.local/share/uv/tools/english-coach/bin/python'" in text


def test_linux_install_without_systemd_raises_with_crontab(tmp_path):
    run = FakeRun(returncode=1)
    with pytest.raises(Exception) as exc:
        linux.install("07:00", POSIX_SPACEY, run=run, config_home=tmp_path, systemd_ok=False)
    assert "crontab" in str(exc.value)


def test_linux_install_writes_units_and_enables(tmp_path):
    run = FakeRun()
    linux.install("07:00", POSIX_SPACEY, run=run, config_home=tmp_path, systemd_ok=True)
    assert (tmp_path / "systemd/user/english-coach.service").exists()
    assert (tmp_path / "systemd/user/english-coach.timer").exists()
    assert ["systemctl", "--user", "enable", "--now", "english-coach.timer"] in run.calls


# --- Real OS (opt-in) --------------------------------------------------------

@pytest.mark.integration
@pytest.mark.skipif(sys.platform != "win32" or os.environ.get("EC_SCHEDULER_IT") != "1",
                    reason="real Task Scheduler; set EC_SCHEDULER_IT=1")
def test_windows_real_install_status_remove(monkeypatch):
    monkeypatch.setattr(windows, "TASK_NAME", "English Coach IT")
    windows.install("03:33", [sys.executable, "-c", "pass"])
    try:
        assert windows.status().installed
    finally:
        windows.remove()
    assert not windows.status().installed
```

- [ ] **Step 2: Run** — `uv run pytest tests/test_scheduler.py -q` → FAIL (package missing).

- [ ] **Step 3: Implement `english_coach/scheduler/windows.py`**

```python
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

from english_coach.scheduler import ScheduleStatus

TASK_NAME = "English Coach"
_LOGON_DELAY = "PT5M"


def _default_user() -> str:
    domain, user = os.environ.get("USERDOMAIN", ""), os.environ.get("USERNAME", "")
    return f"{domain}\\{user}" if domain else user


def render_task_xml(command: list[str], time_hhmm: str, user: str) -> str:
    exe, args = command[0], subprocess.list2cmdline(command[1:])
    u = escape(user)
    # Daily trigger + logon trigger: an Interactive task whose daily trigger fires
    # before the user logs on is dropped, not deferred — the logon trigger catches up.
    # Running twice a day is harmless: the run is watermark-driven.
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Daily English coaching vault from Claude Code prompts.</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2026-01-01T{time_hhmm}:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{u}</UserId>
      <Delay>{_LOGON_DELAY}</Delay>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{u}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <ExecutionTimeLimit>PT30M</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(exe)}</Command>
      <Arguments>{escape(args)}</Arguments>
    </Exec>
  </Actions>
</Task>
"""


def install(time_hhmm: str, command: list[str], run=subprocess.run, user: str | None = None,
            tmp_dir: Path | None = None) -> str:
    xml = render_task_xml(command, time_hhmm, user or _default_user())
    tmp_dir = Path(tmp_dir or tempfile.gettempdir())
    xml_path = tmp_dir / "english-coach-task.xml"
    xml_path.write_text(xml, encoding="utf-16")  # schtasks requires UTF-16
    proc = run(["schtasks", "/Create", "/TN", TASK_NAME, "/XML", str(xml_path), "/F"],
               capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"schtasks failed: {(proc.stderr or proc.stdout).strip()}")
    return f"Task Scheduler: '{TASK_NAME}' daily at {time_hhmm}, plus at logon (+5 min)."


def remove(run=subprocess.run) -> None:
    run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], capture_output=True, text=True)


def status(run=subprocess.run) -> ScheduleStatus:
    proc = run(["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "LIST", "/V"],
               capture_output=True, text=True)
    if proc.returncode != 0:
        return ScheduleStatus(False, f"Task '{TASK_NAME}' not found.")
    keep = [l.strip() for l in proc.stdout.splitlines()
            if l.strip().startswith(("Next Run Time", "Last Run Time", "Last Result"))]
    return ScheduleStatus(True, "; ".join(keep) or f"Task '{TASK_NAME}' registered.")
```

- [ ] **Step 4: Implement `english_coach/scheduler/macos.py`**

```python
from __future__ import annotations

import os
import plistlib
import subprocess
from pathlib import Path

from english_coach.scheduler import ScheduleStatus

LABEL = "io.github.english-coach"


def render_plist(command: list[str], time_hhmm: str, log_dir: Path) -> bytes:
    hour, minute = (int(x) for x in time_hhmm.split(":"))
    return plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": list(command),
        "StartCalendarInterval": {"Hour": hour, "Minute": minute},
        "RunAtLoad": True,  # catch up at login; launchd also runs a missed interval after wake
        "StandardOutPath": str(Path(log_dir) / "launchd.log"),
        "StandardErrorPath": str(Path(log_dir) / "launchd.log"),
    })


def _agent_path(home: Path) -> Path:
    return Path(home) / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def install(time_hhmm: str, log_dir: Path, command: list[str], run=subprocess.run,
            home: Path | None = None, uid: int | None = None) -> str:
    home = Path(home or Path.home())
    uid = os.getuid() if uid is None else uid
    agent = _agent_path(home)
    agent.parent.mkdir(parents=True, exist_ok=True)
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    agent.write_bytes(render_plist(command, time_hhmm, log_dir))
    run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"], capture_output=True, text=True)
    proc = run(["launchctl", "bootstrap", f"gui/{uid}", str(agent)], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"launchctl bootstrap failed: {(proc.stderr or proc.stdout).strip()}")
    return f"launchd: {agent} daily at {time_hhmm}, plus at login."


def remove(run=subprocess.run, home: Path | None = None, uid: int | None = None) -> None:
    uid = os.getuid() if uid is None else uid
    run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"], capture_output=True, text=True)
    _agent_path(Path(home or Path.home())).unlink(missing_ok=True)


def status(run=subprocess.run, uid: int | None = None) -> ScheduleStatus:
    uid = os.getuid() if uid is None else uid
    proc = run(["launchctl", "print", f"gui/{uid}/{LABEL}"], capture_output=True, text=True)
    if proc.returncode != 0:
        return ScheduleStatus(False, f"launchd agent {LABEL} not loaded.")
    return ScheduleStatus(True, f"launchd agent {LABEL} loaded.")
```

- [ ] **Step 5: Implement `english_coach/scheduler/linux.py`**

```python
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

from english_coach.scheduler import ScheduleStatus, SchedulerUnavailable

UNIT = "english-coach"


def _sd_quote(arg: str) -> str:
    escaped = arg.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    return f'"{escaped}"'


def render_service(command: list[str]) -> str:
    return ("[Unit]\nDescription=English Coach daily run\n\n"
            "[Service]\nType=oneshot\n"
            f"ExecStart={' '.join(_sd_quote(a) for a in command)}\n")


def render_timer(time_hhmm: str) -> str:
    return ("[Unit]\nDescription=English Coach daily timer\n\n"
            f"[Timer]\nOnCalendar=*-*-* {time_hhmm}:00\nPersistent=true\n\n"
            "[Install]\nWantedBy=timers.target\n")


def render_crontab(command: list[str], time_hhmm: str) -> str:
    hour, minute = (int(x) for x in time_hhmm.split(":"))
    cmd = " ".join(shlex.quote(a) for a in command)
    return f"{minute} {hour} * * * {cmd}\n@reboot sleep 300 && {cmd}\n"


def _config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def systemd_available(run=subprocess.run) -> bool:
    if not shutil.which("systemctl"):
        return False
    return run(["systemctl", "--user", "show-environment"],
               capture_output=True, text=True).returncode == 0


def install(time_hhmm: str, command: list[str], run=subprocess.run,
            config_home: Path | None = None, systemd_ok: bool | None = None) -> str:
    ok = systemd_available(run) if systemd_ok is None else systemd_ok
    if not ok:
        raise SchedulerUnavailable(
            "systemd user timers are not available. Add these lines with `crontab -e`:\n"
            + render_crontab(command, time_hhmm))
    unit_dir = Path(config_home or _config_home()) / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    (unit_dir / f"{UNIT}.service").write_text(render_service(command), encoding="utf-8")
    (unit_dir / f"{UNIT}.timer").write_text(render_timer(time_hhmm), encoding="utf-8")
    run(["systemctl", "--user", "daemon-reload"], capture_output=True, text=True)
    proc = run(["systemctl", "--user", "enable", "--now", f"{UNIT}.timer"],
               capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"systemctl failed: {(proc.stderr or proc.stdout).strip()}")
    return f"systemd: {UNIT}.timer daily at {time_hhmm} (Persistent: catches up after boot)."


def remove(run=subprocess.run, config_home: Path | None = None) -> None:
    run(["systemctl", "--user", "disable", "--now", f"{UNIT}.timer"], capture_output=True, text=True)
    unit_dir = Path(config_home or _config_home()) / "systemd" / "user"
    for suffix in ("service", "timer"):
        (unit_dir / f"{UNIT}.{suffix}").unlink(missing_ok=True)
    run(["systemctl", "--user", "daemon-reload"], capture_output=True, text=True)


def status(run=subprocess.run) -> ScheduleStatus:
    if not shutil.which("systemctl"):
        return ScheduleStatus(False, "systemd not available (check your crontab).")
    proc = run(["systemctl", "--user", "is-enabled", f"{UNIT}.timer"], capture_output=True, text=True)
    if proc.returncode != 0:
        return ScheduleStatus(False, f"{UNIT}.timer not enabled.")
    nxt = run(["systemctl", "--user", "list-timers", f"{UNIT}.timer", "--no-pager"],
              capture_output=True, text=True).stdout.strip().splitlines()
    return ScheduleStatus(True, nxt[1] if len(nxt) > 1 else f"{UNIT}.timer enabled.")
```

- [ ] **Step 6: Implement `english_coach/scheduler/__init__.py`**

```python
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ScheduleStatus:
    installed: bool
    detail: str


class SchedulerUnavailable(RuntimeError):
    """No supported scheduler; the message tells the user what to do manually."""


def scheduled_command() -> list[str]:
    exe = Path(sys.executable)
    if sys.platform == "win32":
        pyw = exe.with_name("pythonw.exe")  # no console window flashing every morning
        if pyw.exists():
            exe = pyw
    return [str(exe), "-m", "english_coach", "run"]


def _backend():
    if sys.platform == "win32":
        from english_coach.scheduler import windows as m
    elif sys.platform == "darwin":
        from english_coach.scheduler import macos as m
    else:
        from english_coach.scheduler import linux as m
    return m


def install(time_hhmm: str, log_dir: Path, command: list[str] | None = None,
            run=subprocess.run) -> str:
    m = _backend()
    command = command or scheduled_command()
    if m.__name__.endswith("macos"):
        return m.install(time_hhmm, log_dir, command, run=run)
    return m.install(time_hhmm, command, run=run)


def remove(run=subprocess.run) -> None:
    _backend().remove(run=run)


def status(run=subprocess.run) -> ScheduleStatus:
    return _backend().status(run=run)
```

- [ ] **Step 7: Add `schedule` / `unschedule` to `english_coach/cli.py`**

Add import `from english_coach import scheduler` and `from english_coach.config import save_config`, then these handlers:

```python
def _valid_time(s: str) -> str:
    hh, mm = s.split(":")
    if not (0 <= int(hh) <= 23 and 0 <= int(mm) <= 59):
        raise argparse.ArgumentTypeError("time must be HH:MM")
    return f"{int(hh):02d}:{int(mm):02d}"


def cmd_schedule(args, paths: AppPaths, env: dict) -> int:
    config = load_config(paths, env)
    if args.time:
        config = replace(config, schedule_time=args.time)
        save_config(paths, config)
    try:
        print(scheduler.install(config.schedule_time, paths.log_file.parent))
        return 0
    except scheduler.SchedulerUnavailable as exc:
        print(str(exc))
        return 1
    except RuntimeError as exc:
        print(f"Scheduling failed: {exc}", file=sys.stderr)
        return 1


def cmd_unschedule(args, paths: AppPaths, env: dict) -> int:
    scheduler.remove()
    print("Removed the daily english-coach job.")
    return 0
```
and in `build_parser()` before `return parser`:

```python
    sch = sub.add_parser("schedule", help="Register (or update) the daily OS job.")
    sch.add_argument("--time", type=_valid_time, default=None, help="HH:MM, local time.")
    sch.set_defaults(func=cmd_schedule)
    unsch = sub.add_parser("unschedule", help="Remove the daily OS job.")
    unsch.set_defaults(func=cmd_unschedule)
```

Add to `tests/test_scheduler.py`:

```python
def test_cli_schedule_saves_time_and_installs(tmp_path, monkeypatch):
    from english_coach import cli, scheduler
    from english_coach.config import AppPaths, Config, load_config, save_config
    paths = AppPaths(tmp_path / "cfg")
    save_config(paths, Config(vault_path=tmp_path / "v"))
    seen = {}
    monkeypatch.setattr(scheduler, "install", lambda t, log_dir, **k: seen.setdefault("t", t) or "ok")
    env = {"ENGLISH_COACH_CONFIG_DIR": str(paths.config_dir)}
    assert cli.main(["schedule", "--time", "6:30"], env=env) == 0
    assert seen["t"] == "06:30"
    assert load_config(paths, env={}).schedule_time == "06:30"
```

- [ ] **Step 8: Run** — `uv run pytest -q` → all PASS. On Windows, also run the real integration test once: `EC_SCHEDULER_IT=1 uv run pytest tests/test_scheduler.py -m integration -q` → PASS (creates and deletes the task "English Coach IT").

- [ ] **Step 9: Commit** — `git add -A && git commit -m "feat: cross-platform daily scheduling (Task Scheduler, launchd, systemd)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"`

---

### Task 8: `english-coach doctor`

**Files:**
- Create: `english_coach/doctor.py`, `tests/test_doctor.py`
- Modify: `english_coach/cli.py` (add subcommand)

**Interfaces:**
- Consumes: `AppPaths`, `load_config`, `ConfigError` (Task 5); `default_projects_dir` (Task 2); `read_last_run` (Task 5); `scheduler.status` (Task 7); `analyzer._resolve_claude`, `run_claude_cli` (Task 4).
- Produces: `@dataclass(frozen=True) Check(name: str, ok: bool, detail: str)`; `doctor.run_checks(paths: AppPaths, env: dict, *, ping: bool = False, which=_find_claude, sched_status=None, claude_ping=None, now: datetime | None = None) -> list[Check]`; `doctor.format_checks(checks) -> str`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_doctor.py
import os
import time
from datetime import datetime, timezone

from english_coach.config import AppPaths, Config, save_config
from english_coach.doctor import Check, format_checks, run_checks
from english_coach.runlog import write_last_run
from english_coach.scheduler import ScheduleStatus
from english_coach.transcripts import ReadStats


def _env(tmp_path):
    proj = tmp_path / "claude" / "projects" / "C--x"
    proj.mkdir(parents=True)
    (proj / "s.jsonl").write_text("{}\n", encoding="utf-8")
    return {"CLAUDE_CONFIG_DIR": str(tmp_path / "claude")}


def _by_name(checks):
    return {c.name: c for c in checks}


def test_all_green(tmp_path):
    paths = AppPaths(tmp_path / "cfg")
    (tmp_path / "vault").mkdir()
    save_config(paths, Config(vault_path=tmp_path / "vault"))
    write_last_run(paths.last_run_file, "wrote:2026-07-05", ReadStats(1, 2, 0, 1))
    checks = run_checks(paths, _env(tmp_path), which=lambda n: "/bin/claude",
                        sched_status=lambda: ScheduleStatus(True, "next 07:00"))
    assert all(c.ok for c in checks), format_checks(checks)
    assert set(_by_name(checks)) == {"claude CLI", "transcripts", "config", "vault",
                                     "schedule", "last run"}


def test_missing_config_and_claude_fail_with_hints(tmp_path):
    paths = AppPaths(tmp_path / "cfg")
    checks = _by_name(run_checks(paths, {"CLAUDE_CONFIG_DIR": str(tmp_path / "none")},
                                 which=lambda n: None,
                                 sched_status=lambda: ScheduleStatus(False, "not found")))
    assert not checks["claude CLI"].ok and "install" in checks["claude CLI"].detail.lower()
    assert not checks["transcripts"].ok
    assert not checks["config"].ok and "english-coach init" in checks["config"].detail
    assert not checks["schedule"].ok


def test_last_run_error_and_malformed_lines_are_reported(tmp_path):
    paths = AppPaths(tmp_path / "cfg")
    (tmp_path / "vault").mkdir()
    save_config(paths, Config(vault_path=tmp_path / "vault"))
    write_last_run(paths.last_run_file, "error", ReadStats(3, 100, 40, 0))
    last = _by_name(run_checks(paths, _env(tmp_path), which=lambda n: "c",
                               sched_status=lambda: ScheduleStatus(True, "")))["last run"]
    assert not last.ok
    assert "error" in last.detail and "40 malformed" in last.detail


def test_ping_failure_is_reported(tmp_path):
    paths = AppPaths(tmp_path / "cfg")

    def bad_ping():
        raise RuntimeError("not logged in")

    checks = _by_name(run_checks(paths, _env(tmp_path), ping=True, which=lambda n: "c",
                                 sched_status=lambda: ScheduleStatus(True, ""), claude_ping=bad_ping))
    assert not checks["claude CLI"].ok and "not logged in" in checks["claude CLI"].detail


def test_format_is_ascii():
    out = format_checks([Check("a", True, "fine"), Check("b", False, "broken")])
    assert out.isascii() and "[OK]" in out and "[FAIL]" in out
```

- [ ] **Step 2: Run** — `uv run pytest tests/test_doctor.py -q` → FAIL.

- [ ] **Step 3: Implement `english_coach/doctor.py`**

```python
from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timezone

from english_coach import scheduler
from english_coach.analyzer import _resolve_claude, run_claude_cli
from english_coach.config import AppPaths, ConfigError, load_config
from english_coach.runlog import read_last_run
from english_coach.transcripts import default_projects_dir

_STALE_DAYS = 3


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def _find_claude(name: str = "claude") -> str | None:
    found = _resolve_claude()  # env override -> PATH -> ~/.local/bin
    return found if found != "claude" else shutil.which(name)


def _check_claude(which, ping: bool, claude_ping) -> Check:
    path = which("claude")
    if not path:
        return Check("claude CLI", False,
                     "Not found. Install Claude Code and log in: https://docs.claude.com/claude-code")
    if ping:
        try:
            claude_ping()
        except Exception as exc:
            return Check("claude CLI", False, f"{path} found but a test call failed: {exc}")
    return Check("claude CLI", True, path)


def _check_transcripts(env: dict, now: datetime) -> Check:
    d = default_projects_dir(env)
    if not d.is_dir():
        return Check("transcripts", False, f"{d} does not exist. Use Claude Code at least once.")
    files = list(d.rglob("*.jsonl"))
    if not files:
        return Check("transcripts", False, f"{d} has no session files yet.")
    newest = datetime.fromtimestamp(max(f.stat().st_mtime for f in files), timezone.utc)
    return Check("transcripts", True, f"{len(files)} files in {d}; newest {newest:%Y-%m-%d %H:%M} UTC")


def run_checks(paths: AppPaths, env: dict, *, ping: bool = False, which=_find_claude,
               sched_status=None, claude_ping=None, now: datetime | None = None) -> list[Check]:
    now = now or datetime.now(timezone.utc)
    claude_ping = claude_ping or (lambda: run_claude_cli("Reply with the single word OK.",
                                                         cwd=paths.workdir, timeout=60))
    checks = [_check_claude(which, ping, claude_ping), _check_transcripts(env, now)]

    config = None
    try:
        config = load_config(paths, env)
        checks.append(Check("config", True, str(paths.config_file)))
    except ConfigError as exc:
        checks.append(Check("config", False, str(exc)))

    if config is None:
        checks.append(Check("vault", False, "No config — run `english-coach init`."))
    elif config.vault_path.is_dir():
        checks.append(Check("vault", True, str(config.vault_path)))
    else:
        checks.append(Check("vault", False, f"{config.vault_path} missing — run `english-coach init`."))

    st = (sched_status or scheduler.status)()
    checks.append(Check("schedule", st.installed,
                        st.detail if st.installed else f"{st.detail} Run `english-coach schedule`."))

    last = read_last_run(paths.last_run_file)
    if last is None:
        checks.append(Check("last run", False, "Never ran. Try `english-coach run`."))
    else:
        stats = last.get("stats") or {}
        detail = f"{last['status']} at {last['finished_at']}"
        if stats:
            detail += (f"; {stats.get('prompts', 0)} prompts, "
                       f"{stats.get('malformed', 0)} malformed lines of {stats.get('lines_read', 0)}")
        finished = datetime.fromisoformat(last["finished_at"])
        ok = last["status"] != "error" and (now - finished).days <= _STALE_DAYS
        if stats.get("lines_read") and stats.get("malformed", 0) > stats["lines_read"] * 0.2:
            ok = False
            detail += " — many unreadable lines; Claude Code's transcript format may have changed"
        checks.append(Check("last run", ok, detail + f". Log: {paths.log_file}"))
    return checks


def format_checks(checks: list[Check]) -> str:
    lines = [f"{'[OK]  ' if c.ok else '[FAIL]'} {c.name}: {c.detail}" for c in checks]
    return "\n".join(lines).encode("ascii", "replace").decode("ascii")
```

- [ ] **Step 4: Add the subcommand in `english_coach/cli.py`**

```python
def cmd_doctor(args, paths: AppPaths, env: dict) -> int:
    from english_coach.doctor import format_checks, run_checks
    checks = run_checks(paths, env, ping=args.ping)
    print(format_checks(checks))
    return 0 if all(c.ok for c in checks) else 1
```
In `build_parser()`:
```python
    doc = sub.add_parser("doctor", help="Check that everything is set up.")
    doc.add_argument("--ping", action="store_true", help="Also make a tiny test call to Claude.")
    doc.set_defaults(func=cmd_doctor)
```

- [ ] **Step 5: Run** — `uv run pytest -q` → all PASS. `uv run english-coach doctor` → prints six ASCII lines (config will FAIL until init exists — expected).

- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat: english-coach doctor health checks" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"`

---

### Task 9: `english-coach init` wizard

**Files:**
- Create: `english_coach/init_wizard.py`, `tests/test_init_wizard.py`
- Modify: `english_coach/cli.py` (add subcommand)

**Interfaces:**
- Consumes: `AppPaths, Config, load_config, save_config, save_api_key, DEFAULT_VAULT, ConfigError` (Task 5); `Profile` (Task 4); `create_skeleton` (Task 6); `scheduler.install`, `SchedulerUnavailable` (Task 7); `doctor.run_checks` pieces are **not** used — init does its own two prerequisite checks; `execute_run` (Task 5); `TranscriptSource`, `default_projects_dir` (Task 2); `compute_window` (existing); `filter_prompts` (existing).
- Produces:
  - `class Prompter(answers: dict | None = None, assume_yes: bool = False, input_fn=input, out=print)` with `ask(key: str, question: str, default: str) -> str` and `confirm(key: str, question: str, default: bool = True) -> bool`. `answers` pre-fills by key (flags); `assume_yes` returns defaults without prompting.
  - `detect_timezone() -> str`
  - `init(paths: AppPaths, env: dict, prompter: Prompter, *, check_claude=None, schedule=None, do_run=None, now_utc=None) -> int`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_init_wizard.py
import json
from datetime import datetime, timezone
from pathlib import Path

from english_coach.config import AppPaths, load_config
from english_coach.init_wizard import Prompter, init
from english_coach.profile import Profile

NOW = datetime(2026, 7, 6, 5, tzinfo=timezone.utc)


def _env(tmp_path, prompts=("How should we name this?",)):
    proj = tmp_path / "claude" / "projects" / "C--x"
    proj.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"type": "user", "uuid": f"u{i}", "timestamp": "2026-07-05T09:00:00Z",
                         "cwd": "/p", "message": {"role": "user", "content": t}})
             for i, t in enumerate(prompts)]
    (proj / "s.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"CLAUDE_CONFIG_DIR": str(tmp_path / "claude")}


class Recorder:
    def __init__(self):
        self.schedule_calls, self.run_calls = [], []

    def schedule(self, time_hhmm, log_dir):
        self.schedule_calls.append(time_hhmm)
        return "scheduled"

    def do_run(self, config, paths, env, backfill_days):
        self.run_calls.append(backfill_days)
        return 0, "wrote:x"


def _answers(tmp_path, **over):
    a = {"vault": str(tmp_path / "vault"), "native_language": "Polish",
         "context": "software developer", "timezone": "Europe/Warsaw", "backend": "cli",
         "backfill_days": "7", "run_backfill": True, "time": "07:00", "schedule": True}
    a.update(over)
    return a


def test_init_happy_path(tmp_path):
    paths, rec = AppPaths(tmp_path / "cfg"), Recorder()
    code = init(paths, _env(tmp_path), Prompter(_answers(tmp_path)), check_claude=lambda: None,
                schedule=rec.schedule, do_run=rec.do_run, now_utc=NOW)
    assert code == 0
    cfg = load_config(paths, env={})
    assert cfg.vault_path == tmp_path / "vault"
    assert cfg.profile == Profile("Polish", "software developer")
    assert cfg.timezone == "Europe/Warsaw"
    assert (tmp_path / "vault" / ".obsidian" / "plugins" / "dataview" / "main.js").exists()
    assert rec.run_calls == [7] and rec.schedule_calls == ["07:00"]


def test_init_stops_when_claude_missing(tmp_path):
    paths = AppPaths(tmp_path / "cfg")

    def missing():
        raise RuntimeError("claude not found")

    lines = []
    code = init(paths, _env(tmp_path), Prompter(_answers(tmp_path), out=lines.append),
                check_claude=missing, schedule=Recorder().schedule, do_run=Recorder().do_run)
    assert code == 1
    assert not paths.config_file.exists()
    assert any("claude not found" in l for l in lines)


def test_init_stops_when_no_transcripts(tmp_path):
    paths = AppPaths(tmp_path / "cfg")
    code = init(paths, {"CLAUDE_CONFIG_DIR": str(tmp_path / "none")}, Prompter(_answers(tmp_path)),
                check_claude=lambda: None, schedule=Recorder().schedule, do_run=Recorder().do_run)
    assert code == 1


def test_init_rerun_keeps_existing_and_uses_previous_answers(tmp_path):
    paths, rec = AppPaths(tmp_path / "cfg"), Recorder()
    env = _env(tmp_path)
    init(paths, env, Prompter(_answers(tmp_path, native_language="German", time="06:15")),
         check_claude=lambda: None, schedule=rec.schedule, do_run=rec.do_run, now_utc=NOW)
    note = tmp_path / "vault" / "Phrases" / "park it.md"
    note.write_text("my note", encoding="utf-8")
    # Second run: accept every default -> must reuse previous answers, not factory defaults.
    init(paths, env, Prompter(assume_yes=True), check_claude=lambda: None,
         schedule=rec.schedule, do_run=rec.do_run, now_utc=NOW)
    cfg = load_config(paths, env={})
    assert cfg.profile.native_language == "German"
    assert cfg.schedule_time == "06:15"
    assert note.read_text(encoding="utf-8") == "my note"


def test_init_api_backend_saves_key(tmp_path):
    paths = AppPaths(tmp_path / "cfg")
    init(paths, _env(tmp_path), Prompter(_answers(tmp_path, backend="api", api_key="sk-ant-x")),
         check_claude=lambda: None, schedule=Recorder().schedule, do_run=Recorder().do_run,
         now_utc=NOW)
    assert load_config(paths, env={}).anthropic_api_key == "sk-ant-x"


def test_init_can_skip_backfill_and_schedule(tmp_path):
    paths, rec = AppPaths(tmp_path / "cfg"), Recorder()
    init(paths, _env(tmp_path), Prompter(_answers(tmp_path, run_backfill=False, schedule=False)),
         check_claude=lambda: None, schedule=rec.schedule, do_run=rec.do_run, now_utc=NOW)
    assert rec.run_calls == [] and rec.schedule_calls == []


def test_prompter_uses_input_and_default():
    replies = iter(["", "Spanish"])
    p = Prompter(input_fn=lambda q: next(replies), out=lambda s: None)
    assert p.ask("a", "Vault?", "/v") == "/v"
    assert p.ask("b", "Language?", "") == "Spanish"
```

- [ ] **Step 2: Run** — `uv run pytest tests/test_init_wizard.py -q` → FAIL.

- [ ] **Step 3: Implement `english_coach/init_wizard.py`**

```python
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from english_coach import scheduler
from english_coach.config import (
    AppPaths, Config, ConfigError, DEFAULT_VAULT, load_config, save_api_key, save_config,
)
from english_coach.filtering import filter_prompts
from english_coach.profile import Profile
from english_coach.skeleton import create_skeleton
from english_coach.transcripts import TranscriptSource, default_projects_dir
from english_coach.window import compute_window


class Prompter:
    def __init__(self, answers: dict | None = None, assume_yes: bool = False,
                 input_fn=input, out=print):
        self._answers = answers or {}
        self._yes = assume_yes
        self._input = input_fn
        self.out = out

    def ask(self, key: str, question: str, default: str) -> str:
        if key in self._answers and self._answers[key] is not None:
            return str(self._answers[key])
        if self._yes:
            return default
        reply = self._input(f"{question} [{default}]: ").strip()
        return reply or default

    def confirm(self, key: str, question: str, default: bool = True) -> bool:
        if key in self._answers and self._answers[key] is not None:
            return bool(self._answers[key])
        if self._yes:
            return default
        reply = self._input(f"{question} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
        return default if not reply else reply.startswith("y")


def detect_timezone() -> str:
    try:
        from tzlocal import get_localzone_name
        return get_localzone_name() or "UTC"
    except Exception:
        return "UTC"


def _default_check_claude(paths: AppPaths):
    from english_coach.analyzer import run_claude_cli
    paths.workdir.mkdir(parents=True, exist_ok=True)
    run_claude_cli("Reply with the single word OK.", cwd=paths.workdir, timeout=60)


def _default_do_run(config, paths, env, backfill_days):
    from english_coach.cli import execute_run
    return execute_run(config, paths, env, backfill_days=backfill_days)


def init(paths: AppPaths, env: dict, prompter: Prompter, *, check_claude=None, schedule=None,
         do_run=None, now_utc: datetime | None = None) -> int:
    out = prompter.out
    now_utc = now_utc or datetime.now(timezone.utc)
    check_claude = check_claude or (lambda: _default_check_claude(paths))
    schedule = schedule or (lambda t, log_dir: scheduler.install(t, log_dir))
    do_run = do_run or _default_do_run

    # 1. Prerequisites
    out("Checking Claude Code...")
    try:
        check_claude()
    except Exception as exc:
        out(f"Claude Code is not ready: {exc}")
        out("Install Claude Code, run `claude` once to log in, then re-run `english-coach init`.")
        return 1
    projects = default_projects_dir(env)
    if not projects.is_dir() or not any(projects.rglob("*.jsonl")):
        out(f"No Claude Code transcripts found in {projects}. Use Claude Code for a while first.")
        return 1

    # Previous answers become defaults on re-run.
    try:
        prev = load_config(paths, env)
    except ConfigError:
        prev = Config(vault_path=DEFAULT_VAULT, timezone=detect_timezone())

    # 2-5. Questions
    vault = Path(prompter.ask("vault", "Where should the vault live?", str(prev.vault_path))).expanduser()
    lang = prompter.ask("native_language", "Your native language (blank to skip)?",
                        prev.profile.native_language)
    ctx = prompter.ask("context", "Your role / context, in a few words?", prev.profile.context)
    tz = prompter.ask("timezone", "Timezone?", prev.timezone)
    backend = prompter.ask("backend", "Backend: 'cli' (Claude Code login) or 'api' (API key)?",
                           prev.backend)
    if backend not in ("cli", "api"):
        out(f"Unknown backend {backend!r}; using 'cli'.")
        backend = "cli"
    if backend == "api" and not env.get("ANTHROPIC_API_KEY"):
        key = prompter.ask("api_key", "Anthropic API key (or set ANTHROPIC_API_KEY)?", "")
        if key:
            save_api_key(paths, key)

    config = replace(prev, vault_path=vault, timezone=tz, backend=backend,
                     profile=Profile(lang, ctx))

    # 6. Vault skeleton + config
    for item in create_skeleton(vault):
        out(f"  created {item}")
    save_config(paths, config)
    config = load_config(paths, env)  # picks up the saved API key
    out(f"Config saved to {paths.config_file}")

    # 7. First backfill
    days = int(prompter.ask("backfill_days", "Analyze how many past days now?", "7"))
    if days > 0:
        w = compute_window(now_utc, None, config.timezone, backfill_days=days)
        found = filter_prompts(TranscriptSource(projects, exclude_cwd=paths.workdir)
                               .fetch_prompts(w.start_utc, w.end_utc))
        out(f"Found {len(found)} prompts in the last {days} day(s).")
        if found and prompter.confirm("run_backfill", "Analyze them now (one Claude call)?", True):
            code, status = do_run(config, paths, env, days)
            out(f"First run: {status}")

    # 8. Schedule
    t = prompter.ask("time", "Daily run time (HH:MM)?", prev.schedule_time)
    config = replace(config, schedule_time=t)
    save_config(paths, config)
    if prompter.confirm("schedule", "Register the daily job now?", True):
        try:
            out(schedule(t, paths.log_file.parent))
        except scheduler.SchedulerUnavailable as exc:
            out(str(exc))
        except RuntimeError as exc:
            out(f"Scheduling failed: {exc}. You can retry with `english-coach schedule`.")

    # 9. Summary
    out("")
    out("Done.")
    out(f"  Vault:  {vault}  -> open this folder in Obsidian and trust the Dataview plugin when asked.")
    out(f"  Config: {paths.config_file}")
    out(f"  Log:    {paths.log_file}")
    out("  Check health any time with `english-coach doctor`.")
    return 0
```

- [ ] **Step 4: Add the subcommand in `english_coach/cli.py`**

```python
def cmd_init(args, paths: AppPaths, env: dict) -> int:
    from english_coach.init_wizard import Prompter, init
    answers = {
        "vault": args.vault, "native_language": args.native_language, "context": args.context,
        "timezone": args.timezone, "backend": args.backend,
        "backfill_days": args.backfill_days, "time": args.time,
        "schedule": False if args.no_schedule else None,
    }
    return init(paths, env, Prompter(answers, assume_yes=args.yes))
```
In `build_parser()`:
```python
    ini = sub.add_parser("init", help="Set up config, vault, first run and daily schedule.")
    ini.add_argument("--yes", action="store_true", help="Accept defaults without prompting.")
    ini.add_argument("--vault", default=None)
    ini.add_argument("--native-language", default=None)
    ini.add_argument("--context", default=None)
    ini.add_argument("--timezone", default=None)
    ini.add_argument("--backend", choices=["cli", "api"], default=None)
    ini.add_argument("--backfill-days", type=int, default=None)
    ini.add_argument("--time", type=_valid_time, default=None)
    ini.add_argument("--no-schedule", action="store_true")
    ini.set_defaults(func=cmd_init)
```

- [ ] **Step 5: Run** — `uv run pytest -q` → all PASS.

- [ ] **Step 6: Manual smoke test in a throwaway config dir** (uses the real `claude`; no scheduling):

```bash
ENGLISH_COACH_CONFIG_DIR="$TEMP/ec-smoke" uv run english-coach init --vault "$TEMP/ec-smoke-vault" --backfill-days 1 --no-schedule
ENGLISH_COACH_CONFIG_DIR="$TEMP/ec-smoke" uv run english-coach doctor
```
Expected: init prints created items + "Done."; doctor shows `[OK]` for claude, transcripts, config, vault, last run, and `[FAIL]` for schedule (expected — skipped). Report output to the user; delete `$TEMP/ec-smoke*` afterwards.

- [ ] **Step 7: Commit** — `git add -A && git commit -m "feat: english-coach init wizard" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"`

---

### Task 10: README, CI, personal-data guard, release branch

**Files:**
- Create: `README.md`, `.github/workflows/ci.yml`, `tests/test_no_personal_data.py`
- Modify: `pyproject.toml` (add `readme = "README.md"`)

**Interfaces:**
- Consumes: the finished CLI (`init`, `run`, `enrich`, `doctor`, `schedule`, `unschedule`).
- Produces: a publishable repo; branch `release` with a single clean commit.

- [ ] **Step 1: Write the personal-data guard test**

```python
# tests/test_no_personal_data.py
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Assembled from pieces so this file does not match itself.
FORBIDDEN = [
    r"C:\\Users\\[A-Za-z]",            # absolute Windows user paths
    "soft" + "wareone", "mpt" + "-library", "ai-" + "knowledge",
    "Polish" + "-native", r"\.NET", "lang" + "fuse",
]
SCANNED = [ROOT / "README.md", ROOT / "pyproject.toml", *sorted((ROOT / "english_coach").rglob("*.py"))]


def test_no_personal_or_internal_strings():
    hits = []
    for path in SCANNED:
        text = path.read_text(encoding="utf-8")
        for pat in FORBIDDEN:
            for m in re.finditer(pat, text, flags=re.IGNORECASE):
                hits.append(f"{path.relative_to(ROOT)}: {m.group(0)!r}")
    assert not hits, "\n".join(hits)
```
Also run once, manually: `git grep -n -i "dycjan\|marta"` → must print nothing outside `docs/superpowers/`.

- [ ] **Step 2: Write `README.md`** with these sections, in this order (fill in real prose; no placeholders except `<owner>`):
  1. **English Coach** — one paragraph: turns the prompts you type into Claude Code into a daily English-coaching vault in Obsidian (wins, one focus pattern, before→after fixes, phrases to practice, dashboard).
  2. **Screenshot** — `docs/dashboard.png` (the user supplies it before publishing; leave the image link in).
  3. **Requirements** — Claude Code (logged in), `uv`, Obsidian. Python is installed by uv.
  4. **Quick start** — 
     ```
     uv tool install git+https://github.com/<owner>/english-coach
     english-coach init
     ```
     then "Open the vault folder in Obsidian; trust the Dataview plugin when asked."
  5. **How it works** — reads `~/.claude/projects/**/*.jsonl` (only prompts you typed; tool output, subagents and the coach's own calls are skipped); once a day analyzes completed days since the last run; catches up after the machine was off; one Claude call per run plus small enrichment/curation calls.
  6. **Privacy** — transcripts are read locally; the day's prompts are sent to Claude (via your Claude Code login or your API key) for analysis; nothing else leaves the machine.
  7. **Cost** — CLI backend uses your Claude subscription usage; API backend uses API credits; set `model` in config to a cheaper model to reduce cost.
  8. **Commands** — table of `init`, `run` (flags `--backfill-days`, `--from/--to`, `--include-today`), `enrich`, `doctor [--ping]`, `schedule [--time]`, `unschedule`.
  9. **Configuration** — config file locations per OS and the `config.toml` example from the spec; `ANTHROPIC_API_KEY`; `ENGLISH_COACH_CONFIG_DIR`; `ENGLISH_COACH_CLAUDE`.
  10. **Scheduling details** — the per-OS table from the spec.
  11. **Limits** — Claude Code deletes transcripts older than `cleanupPeriodDays` (default 30), so backfill cannot go further back; the transcript format is not a public API — `doctor` warns if parsing starts failing.
  12. **Troubleshooting** — run `english-coach doctor`; log location.
  13. **Uninstall** — `english-coach unschedule`, `uv tool uninstall english-coach`, delete the config folder; the vault is yours to keep.
  14. **License** — MIT; bundles Obsidian Dataview (MIT, © Michael Brenan) in `english_coach/assets/obsidian/plugins/dataview/`.

  Add `readme = "README.md"` to `[project]` in `pyproject.toml`.

- [ ] **Step 3: Write `.github/workflows/ci.yml`**

```yaml
name: CI
on:
  push:
  pull_request:
jobs:
  test:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
        python: ["3.11", "3.13"]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          python-version: ${{ matrix.python }}
      - run: uv sync
      - run: uv run pytest -q
      - name: Real Task Scheduler round-trip
        if: runner.os == 'Windows'
        env:
          EC_SCHEDULER_IT: "1"
        run: uv run pytest tests/test_scheduler.py -m integration -q
```

- [ ] **Step 4: Run** — `uv run pytest -q` → all PASS (the guard test included).

- [ ] **Step 5: End-to-end install check from the built wheel**

```bash
uv build
uv tool install --force dist/english_coach-0.1.0-py3-none-any.whl
english-coach --help
english-coach doctor || true
uv tool uninstall english-coach
```
Expected: help lists `init run enrich doctor schedule unschedule`; doctor runs. Report the output.

- [ ] **Step 6: Commit** — `git add -A && git commit -m "docs: README, CI matrix, personal-data guard" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"`

- [ ] **Step 7: Create the clean `release` branch (no plans/specs, single commit)**

```bash
git checkout --orphan release
git rm -r --cached docs/superpowers
rm -rf docs/superpowers
git commit -m "Initial public release of English Coach

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
git log --oneline release
git checkout master   # or the repo's default branch; docs/superpowers returns here
```
Expected: `release` has exactly one commit and no `docs/superpowers`. **Do not push.** Pushing to GitHub is outward-facing: stop and hand over to the user with the commands (`gh repo create <owner>/english-coach --public --source . --push` from the `release` branch, or `git remote add origin … && git push -u origin release:main`).
