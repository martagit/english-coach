from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

from english_coach.coach_prompts import (  # noqa: F401  (COACH_PROMPT_PREFIXES re-exported)
    ANALYSIS_PREAMBLE, COACH_PROMPT_PREFIXES, CONSTRUCTION_ENRICH_PREAMBLE, ENRICH_PREAMBLE,
    PATTERN_PREAMBLE,
)
from english_coach.config import Config
from english_coach.models import (
    Analysis, Win, BeforeAfter, FocusPattern, Recurring, NewPhrase, UserPrompt, PhraseInfo,
    ConstructionInfo, MissedConstruction, NewConstruction,
)
from english_coach.vault import construction_key
from english_coach.profile import Profile

_BA = {"type": "object", "properties": {"before": {"type": "string"}, "after": {"type": "string"}},
       "required": ["before", "after"]}

ANALYSIS_TOOL = {
    "name": "report_analysis",
    "description": "Return the structured English-coaching analysis for the day's prompts.",
    "input_schema": {
        "type": "object",
        "properties": {
            "wins": {"type": "array", "items": {"type": "object", "properties": {
                "phrase": {"type": "string"}, "quote": {"type": "string"}},
                "required": ["phrase", "quote"]}},
            "focus_pattern": {"type": ["object", "null"], "properties": {
                "pattern": {"type": "string"}, "explanation": {"type": "string"},
                "examples": {"type": "array", "items": _BA}},
                "required": ["pattern", "explanation", "examples"]},
            "recurring": {"type": "array", "items": {"type": "object", "properties": {
                "pattern": {"type": "string"}, "before": {"type": "string"}, "after": {"type": "string"}},
                "required": ["pattern", "before", "after"]}},
            "new_phrases": {"type": "array", "items": {"type": "object", "properties": {
                "phrase": {"type": "string"}, "meaning": {"type": "string"}, "example": {"type": "string"}},
                "required": ["phrase", "meaning", "example"]}},
            "reused_phrases": {"type": "array", "items": {"type": "string"}},
            "snapshot": {"type": "array", "items": {"type": "string"}},
            "construction_wins": {"type": "array", "items": {"type": "object", "properties": {
                "construction": {"type": "string"}, "quote": {"type": "string"}},
                "required": ["construction", "quote"]}},
            "missed_constructions": {"type": "array", "items": {"type": "object", "properties": {
                "construction": {"type": "string"}, "before": {"type": "string"},
                "after": {"type": "string"}},
                "required": ["construction", "before", "after"]}},
            "new_constructions": {"type": "array", "items": {"type": "object", "properties": {
                "construction": {"type": "string"}, "rule": {"type": "string"},
                "example": {"type": "string"}},
                "required": ["construction", "rule", "example"]}},
        },
        "required": ["wins", "focus_pattern", "recurring", "new_phrases", "reused_phrases", "snapshot"],
    },
}

_MAX_TOKENS = 8000

PATTERN_NAMING_RULE = (
    "Name the grammar rule, not the symptom: one sentence of advice must fix every example "
    "filed under the name (good: \"Articles\", \"Verb + preposition\", \"Relative pronouns\", "
    "\"Linking clauses\"; too broad: \"Missing words\", \"Word choice\", \"Grammar\", "
    "\"Wrong word\", \"Typos\")."
)


def system_prompt(profile: Profile) -> str:
    hint = profile.interference_hint()
    return (
        f"{ANALYSIS_PREAMBLE} {profile.learner()} who wants to "
        "sound more fluent and natural in English. You analyze the learner's own Claude Code "
        "prompts. Ground EVERY point in a direct quote of their actual words. Be concise and "
        "aware of the idioms of their field. Never fabricate: if a section has nothing real, "
        "return it empty." + (f" {hint}" if hint else "")
    )


def build_analysis_prompt(prompts: list[UserPrompt], phrasebook: list[PhraseInfo],
                          max_new_phrases: int = 2, known_patterns=(),
                          profile: Profile = Profile(), constructions=(),
                          max_new_constructions: int = 1) -> str:
    patterns = "\n".join(f"- {name}: {desc}" if desc else f"- {name}"
                         for name, desc in known_patterns) or "- (none yet)"
    book = "\n".join(f"- {p.phrase} (status: {p.status}, reuse_count: {p.reuse_count})"
                     for p in phrasebook) or "- (empty)"
    cons = "\n".join(f"- {c.construction} | {c.status} | {c.rule or '-'}"
                     for c in constructions) or "- (none yet)"
    joined = "\n\n".join(f"[{i + 1}] {p.text}" for i, p in enumerate(prompts))
    return (
        f"{system_prompt(profile)}\n\n"
        "Known recurring patterns for this user:\n"
        f"{patterns}\n\n"
        "Current phrasebook (taught phrases — detect which were reused today):\n"
        f"{book}\n\n"
        "Grammar constructions the learner is practicing (name | status | rule) — everyday "
        "native structures they rarely use; these are upgrades, not mistakes:\n"
        f"{cons}\n\n"
        "The user's prompts for the period:\n"
        f"{joined}\n\n"
        "Analyze and call report_analysis. reused_phrases must be a subset of the phrasebook "
        "phrase names that the user actually reused correctly. Pick ONE highest-value focus_pattern.\n"
        "For every 'pattern' field (in focus_pattern and recurring), use the EXACT short name "
        "from the 'Known recurring patterns' list above — copied verbatim, NOT expanded or "
        "paraphrased into a sentence — but only when the example truly fits that pattern's "
        "rule. Otherwise coin a new short 2-4 word name. "
        f"{PATTERN_NAMING_RULE} Put the detailed guidance in 'explanation', never in the "
        "name. Typos and one-off vocabulary slips are not patterns: leave them out of "
        "focus_pattern and recurring.\n"
        f"For new_phrases: propose AT MOST {max_new_phrases}, and only if genuinely high-value "
        "for this user — an empty list is a fine answer. Never re-teach anything already in the "
        "phrasebook above, including close variants of it.\n"
        "construction_wins: for each construction listed above that the learner actually used "
        "correctly, give its name copied verbatim and the learner's verbatim quote. Only names "
        "from that list.\n"
        "missed_constructions: AT MOST 3, ONLY for constructions with status 'active'. Pick "
        "sentences the learner actually wrote ('before', verbatim) where that construction would "
        "sound clearly more natural, and rewrite them with it ('after', same meaning). Skip it "
        "if the rewrite is merely different. An empty list is fine.\n"
        f"new_constructions: AT MOST {max_new_constructions}. Only an everyday native grammar "
        "construction the learner's prompts show they avoid — not vocabulary and not a mistake "
        "(those are patterns), and never a variant of a construction, phrase or pattern listed "
        "above. 'rule' is 1-2 plain sentences; 'example' is one of the learner's sentences "
        "rewritten with it. An empty list is fine."
    )


_MAX_MISSED = 3


def _dicts(payload: dict, key: str) -> list[dict]:
    return [x for x in (payload.get(key) or []) if isinstance(x, dict)]


def _text(d: dict, key: str) -> str:
    v = d.get(key)
    return " ".join(v.split()) if isinstance(v, str) else ""  # one line: quotes go into bullets/tables


def parse_analysis(payload: dict, max_new_phrases: int = 2, known_constructions=None,
                   max_new_constructions: int = 1, active_constructions=None) -> Analysis:
    fp_raw = payload.get("focus_pattern")
    fp = None
    if fp_raw:
        fp = FocusPattern(
            pattern=fp_raw["pattern"],
            explanation=fp_raw["explanation"],
            examples=[BeforeAfter(e["before"], e["after"]) for e in fp_raw.get("examples", [])],
        )
    known = (None if known_constructions is None
             else {construction_key(n): n for n in known_constructions})
    active = (None if active_constructions is None
              else {construction_key(n) for n in active_constructions})

    def canon(name: str) -> str | None:
        if not name:
            return None
        return name if known is None else known.get(construction_key(name))

    cons_wins = []
    for d in _dicts(payload, "construction_wins"):
        name, quote = canon(_text(d, "construction")), _text(d, "quote")
        if name and quote:
            cons_wins.append(Win(name, quote))
    missed = []
    for d in _dicts(payload, "missed_constructions"):
        name, before, after = canon(_text(d, "construction")), _text(d, "before"), _text(d, "after")
        if name and before and after and (active is None or construction_key(name) in active):
            missed.append(MissedConstruction(name, before, after))
    new_cons = []
    for d in _dicts(payload, "new_constructions"):
        name, rule, example = _text(d, "construction"), _text(d, "rule"), _text(d, "example")
        if name and rule and (known is None or construction_key(name) not in known):
            new_cons.append(NewConstruction(name, rule, example))
    return Analysis(
        wins=[Win(w["phrase"], w["quote"]) for w in payload.get("wins", [])],
        focus_pattern=fp,
        recurring=[Recurring(r["pattern"], r["before"], r["after"]) for r in payload.get("recurring", [])],
        new_phrases=[NewPhrase(n["phrase"], n["meaning"], n["example"])
                     for n in payload.get("new_phrases", [])[:max_new_phrases]],
        reused_phrases=list(payload.get("reused_phrases", [])),
        snapshot=list(payload.get("snapshot", [])),
        construction_wins=cons_wins,
        missed_constructions=missed[:_MAX_MISSED],
        new_constructions=new_cons[:max_new_constructions],
    )


def _practicing(constructions) -> list[ConstructionInfo]:
    return [c for c in constructions if c.status != "adopted"]


def _active_names(constructions) -> list[str]:
    return [c.construction for c in constructions if c.status == "active"]


class ClaudeAnalyzer:
    def __init__(self, config: Config, client=None):
        self._config = config
        if client is None:
            import anthropic
            client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        self._client = client

    def analyze(self, prompts: list[UserPrompt], phrasebook: list[PhraseInfo],
               known_patterns=(), constructions=()) -> Analysis:
        cons = _practicing(constructions)
        prompt = build_analysis_prompt(prompts, phrasebook, self._config.max_new_phrases,
                                       known_patterns, self._config.profile, cons,
                                       self._config.max_new_constructions)
        message = self._client.messages.create(
            model=self._config.model,
            max_tokens=_MAX_TOKENS,
            tools=[ANALYSIS_TOOL],
            tool_choice={"type": "tool", "name": "report_analysis"},
            messages=[{"role": "user", "content": prompt}],
        )
        for block in message.content:
            if getattr(block, "type", None) == "tool_use":
                return parse_analysis(block.input, self._config.max_new_phrases,
                                      [c.construction for c in cons],
                                      self._config.max_new_constructions, _active_names(cons))
        raise RuntimeError("Claude did not return a tool_use block.")


# --- Claude Code (headless CLI) backend -------------------------------------
# Uses the local `claude -p` CLI (the user's Claude Code subscription auth)
# instead of the Anthropic API, so no API key is required. The analysis is a
# pure text-in / JSON-out call with no tools, so there are no permission prompts.

_CLI_JSON_INSTRUCTION = (
    "\n\nOutput ONLY a single JSON object and nothing else — no prose, no explanation, "
    "no markdown code fences. It must match exactly this shape (the first six keys are "
    "required; construction_wins, missed_constructions and new_constructions are optional but "
    "include them; use [] for empty arrays and null for focus_pattern if there is none):\n"
    '{"wins":[{"phrase":"...","quote":"..."}],'
    '"focus_pattern":{"pattern":"...","explanation":"...",'
    '"examples":[{"before":"...","after":"..."}]},'
    '"recurring":[{"pattern":"...","before":"...","after":"..."}],'
    '"new_phrases":[{"phrase":"...","meaning":"...","example":"..."}],'
    '"reused_phrases":["..."],'
    '"snapshot":["..."],'
    '"construction_wins":[{"construction":"...","quote":"..."}],'
    '"missed_constructions":[{"construction":"...","before":"...","after":"..."}],'
    '"new_constructions":[{"construction":"...","rule":"...","example":"..."}]}'
)


def _resolve_claude() -> str:
    """Locate the claude CLI even when PATH is stripped (e.g. under a scheduler).

    Order: ENGLISH_COACH_CLAUDE env override -> PATH -> the standard native-install
    location ~/.local/bin/claude(.exe) -> bare "claude".
    """
    override = os.environ.get("ENGLISH_COACH_CLAUDE")
    if override:
        return override
    found = shutil.which("claude")
    if found:
        return found
    for name in ("claude.exe", "claude"):
        guess = os.path.join(os.path.expanduser("~"), ".local", "bin", name)
        if os.path.exists(guess):
            return guess
    return "claude"


def run_claude_cli(prompt: str, model: str | None = None, timeout: int = 300, cwd=None) -> str:
    """Run a one-shot `claude -p` and return the model's text reply.

    Pure text-in / JSON-out with no tools (`--allowedTools ""`), so no permission
    prompts. Forces UTF-8 decoding (Windows text mode would otherwise use cp1252
    and mangle em-dashes/curly quotes). `cwd` is the coach's own work dir, so the
    transcript reader can exclude these calls from analysis.
    """
    cli = _resolve_claude()
    # Pass the prompt on STDIN, not as a CLI arg — Windows caps command lines at
    # ~32,767 chars (WinError 206), and a full day of prompts easily exceeds that.
    cmd = [cli, "-p", "--output-format", "json", "--allowedTools", ""]
    if model:
        cmd += ["--model", model]
    extra = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout, cwd=cwd, **extra)
    if proc.returncode != 0:
        raise RuntimeError(
            f"claude CLI failed (exit {proc.returncode}): {(proc.stderr or '').strip()[:500]}"
        )
    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return proc.stdout  # not the JSON envelope; treat raw stdout as the reply
    if isinstance(envelope, dict):
        if envelope.get("is_error"):
            raise RuntimeError(f"claude CLI returned an error result: {str(envelope)[:300]}")
        return envelope.get("result", "")
    return proc.stdout


def extract_json_object(text: str) -> dict:
    """Pull the first top-level JSON object out of a model's text reply.

    Tolerates markdown code fences and surrounding prose by scanning from the
    first '{' to the matching last '}'.
    """
    if text is None:
        raise ValueError("empty model output")
    stripped = text.strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object found in model output")
    return json.loads(stripped[start:end + 1])


class ClaudeCliAnalyzer:
    """Analyzer that calls the local `claude -p` CLI (Claude Code subscription).

    `runner` is injectable for tests: a callable taking the prompt string and
    returning the model's text reply. The default runner shells out to
    `claude.exe -p <prompt> --output-format json --allowedTools ""`.
    """

    def __init__(self, config: Config, runner=None, model: str | None = None, timeout: int = 300):
        self._config = config
        self._model = model  # None => inherit the Claude Code session default
        self._timeout = timeout
        self._runner = runner or self._default_runner

    def _default_runner(self, prompt: str) -> str:
        return run_claude_cli(prompt, model=self._model, timeout=self._timeout)

    def analyze(self, prompts: list[UserPrompt], phrasebook: list[PhraseInfo],
               known_patterns=(), constructions=()) -> Analysis:
        cons = _practicing(constructions)
        prompt = (build_analysis_prompt(prompts, phrasebook, self._config.max_new_phrases,
                                        known_patterns, self._config.profile, cons,
                                        self._config.max_new_constructions)
                 + _CLI_JSON_INSTRUCTION)
        text = self._runner(prompt)
        try:
            payload = extract_json_object(text)
        except (ValueError, json.JSONDecodeError):
            # One stricter retry — models occasionally wrap JSON in prose/fences.
            text = self._runner(prompt + "\n\nReturn ONLY the JSON object. No other text.")
            payload = extract_json_object(text)
        return parse_analysis(payload, self._config.max_new_phrases,
                              [c.construction for c in cons], self._config.max_new_constructions,
                              _active_names(cons))


# --- Phrase enrichment (definition + dev-context sample usage) --------------

def enrich_system(profile: Profile) -> str:
    return (
        f"{ENRICH_PREAMBLE} for an English learner who is {profile.learner()}. "
        "Definitions are one plain-English sentence. Example sentences must sound natural in "
        f"the learner's working context ({profile.work_context()}) — the kind of thing they would "
        "actually say to a colleague or write in a work message."
    )


def build_enrichment_prompt(items: list[dict], examples_per_phrase: int = 3,
                            profile: Profile = Profile()) -> str:
    """items: [{"phrase": str, "your_quote": str | None}]."""
    lines = []
    for it in items:
        q = it.get("your_quote")
        suffix = f'   (the learner actually used it: "{q}")' if q else ""
        lines.append(f"- {it['phrase']}{suffix}")
    listing = "\n".join(lines)
    return (
        f"{enrich_system(profile)}\n\n"
        f"For EACH phrase below, write a one-sentence definition and {examples_per_phrase} "
        f"example sentences in the learner's working context ({profile.work_context()}). Do NOT reuse "
        "the learner's own quoted sentence as an example — write fresh ones.\n\n"
        f"Phrases:\n{listing}\n\n"
        "Output ONLY a single JSON object of exactly this shape — no prose, no markdown fences:\n"
        '{"phrases":[{"phrase":"<the phrase verbatim>","definition":"...","examples":["...","..."]}]}\n'
        "Include EVERY phrase listed, with the phrase copied verbatim so it can be matched back."
    )


def enrich_phrases(items: list[dict], runner=None, examples_per_phrase: int = 3,
                   profile: Profile = Profile()) -> dict:
    """Return {phrase: {"definition": str, "examples": [str, ...]}} for the given phrases.

    `runner` is an injectable callable (prompt -> reply text); defaults to the
    Claude Code CLI. One batched call covers all phrases.
    """
    if not items:
        return {}
    runner = runner or (lambda p: run_claude_cli(p))
    prompt = build_enrichment_prompt(items, examples_per_phrase, profile)
    text = runner(prompt)
    try:
        payload = extract_json_object(text)
    except (ValueError, json.JSONDecodeError):
        text = runner(prompt + "\n\nReturn ONLY the JSON object. No other text.")
        payload = extract_json_object(text)
    out: dict = {}
    for p in payload.get("phrases", []):
        name = p.get("phrase")
        if name:
            out[name] = {"definition": p.get("definition", ""), "examples": list(p.get("examples", []))}
    return out


def pattern_system(profile: Profile) -> str:
    return (
        f"{PATTERN_PREAMBLE} concisely for {profile.learner()}. Each 'rule' is "
        "1-2 plain-English sentences: state the rule and the specific mistake to watch for. "
        "Ground it in the learner's own before/after fixes when given."
    )


def build_pattern_enrichment_prompt(items: list[dict], profile: Profile = Profile()) -> str:
    """items: [{"pattern": str, "description": str, "examples": [(before, after), ...]}]."""
    blocks = []
    for it in items:
        exs = "\n".join(f'    - "{b}"  ->  "{a}"' for b, a in it.get("examples", [])[:8]) or "    (none yet)"
        blocks.append(
            f"- {it['pattern']}\n"
            f"  current note text: {it.get('description', '') or '(none)'}\n"
            f"  the learner's own fixes:\n{exs}"
        )
    listing = "\n".join(blocks)
    return (
        f"{pattern_system(profile)}\n\n"
        "For EACH grammar pattern below, write a crisp 'rule' (1-2 sentences) that states the "
        "rule and the specific mistake to watch for, tailored to the examples.\n\n"
        f"Patterns:\n{listing}\n\n"
        "Output ONLY a single JSON object of exactly this shape — no prose, no markdown fences:\n"
        '{"patterns":[{"pattern":"<the pattern name verbatim>","rule":"..."}]}\n'
        "Include EVERY pattern, name copied verbatim so it can be matched back."
    )


def enrich_patterns(items: list[dict], runner=None, profile: Profile = Profile()) -> dict:
    """Return {pattern: {"rule": str}} for the given patterns. One batched call."""
    if not items:
        return {}
    runner = runner or (lambda p: run_claude_cli(p))
    prompt = build_pattern_enrichment_prompt(items, profile)
    text = runner(prompt)
    try:
        payload = extract_json_object(text)
    except (ValueError, json.JSONDecodeError):
        text = runner(prompt + "\n\nReturn ONLY the JSON object. No other text.")
        payload = extract_json_object(text)
    out: dict = {}
    for p in payload.get("patterns", []):
        name = p.get("pattern")
        if name:
            out[name] = {"rule": p.get("rule", "")}
    return out


def build_pattern_resplit_prompt(items: list[dict], profile: Profile = Profile()) -> str:
    """items: [{"pattern": str, "rule": str, "examples": [(before, after), ...]}]."""
    blocks = []
    for it in items:
        exs = "\n".join(f'    - "{b}"  ->  "{a}"' for b, a in it.get("examples", [])) or "    (none)"
        blocks.append(f"- {it['pattern']}\n  rule: {it.get('rule', '') or '(none)'}\n  examples:\n{exs}")
    listing = "\n".join(blocks)
    return (
        f"{PATTERN_PREAMBLE} to {profile.learner()} and keep their mistake notes tidy.\n\n"
        f"Audit the grammar pattern notes below. {PATTERN_NAMING_RULE}\n"
        "For EACH note answer \"keep\" if all its examples share one rule. Otherwise answer "
        "\"split\" and give EVERY example a target: the name of another note below when the "
        "example truly fits its rule, a new short 2-4 word rule name, or null to drop it "
        "(typos and one-off vocabulary slips are not patterns). A split note's own name is "
        "never a target.\n\n"
        f"Notes:\n{listing}\n\n"
        "Output ONLY a single JSON object of exactly this shape — no prose, no markdown fences:\n"
        '{"notes":[{"pattern":"<note name verbatim>","action":"keep"},'
        '{"pattern":"<note name verbatim>","action":"split","examples":'
        '[{"before":"<before text verbatim>","target":"<pattern name or null>"}]}]}\n'
        "Include EVERY note; copy names and 'before' texts verbatim so they can be matched back."
    )


def resplit_patterns(items: list[dict], runner=None, profile: Profile = Profile()) -> dict:
    """Return {pattern: {before: target-or-None}} for the notes the model wants split.
    One batched call; targets are passed through unvalidated."""
    if not items:
        return {}
    runner = runner or (lambda p: run_claude_cli(p))
    prompt = build_pattern_resplit_prompt(items, profile)
    text = runner(prompt)
    try:
        payload = extract_json_object(text)
    except (ValueError, json.JSONDecodeError):
        text = runner(prompt + "\n\nReturn ONLY the JSON object. No other text.")
        payload = extract_json_object(text)
    out: dict = {}
    for n in payload.get("notes") or []:
        if not (isinstance(n, dict) and n.get("action") == "split"
                and isinstance(n.get("pattern"), str)):
            continue
        out[n["pattern"]] = {" ".join(ex["before"].split()): ex.get("target")
                             for ex in n.get("examples") or []
                             if isinstance(ex, dict) and isinstance(ex.get("before"), str)}
    return out


def construction_enrich_system(profile: Profile) -> str:
    return (
        f"{CONSTRUCTION_ENRICH_PREAMBLE} to {profile.learner()}. Each 'rule' is 1-2 plain-English "
        "sentences: the form of the construction and when native speakers reach for it. Example "
        f"sentences must sound natural in the learner's working context ({profile.work_context()}) "
        "— the kind of thing they would actually say to a colleague or write in a work message."
    )


def build_construction_enrichment_prompt(items: list[dict], examples_per_construction: int = 3,
                                         profile: Profile = Profile()) -> str:
    """items: [{"construction": str, "rule": str, "your_quote": str | None}]."""
    blocks = []
    for it in items:
        q = it.get("your_quote")
        suffix = f'\n  the learner actually used it: "{q}"' if q else ""
        blocks.append(f"- {it['construction']}\n  current rule: {it.get('rule') or '(none)'}{suffix}")
    listing = "\n".join(blocks)
    return (
        f"{construction_enrich_system(profile)}\n\n"
        f"For EACH construction below, write a crisp 'rule' and {examples_per_construction} example "
        "sentences. Do NOT reuse the learner's own quoted sentence as an example — write fresh ones.\n\n"
        f"Constructions:\n{listing}\n\n"
        "Output ONLY a single JSON object of exactly this shape — no prose, no markdown fences:\n"
        '{"constructions":[{"construction":"<the name verbatim>","rule":"...","examples":["...","..."]}]}\n'
        "Include EVERY construction, name copied verbatim so it can be matched back."
    )


def enrich_constructions(items: list[dict], runner=None, examples_per_construction: int = 3,
                         profile: Profile = Profile()) -> dict:
    """Return {construction: {"rule": str, "examples": [str, ...]}}. One batched call."""
    if not items:
        return {}
    runner = runner or (lambda p: run_claude_cli(p))
    prompt = build_construction_enrichment_prompt(items, examples_per_construction, profile)
    text = runner(prompt)
    try:
        payload = extract_json_object(text)
    except (ValueError, json.JSONDecodeError):
        text = runner(prompt + "\n\nReturn ONLY the JSON object. No other text.")
        payload = extract_json_object(text)
    out: dict = {}
    for c in payload.get("constructions", []):
        name = c.get("construction")
        if name:
            out[name] = {"rule": c.get("rule", ""), "examples": list(c.get("examples", []))}
    return out
