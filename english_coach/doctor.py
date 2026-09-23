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
