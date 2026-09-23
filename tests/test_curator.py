import json
from datetime import date
from english_coach.curator import (
    build_curation_prompt, parse_curation, apply_guardrails, curate,
)
from english_coach.vault import ensure_phrase_note
from english_coach.frontmatter import read_note


def _inv(phrase, status="backlog", priority=None, theme=None, reuse=0,
         introduced=date(2026, 7, 1), last_used=None):
    return {"note_name": phrase, "phrase": phrase, "status": status,
            "priority": priority, "theme": theme, "reuse_count": reuse,
            "introduced": introduced, "last_used": last_used}


def test_build_prompt_lists_inventory_and_rules():
    p = build_curation_prompt([_inv("park it", status="active", priority=1, theme="hedging")],
                              max_active=12)
    assert "park it" in p
    assert "hedging" in p
    assert "At most 12" in p
    assert "stable" in p  # stability instruction present


def test_parse_curation_drops_invalid_entries_individually():
    payload = {"phrases": [
        {"phrase": "good", "status": "active", "priority": 1, "theme": "hedging"},
        {"phrase": "bad status", "status": "adopted", "priority": 1, "theme": "x"},
        {"phrase": "bad priority", "status": "active", "priority": 9, "theme": "x"},
        {"phrase": "bad bool priority", "status": "active", "priority": True, "theme": "x"},
        {"phrase": "bad theme", "status": "active", "priority": 1, "theme": ""},
        {"status": "active", "priority": 1, "theme": "no phrase"},
    ]}
    out = parse_curation(payload)
    assert [d["phrase"] for d in out] == ["good"]


def test_guardrails_ignore_unknown_and_keep_missing():
    inv = [_inv("known")]
    decisions = [
        {"phrase": "known", "status": "active", "priority": 1, "theme": "hedging"},
        {"phrase": "hallucinated", "status": "active", "priority": 1, "theme": "x"},
    ]
    updates = apply_guardrails(inv, decisions, max_active=12)
    assert set(updates) == {"known"}  # unknown dropped; missing phrases just absent


def test_guardrails_trim_over_assigned_active_set():
    inv = [
        _inv("p1", last_used=date(2026, 7, 5)),
        _inv("p2", last_used=date(2026, 7, 4)),
        _inv("p3", last_used=None),
    ]
    decisions = [
        {"phrase": "p1", "status": "active", "priority": 2, "theme": "t"},
        {"phrase": "p2", "status": "active", "priority": 1, "theme": "t"},
        {"phrase": "p3", "status": "active", "priority": 1, "theme": "t"},
    ]
    updates = apply_guardrails(inv, decisions, max_active=2)
    active = [n for n, u in updates.items() if u["status"] == "active"]
    # keep by priority asc (p2, p3 tie at 1), then most recent last_used (p2 wins tie);
    # p3 (no last_used) beats p1 only if priority is lower — it is (1 < 2).
    assert sorted(active) == ["p2", "p3"]
    assert updates["p1"]["status"] == "backlog"  # demoted by the cap, not dropped


def test_guardrails_trim_tiebreak_prefers_recent_last_used():
    """Verify that when all candidates have same priority, most recent last_used is kept."""
    inv = [
        _inv("old", last_used=date(2026, 7, 1)),
        _inv("mid", last_used=date(2026, 7, 3)),
        _inv("new", last_used=date(2026, 7, 5)),
    ]
    decisions = [{"phrase": p, "status": "active", "priority": 1, "theme": "t"}
                 for p in ("old", "mid", "new")]
    updates = apply_guardrails(inv, decisions, max_active=2)
    assert updates["old"]["status"] == "backlog"   # least recently used loses the slot
    assert updates["mid"]["status"] == "active"
    assert updates["new"]["status"] == "active"


def test_guardrails_trim_tiebreak_none_last_used_demoted():
    """Verify that None last_used (never used) is demoted first when all have same priority and introduced."""
    inv = [
        _inv("no_use", introduced=date(2026, 7, 1), last_used=None),
        _inv("used_p1", introduced=date(2026, 7, 1), last_used=date(2026, 7, 3)),
        _inv("used_p2", introduced=date(2026, 7, 1), last_used=date(2026, 7, 5)),
    ]
    decisions = [{"phrase": p, "status": "active", "priority": 1, "theme": "t"}
                 for p in ("no_use", "used_p1", "used_p2")]
    updates = apply_guardrails(inv, decisions, max_active=2)
    assert updates["no_use"]["status"] == "backlog"  # None last_used sorts as least recent
    assert updates["used_p1"]["status"] == "active"
    assert updates["used_p2"]["status"] == "active"


def test_guardrails_count_untouched_active_against_cap():
    """A phrase already active but absent from the LLM's decisions keeps its status
    (missing phrases are left alone) but must still count against max_active, shrinking
    the budget available to newly-named actives."""
    inv = [
        _inv("kept", status="active", priority=1, last_used=date(2026, 7, 5)),
        _inv("p1", last_used=date(2026, 7, 4)),
        _inv("p2", last_used=date(2026, 7, 1)),
    ]
    decisions = [
        {"phrase": "p1", "status": "active", "priority": 1, "theme": "t"},
        {"phrase": "p2", "status": "active", "priority": 1, "theme": "t"},
    ]
    updates = apply_guardrails(inv, decisions, max_active=2)
    assert "kept" not in updates  # untouched active phrase is never rewritten
    active = [n for n, u in updates.items() if u["status"] == "active"]
    assert active == ["p1"]  # only one slot left after "kept" consumes the other
    assert updates["p2"]["status"] == "backlog"


def test_guardrails_trim_tiebreak_prefers_recently_introduced():
    """Verify that when priority and last_used are tied, the most recently introduced
    candidate keeps the slot and the oldest-introduced one is demoted."""
    inv = [
        _inv("oldest", introduced=date(2026, 6, 1), last_used=None),
        _inv("mid", introduced=date(2026, 6, 15), last_used=None),
        _inv("newest", introduced=date(2026, 7, 1), last_used=None),
    ]
    decisions = [{"phrase": p, "status": "active", "priority": 1, "theme": "t"}
                 for p in ("oldest", "mid", "newest")]
    updates = apply_guardrails(inv, decisions, max_active=2)
    assert updates["oldest"]["status"] == "backlog"  # oldest introduced loses the slot
    assert updates["mid"]["status"] == "active"
    assert updates["newest"]["status"] == "active"


def test_curate_end_to_end_with_fake_runner(tmp_path):
    ensure_phrase_note(tmp_path, "park it", introduced=date(2026, 7, 1))
    ensure_phrase_note(tmp_path, "hoist", introduced=date(2026, 7, 2))
    reply = json.dumps({"phrases": [
        {"phrase": "park it", "status": "active", "priority": 1, "theme": "hedging"},
        {"phrase": "hoist", "status": "backlog", "priority": 3, "theme": "refactoring verbs"},
    ]})
    prompts = []

    def runner(prompt):
        prompts.append(prompt)
        return reply

    changed = curate(tmp_path, runner=runner, max_active=12)
    assert changed == 2
    assert "park it" in prompts[0] and "hoist" in prompts[0]
    fm, _ = read_note(tmp_path / "Phrases" / "park it.md")
    assert fm["status"] == "active" and fm["priority"] == 1 and fm["theme"] == "hedging"
    fm, _ = read_note(tmp_path / "Phrases" / "hoist.md")
    assert fm["status"] == "backlog" and fm["theme"] == "refactoring verbs"


def test_curate_empty_vault_makes_no_llm_call(tmp_path):
    called = []
    assert curate(tmp_path, runner=lambda p: called.append(p) or "{}") == 0
    assert called == []


def test_curate_retries_once_on_unparseable_output(tmp_path):
    ensure_phrase_note(tmp_path, "park it", introduced=date(2026, 7, 1))
    reply = json.dumps({"phrases": [
        {"phrase": "park it", "status": "active", "priority": 1, "theme": "hedging"}]})
    outputs = iter(["sorry, no JSON", reply])
    changed = curate(tmp_path, runner=lambda p: next(outputs), max_active=12)
    assert changed == 1
