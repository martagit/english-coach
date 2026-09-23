from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from english_coach.coach_prompts import COACH_PROMPT_PREFIXES
from english_coach.models import UserPrompt

# Lines Claude Code writes as "user" but that the human did not type, plus the
# coach's own `claude -p` prompts (second line of defence after the cwd check).
_SKIP_PREFIXES = ("<command-", "<local-command-", "<system-reminder>") + COACH_PROMPT_PREFIXES
# Content blocks a human can legitimately send without any text (e.g. a pasted screenshot).
_NON_TEXT_BLOCKS = ("image", "document")


@dataclass
class ReadStats:
    files_scanned: int = 0
    lines_read: int = 0
    malformed: int = 0
    prompts: int = 0
    # "user" entries rejected only because message/content/timestamp was missing or
    # had an unexpected shape - a sign Claude Code's transcript format changed.
    unrecognized: int = 0

    def summary(self) -> str:
        return (f"Transcripts: {self.files_scanned} files, {self.lines_read} lines, "
                f"{self.prompts} prompts, {self.malformed} malformed, "
                f"{self.unrecognized} unrecognized.")


def default_projects_dir(env: dict | None = None) -> Path:
    env = os.environ if env is None else env
    base = env.get("CLAUDE_CONFIG_DIR")
    return (Path(base) if base else Path.home() / ".claude") / "projects"


def _text_of(content) -> str | None:
    """The typed text ("" when there is legitimately none, e.g. a tool result),
    or None when `content` has a shape we don't recognize."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None
    if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
        return ""
    texts = [b.get("text") for b in content if isinstance(b, dict) and b.get("type") == "text"]
    if texts:
        if not all(isinstance(t, str) for t in texts):
            return None
        return "\n".join(t for t in texts if t)
    if all(isinstance(b, dict) and b.get("type") in _NON_TEXT_BLOCKS for b in content):
        return ""  # includes an empty list
    return None


def _parse_ts(raw) -> datetime | None:
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (AttributeError, ValueError):
        return None


def _same_dir(a, b) -> bool:
    # realpath (not resolve()) never raises for missing paths, makes a relative
    # exclude_cwd match Claude Code's absolute cwd, and sees through symlinks/junctions.
    return (os.path.normcase(os.path.realpath(str(a)))
            == os.path.normcase(os.path.realpath(str(b))))


def _parse_entry(entry: dict, exclude_cwd: Path | None = None) -> tuple[UserPrompt | None, bool]:
    """Return (prompt, unrecognized). `unrecognized` is True only for a "user"
    entry that is not a legitimate skip but whose shape we couldn't read."""
    if entry.get("type") != "user":
        return None, False
    if entry.get("isSidechain") or entry.get("isMeta") or entry.get("isCompactSummary"):
        return None, False
    cwd = entry.get("cwd")
    if exclude_cwd is not None and cwd and _same_dir(cwd, exclude_cwd):
        return None, False
    msg = entry.get("message")
    if not isinstance(msg, dict):
        return None, True
    text = _text_of(msg.get("content"))
    if text is None:
        return None, True
    if not text.strip() or text.lstrip().startswith(_SKIP_PREFIXES):
        return None, False
    ts = _parse_ts(entry.get("timestamp"))
    if ts is None:
        return None, True
    return UserPrompt(text=text, timestamp_utc=ts), False


def prompt_from_entry(entry: dict, exclude_cwd: Path | None = None) -> UserPrompt | None:
    return _parse_entry(entry, exclude_cwd)[0]


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
        try:
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
                    prompt, unrecognized = _parse_entry(entry, exclude_cwd)
                    if unrecognized:
                        stats.unrecognized += 1
                    if prompt is None or not (start_utc <= prompt.timestamp_utc <= end_utc):
                        continue
                    key = entry.get("uuid") or (entry.get("sessionId"), entry.get("timestamp"), prompt.text)
                    if key in seen:
                        continue  # resumed/forked sessions replay history
                    seen.add(key)
                    out.append(prompt)
        except OSError:
            stats.malformed += 1  # e.g. file deleted, locked, or permission denied
            continue
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
