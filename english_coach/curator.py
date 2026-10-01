from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable
from datetime import date as _date
from pathlib import Path

from english_coach.analyzer import run_claude_cli, extract_json_object
from english_coach.coach_prompts import CONSTRUCTION_CURATOR_PREAMBLE, CURATOR_PREAMBLE
from english_coach.profile import Profile
from english_coach.vault import construction_key


@dataclass(frozen=True)
class CurationKind:
    folder: str
    name_key: str
    preamble: str
    noun: str
    theme_examples: str
    show_missed: bool = False
    match_key: Callable[[str], str] = str.strip  # how a curator decision's name finds its note


PHRASES = CurationKind("Phrases", "phrase", CURATOR_PREAMBLE, "phrases",
                       "'hedging', 'review feedback', 'asking for changes'")
CONSTRUCTIONS = CurationKind("Constructions", "construction", CONSTRUCTION_CURATOR_PREAMBLE,
                             "grammar constructions",
                             "'suggesting', 'expectations', 'hypotheticals', 'linking ideas'",
                             show_missed=True, match_key=construction_key)


def curator_system(profile: Profile, kind: CurationKind = PHRASES) -> str:
    return (
        f"{kind.preamble} for {profile.learner()}. "
        f"The learner can only actively practice a small set of {kind.noun} at a time. Decide which "
        f"{kind.noun} are 'active' (currently practicing) vs 'backlog' (parked for later), give each "
        "a priority (1 = practice first .. 5 = someday), and a short theme label that groups "
        f"related {kind.noun} (e.g. {kind.theme_examples})."
    )


def build_curation_prompt(inventory: list[dict], max_active: int,
                          profile: Profile = Profile(), kind: CurationKind = PHRASES) -> str:
    lines = []
    for it in inventory:
        missed = f" | missed_count: {it.get('missed_count', 0)}" if kind.show_missed else ""
        lines.append(
            f"- {it['phrase']} | status: {it['status']} | priority: {it.get('priority') or '-'}"
            f" | theme: {it.get('theme') or '-'} | reuse_count: {it['reuse_count']}{missed}"
            f" | introduced: {it.get('introduced') or '-'} | last_used: {it.get('last_used') or '-'}"
        )
    listing = "\n".join(lines)
    missed_rule = ("- Prefer activating items with a high missed_count: the learner keeps meeting "
                   "situations that need them.\n" if kind.show_missed else "")
    return (
        f"{curator_system(profile, kind)}\n\n"
        "Rules:\n"
        f"- At most {max_active} {kind.noun} may be 'active'.\n"
        "- Keep current assignments stable: change an item's status/priority/theme only when "
        "you have a concrete reason (near-duplicate of another item, stale and never reused, "
        "or a clearly higher-value newcomer deserving the slot).\n"
        "- Every item gets a priority 1-5 (1 = practice first) and a short theme (2-3 words).\n"
        "- Give related items the SAME theme label so they group together.\n"
        f"{missed_rule}\n"
        f"The current list (metadata shown):\n{listing}\n\n"
        "Output ONLY a single JSON object of exactly this shape — no prose, no markdown fences:\n"
        '{"phrases":[{"phrase":"<verbatim>","status":"active|backlog","priority":1,"theme":"..."}]}\n'
        "Include EVERY item listed, copied verbatim so it can be matched back."
    )


def parse_curation(payload: dict) -> list[dict]:
    """Validate curator output; malformed entries are dropped individually."""
    out: list[dict] = []
    for p in payload.get("phrases", []):
        phrase, status = p.get("phrase"), p.get("status")
        priority, theme = p.get("priority"), p.get("theme")
        if not phrase or status not in ("active", "backlog"):
            continue
        if not isinstance(priority, int) or isinstance(priority, bool) or not 1 <= priority <= 5:
            continue
        if not isinstance(theme, str) or not theme.strip():
            continue
        out.append({"phrase": phrase, "status": status, "priority": priority,
                    "theme": theme.strip()})
    return out


def _as_ordinal(v) -> int:
    if isinstance(v, _date):
        return v.toordinal()
    try:
        return _date.fromisoformat(str(v)).toordinal()
    except (TypeError, ValueError):
        return 0


def apply_guardrails(inventory: list[dict], decisions: list[dict],
                     max_active: int, key: Callable[[str], str] = str.strip) -> dict[str, dict]:
    """Match decisions to the inventory and enforce the active-set cap.

    Unknown phrases are ignored; phrases missing from the decisions are simply
    absent (their notes keep current values). If more than max_active are marked
    active, the excess (worst priority, then least recently used/introduced)
    are demoted to backlog. Returns note_name -> {status, priority, theme}."""
    by_phrase = {key(it["phrase"]): it for it in inventory}
    updates: dict[str, dict] = {}
    for d in decisions:
        it = by_phrase.get(key(d["phrase"]))
        if it is None:
            continue
        updates[it["note_name"]] = {"status": d["status"], "priority": d["priority"],
                                    "theme": d["theme"]}
    untouched_active = sum(1 for it in inventory
                           if it["status"] == "active" and it["note_name"] not in updates)
    budget = max(0, max_active - untouched_active)
    active = [(name, upd) for name, upd in updates.items() if upd["status"] == "active"]
    if len(active) > budget:
        info = {it["note_name"]: it for it in inventory}
        active.sort(key=lambda nu: (nu[1]["priority"],
                                    -_as_ordinal(info[nu[0]].get("last_used")),
                                    -_as_ordinal(info[nu[0]].get("introduced"))))
        for _, upd in active[budget:]:
            upd["status"] = "backlog"
    return updates


def curate(vault: Path, runner=None, max_active: int = 12,
          profile: Profile = Profile(), kind: CurationKind = PHRASES) -> int:
    """One full curation pass over the non-adopted notes of `kind`.

    Raises on LLM/parse failure — the caller decides fail-soft behavior.
    Returns the number of notes whose frontmatter changed."""
    from english_coach import vault as vault_mod

    inventory = vault_mod.read_curation_inventory(vault, folder=kind.folder, name_key=kind.name_key)
    if not inventory:
        return 0
    runner = runner or (lambda p: run_claude_cli(p))
    prompt = build_curation_prompt(inventory, max_active, profile, kind)
    text = runner(prompt)
    try:
        payload = extract_json_object(text)
    except (ValueError, json.JSONDecodeError):
        text = runner(prompt + "\n\nReturn ONLY the JSON object. No other text.")
        payload = extract_json_object(text)
    decisions = parse_curation(payload)
    updates = apply_guardrails(inventory, decisions, max_active, kind.match_key)
    return vault_mod.apply_curation(vault, updates, folder=kind.folder)
