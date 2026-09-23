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
                    prompt = prompt_from_entry(entry, exclude_cwd)
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
