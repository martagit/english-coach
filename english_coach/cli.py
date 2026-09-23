from __future__ import annotations

import argparse
import os
import sys
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

from english_coach import coach, scheduler, vault
from english_coach.analyzer import (
    ClaudeAnalyzer, ClaudeCliAnalyzer, enrich_patterns, enrich_phrases, run_claude_cli,
)
from english_coach.config import AppPaths, Config, ConfigError, load_config, save_config
from english_coach.curator import curate
from english_coach.lock import AlreadyRunning, run_lock
from english_coach.runlog import read_last_run, run_log, write_last_run
from english_coach.transcripts import TranscriptSource, default_projects_dir
from english_coach.validation import normalize_time, validate_timezone


def _parse_date(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


def make_runner(config: Config, paths: AppPaths):
    paths.workdir.mkdir(parents=True, exist_ok=True)
    return lambda prompt: run_claude_cli(prompt, model=config.model, cwd=paths.workdir)


def execute_run(config: Config, paths: AppPaths, env: dict, *, backfill_days: int = 1,
                override_from: date | None = None, override_to: date | None = None,
                include_today: bool = False, now_utc: datetime | None = None,
                analyzer=None, source=None, runner=None) -> tuple[int, str]:
    prof = config.profile
    with run_log(paths.log_file):
        try:
            runner = runner or make_runner(config, paths)
            if analyzer is None:
                analyzer = (ClaudeAnalyzer(config) if config.backend == "api"
                            else ClaudeCliAnalyzer(config, runner=runner))
            source = source or TranscriptSource(default_projects_dir(env), exclude_cwd=paths.workdir)
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
        stats = getattr(source, "last_stats", None)
        if status == "empty":
            # Nothing was fetched: keep the last real read's stats so doctor's
            # format-change signal survives quiet runs.
            prev = read_last_run(paths.last_run_file)
            stats = prev.get("stats") if isinstance(prev, dict) else None
        write_last_run(paths.last_run_file, status, stats)
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
    try:
        config = _load(paths, env, args)
    except ConfigError as exc:
        # A scheduled run has no terminal: record the failure where doctor points.
        with run_log(paths.log_file):
            print(f"Config error: {exc}", file=sys.stderr)
        return 1
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


def _valid_time(s: str) -> str:
    try:
        return normalize_time(s)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _valid_timezone(s: str) -> str:
    try:
        return validate_timezone(s)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def cmd_schedule(args, paths: AppPaths, env: dict) -> int:
    config = load_config(paths, env)
    if args.time:
        config = replace(config, schedule_time=args.time)
        save_config(paths, config)
    try:
        print(scheduler.install(config.schedule_time, paths.log_file.parent, env=env))
        return 0
    except scheduler.SchedulerUnavailable as exc:
        print(str(exc))
        return 1
    except RuntimeError as exc:
        print(f"Scheduling failed: {exc}", file=sys.stderr)
        return 1


def cmd_unschedule(args, paths: AppPaths, env: dict) -> int:
    try:
        scheduler.remove()
    except scheduler.SchedulerUnavailable as exc:
        print(str(exc))
        return 1
    current = scheduler.status()
    if current.installed:
        print(f"Failed to remove the daily job: {current.detail}", file=sys.stderr)
        return 1
    print("Removed the daily english-coach job.")
    return 0


def cmd_init(args, paths: AppPaths, env: dict) -> int:
    from english_coach.init_wizard import Prompter, init
    answers = {
        "vault": args.vault, "native_language": args.native_language, "context": args.context,
        "timezone": args.timezone, "backend": args.backend,
        "backfill_days": args.backfill_days, "time": args.time,
        "schedule": False if args.no_schedule else None,
    }
    try:
        return init(paths, env, Prompter(answers, assume_yes=args.yes))
    except (KeyboardInterrupt, EOFError):
        print("\nSetup cancelled. Re-run `english-coach init` to continue.", file=sys.stderr)
        return 130


def cmd_doctor(args, paths: AppPaths, env: dict) -> int:
    from english_coach.doctor import format_checks, run_checks
    checks = run_checks(paths, env, ping=args.ping)
    print(format_checks(checks))
    return 0 if all(c.ok for c in checks) else 1


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
    run.add_argument("--config-dir", default=None,
                     help="Use this config directory (overrides ENGLISH_COACH_CONFIG_DIR).")
    run.add_argument("--claude-config-dir", default=None,
                     help="Claude Code config directory to read transcripts from "
                          "(overrides CLAUDE_CONFIG_DIR).")
    run.set_defaults(func=cmd_run)

    enrich = sub.add_parser("enrich", help="Add definitions/examples/rules to bare notes.")
    enrich.add_argument("--vault", default=None)
    enrich.add_argument("--phrases", action="store_true")
    enrich.add_argument("--patterns", action="store_true")
    enrich.add_argument("--force", action="store_true", help="Regenerate ALL notes.")
    enrich.set_defaults(func=cmd_enrich)

    sch = sub.add_parser("schedule", help="Register (or update) the daily OS job.")
    sch.add_argument("--time", type=_valid_time, default=None, help="HH:MM, local time.")
    sch.set_defaults(func=cmd_schedule)
    unsch = sub.add_parser("unschedule", help="Remove the daily OS job.")
    unsch.set_defaults(func=cmd_unschedule)
    doc = sub.add_parser("doctor", help="Check that everything is set up.")
    doc.add_argument("--ping", action="store_true", help="Also make a tiny test call to Claude.")
    doc.set_defaults(func=cmd_doctor)

    ini = sub.add_parser("init", help="Set up config, vault, first run and daily schedule.")
    ini.add_argument("--yes", action="store_true", help="Accept defaults without prompting.")
    ini.add_argument("--vault", default=None)
    ini.add_argument("--native-language", default=None)
    ini.add_argument("--context", default=None)
    ini.add_argument("--timezone", type=_valid_timezone, default=None)
    ini.add_argument("--backend", choices=["cli", "api"], default=None)
    ini.add_argument("--backfill-days", type=int, default=None)
    ini.add_argument("--time", type=_valid_time, default=None)
    ini.add_argument("--no-schedule", action="store_true")
    ini.set_defaults(func=cmd_init)
    return parser


def main(argv: list[str] | None = None, env: dict | None = None) -> int:
    env = dict(os.environ) if env is None else env
    args = build_parser().parse_args(argv)
    # `run --config-dir/--claude-config-dir` let the OS scheduler, which doesn't
    # see the user's shell environment, reproduce the setup `schedule` saw.
    if getattr(args, "claude_config_dir", None):
        env = {**env, "CLAUDE_CONFIG_DIR": str(Path(args.claude_config_dir).expanduser().resolve())}
    if getattr(args, "config_dir", None):
        paths = AppPaths(Path(args.config_dir).expanduser().resolve())
    else:
        paths = AppPaths.default(env)
    try:
        return args.func(args, paths, env)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 1
