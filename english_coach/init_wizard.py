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
