from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone, date
from pathlib import Path

from english_coach.config import Config, load_config
from english_coach.langfuse_client import LangfuseClient
from english_coach.analyzer import ClaudeAnalyzer, ClaudeCliAnalyzer, enrich_phrases, enrich_patterns
from english_coach.filtering import extract_user_prompts, filter_prompts
from english_coach.window import compute_window, note_basename
from english_coach.state import read_watermark, write_watermark
from english_coach import vault

_DEFAULT_VAULT = Path(r"C:\Users\marta.dycjan\english-review")
_DEFAULT_MCP = Path(r"C:\Dev\mpt-library-framework\utility\ai-knowledge\.mcp.json")


def run(config: Config, langfuse, analyzer, now_utc: datetime,
        backfill_days: int = 1, override_from: date | None = None,
        override_to: date | None = None, enricher=None, pattern_enricher=None,
        include_today: bool = False, curator=None) -> str:
    if not langfuse.is_reachable():
        print("Langfuse not reachable — skipping this run.")
        return "down"

    is_override = override_from is not None and override_to is not None
    # Today (and explicit range reprocessing) are partial/manual → don't advance
    # the watermark, so the next scheduled run still does the authoritative pass.
    no_advance = is_override or include_today

    today_local_date = now_utc.astimezone(_zone(config)).date()
    vault.seed_vault(config.vault_path, introduced=today_local_date)

    watermark = read_watermark(config.vault_path)
    window = compute_window(now_utc, watermark, config.timezone, backfill_days,
                            override_from, override_to, include_today)
    if window.is_empty:
        print("Nothing new to process.")
        return "empty"

    traces = langfuse.fetch_traces(window.start_utc, window.end_utc)
    prompts = filter_prompts(extract_user_prompts(traces))
    label = note_basename(window.days)

    if not prompts:
        vault.write_quiet_note(config.vault_path, window)
        vault.recompute_reuse(config.vault_path, config.adopted_threshold)
        _run_curator(curator)
        vault.write_dashboard(config.vault_path)
        if not no_advance:
            write_watermark(config.vault_path, window.end_utc)
        print(f"Quiet day ({label}).")
        return "quiet"

    phrasebook = vault.read_phrasebook(config.vault_path)
    analysis = analyzer.analyze(prompts, phrasebook)
    vault.write_daily_note(config.vault_path, window, len(prompts), analysis)
    vault.apply_analysis_notes(config.vault_path, analysis, introduced=window.days[-1], day_label=label)
    vault.recompute_reuse(config.vault_path, config.adopted_threshold)
    _run_curator(curator)
    vault.write_dashboard(config.vault_path)
    if enricher is not None:
        # Give any newly-created (and still bare) phrase notes a definition + examples.
        enriched = vault.enrich_phrase_notes(config.vault_path, enricher)
        if enriched:
            print(f"Enriched {enriched} new phrase note(s).")
    if pattern_enricher is not None:
        pe = vault.enrich_pattern_notes(config.vault_path, pattern_enricher)
        if pe:
            print(f"Enriched {pe} new pattern note(s).")
    if not no_advance:
        write_watermark(config.vault_path, window.end_utc)
    print(f"Wrote report for {label} ({len(prompts)} prompts).")
    return f"wrote:{label}"


def _run_curator(curator) -> None:
    """Fail-soft: curation must never break the daily run."""
    if curator is None:
        return
    try:
        changed = curator()
        if changed:
            print(f"Curated {changed} phrase note(s).")
    except Exception as exc:
        print(f"Curator failed (skipped): {exc}", file=sys.stderr)


def _zone(config: Config):
    from zoneinfo import ZoneInfo
    return ZoneInfo(config.timezone)


def _parse_date(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Daily English-coaching vault builder.")
    parser.add_argument("--vault", type=Path, default=_DEFAULT_VAULT)
    parser.add_argument("--mcp-json", type=Path, default=_DEFAULT_MCP)
    parser.add_argument("--backfill-days", type=int, default=1)
    parser.add_argument("--from", dest="from_date", default=None)
    parser.add_argument("--to", dest="to_date", default=None)
    parser.add_argument("--include-today", action="store_true",
                        help="Also process today's prompts so far (partial day). Does not advance "
                             "the watermark, so the next scheduled run still does today fully.")
    parser.add_argument("--backend", choices=["cli", "api"], default="cli",
                        help="LLM backend: 'cli' uses the local Claude Code (claude -p, no API key); "
                             "'api' uses the Anthropic API (needs ANTHROPIC_API_KEY).")
    parser.add_argument("--enrich-phrases", action="store_true",
                        help="(Re)generate Definition + sample-usage for phrase notes, then exit.")
    parser.add_argument("--enrich-patterns", action="store_true",
                        help="(Re)generate the Rule + study-card examples for pattern notes, then exit.")
    parser.add_argument("--force", action="store_true",
                        help="With --enrich-*: regenerate ALL notes, not just bare/un-enriched ones.")
    args = parser.parse_args(argv)

    if bool(args.from_date) != bool(args.to_date):
        print("Error: --from and --to must be given together.", file=sys.stderr)
        return 1

    import os
    try:
        config = load_config(vault_path=args.vault, mcp_json_path=args.mcp_json, env=dict(os.environ))
    except RuntimeError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 1

    from english_coach.curator import curate
    curator = lambda: curate(config.vault_path, max_active=config.max_active)
    enricher = lambda items: enrich_phrases(items)
    pattern_enricher = lambda items: enrich_patterns(items)

    if args.enrich_phrases or args.enrich_patterns:
        try:
            total = 0
            if args.enrich_phrases:
                n = vault.enrich_phrase_notes(config.vault_path, enricher, force=args.force)
                print(f"Enriched {n} phrase note(s).")
                total += n
            if args.enrich_patterns:
                n = vault.enrich_pattern_notes(config.vault_path, pattern_enricher, force=args.force)
                print(f"Enriched {n} pattern note(s).")
                total += n
            return 0
        except Exception as exc:
            print(f"Enrich failed: {exc}", file=sys.stderr)
            return 1

    langfuse = LangfuseClient(config)
    analyzer = ClaudeAnalyzer(config) if args.backend == "api" else ClaudeCliAnalyzer(config)
    try:
        run(config, langfuse, analyzer, now_utc=datetime.now(timezone.utc),
            backfill_days=args.backfill_days,
            override_from=_parse_date(args.from_date),
            override_to=_parse_date(args.to_date),
            enricher=enricher, pattern_enricher=pattern_enricher,
            include_today=args.include_today, curator=curator)
        return 0
    except Exception as exc:  # graceful: never crash the scheduled task noisily
        print(f"Run failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
