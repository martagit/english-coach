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

    sch = sub.add_parser("schedule", help="Register (or update) the daily OS job.")
    sch.add_argument("--time", type=_valid_time, default=None, help="HH:MM, local time.")
    sch.set_defaults(func=cmd_schedule)
    unsch = sub.add_parser("unschedule", help="Remove the daily OS job.")
    unsch.set_defaults(func=cmd_unschedule)
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
