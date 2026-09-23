from __future__ import annotations

import sys
from datetime import datetime, date

from english_coach.config import Config
from english_coach.filtering import filter_prompts
from english_coach.window import compute_window, note_basename
from english_coach.state import read_watermark, write_watermark
from english_coach import vault


def run(config: Config, source, analyzer, now_utc: datetime,
        backfill_days: int = 1, override_from: date | None = None,
        override_to: date | None = None, enricher=None, pattern_enricher=None,
        include_today: bool = False, curator=None) -> str:
    is_override = override_from is not None and override_to is not None
    # Today (and explicit range reprocessing) are partial/manual → don't advance
    # the watermark, so the next scheduled run still does the authoritative pass.
    no_advance = is_override or include_today

    watermark = read_watermark(config.vault_path)
    window = compute_window(now_utc, watermark, config.timezone, backfill_days,
                            override_from, override_to, include_today)
    if window.is_empty:
        print("Nothing new to process.")
        return "empty"

    prompts = filter_prompts(source.fetch_prompts(window.start_utc, window.end_utc))
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
    known_patterns = vault.read_known_patterns(config.vault_path)
    analysis = analyzer.analyze(prompts, phrasebook, known_patterns)
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
