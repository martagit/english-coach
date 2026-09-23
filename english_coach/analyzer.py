from __future__ import annotations

import json
import os
import shutil
import subprocess

from english_coach.config import Config
from english_coach.models import (
    Analysis, Win, BeforeAfter, FocusPattern, Recurring, NewPhrase, UserPrompt, PhraseInfo,
)
from english_coach.seed import KNOWN_PATTERNS

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
        },
        "required": ["wins", "focus_pattern", "recurring", "new_phrases", "reused_phrases", "snapshot"],
    },
}

_MAX_TOKENS = 8000

_SYSTEM = (
    "You are an encouraging English teacher for a Polish-native .NET developer who wants to "
    "sound more fluent and natural in English. You analyze the developer's own Claude Code "
    "prompts. Ground EVERY point in a direct quote of their actual words. Be concise and "
    "developer-idiom aware. Never fabricate: if a section has nothing real, return it empty."
)


def build_analysis_prompt(prompts: list[UserPrompt], phrasebook: list[PhraseInfo],
                          max_new_phrases: int = 2) -> str:
    patterns = "\n".join(f"- {name}: {desc}" for name, desc in KNOWN_PATTERNS)
    book = "\n".join(f"- {p.phrase} (status: {p.status}, reuse_count: {p.reuse_count})"
                     for p in phrasebook) or "- (empty)"
    joined = "\n\n".join(f"[{i + 1}] {p.text}" for i, p in enumerate(prompts))
    return (
        f"{_SYSTEM}\n\n"
        "Known recurring patterns for this user:\n"
        f"{patterns}\n\n"
        "Current phrasebook (taught phrases — detect which were reused today):\n"
        f"{book}\n\n"
        "The user's prompts for the period:\n"
        f"{joined}\n\n"
        "Analyze and call report_analysis. reused_phrases must be a subset of the phrasebook "
        "phrase names that the user actually reused correctly. Pick ONE highest-value focus_pattern.\n"
        "For every 'pattern' field (in focus_pattern and recurring), use the EXACT short name "
        "from the 'Known recurring patterns' list above when it applies — e.g. \"Articles\", "
        "\"Question formation\", \"Sense verb + adjective\" — copied verbatim, NOT expanded or "
        "paraphrased into a sentence. Only coin a new short 2-4 word name if the issue is "
        "genuinely not in that list. Put the detailed guidance in 'explanation', never in the name.\n"
        f"For new_phrases: propose AT MOST {max_new_phrases}, and only if genuinely high-value "
        "for this user — an empty list is a fine answer. Never re-teach anything already in the "
        "phrasebook above, including close variants of it."
    )


def parse_analysis(payload: dict, max_new_phrases: int = 2) -> Analysis:
    fp_raw = payload.get("focus_pattern")
    fp = None
    if fp_raw:
        fp = FocusPattern(
            pattern=fp_raw["pattern"],
            explanation=fp_raw["explanation"],
            examples=[BeforeAfter(e["before"], e["after"]) for e in fp_raw.get("examples", [])],
        )
    return Analysis(
        wins=[Win(w["phrase"], w["quote"]) for w in payload.get("wins", [])],
        focus_pattern=fp,
        recurring=[Recurring(r["pattern"], r["before"], r["after"]) for r in payload.get("recurring", [])],
        new_phrases=[NewPhrase(n["phrase"], n["meaning"], n["example"])
                     for n in payload.get("new_phrases", [])[:max_new_phrases]],
        reused_phrases=list(payload.get("reused_phrases", [])),
        snapshot=list(payload.get("snapshot", [])),
    )


class ClaudeAnalyzer:
    def __init__(self, config: Config, client=None):
        self._config = config
        if client is None:
            import anthropic
            client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        self._client = client

    def analyze(self, prompts: list[UserPrompt], phrasebook: list[PhraseInfo]) -> Analysis:
        prompt = build_analysis_prompt(prompts, phrasebook, self._config.max_new_phrases)
        message = self._client.messages.create(
            model=self._config.model,
            max_tokens=_MAX_TOKENS,
            tools=[ANALYSIS_TOOL],
            tool_choice={"type": "tool", "name": "report_analysis"},
            messages=[{"role": "user", "content": prompt}],
        )
        for block in message.content:
            if getattr(block, "type", None) == "tool_use":
                return parse_analysis(block.input, self._config.max_new_phrases)
        raise RuntimeError("Claude did not return a tool_use block.")


# --- Claude Code (headless CLI) backend -------------------------------------
# Uses the local `claude -p` CLI (the user's Claude Code subscription auth)
# instead of the Anthropic API, so no API key is required. The analysis is a
# pure text-in / JSON-out call with no tools, so there are no permission prompts.

_CLI_JSON_INSTRUCTION = (
    "\n\nOutput ONLY a single JSON object and nothing else — no prose, no explanation, "
    "no markdown code fences. It must match exactly this shape (all six keys required; "
    "use [] for empty arrays and null for focus_pattern if there is none):\n"
    '{"wins":[{"phrase":"...","quote":"..."}],'
    '"focus_pattern":{"pattern":"...","explanation":"...",'
    '"examples":[{"before":"...","after":"..."}]},'
    '"recurring":[{"pattern":"...","before":"...","after":"..."}],'
    '"new_phrases":[{"phrase":"...","meaning":"...","example":"..."}],'
    '"reused_phrases":["..."],'
    '"snapshot":["..."]}'
)


def _resolve_claude() -> str:
    """Locate the claude CLI even when PATH is stripped (e.g. under Task Scheduler).

    Order: ENGLISH_COACH_CLAUDE env override -> PATH -> the standard native-install
    location %USERPROFILE%\\.local\\bin\\claude.exe -> bare "claude".
    """
    override = os.environ.get("ENGLISH_COACH_CLAUDE")
    if override:
        return override
    found = shutil.which("claude")
    if found:
        return found
    guess = os.path.join(os.path.expanduser("~"), ".local", "bin", "claude.exe")
    if os.path.exists(guess):
        return guess
    return "claude"


def run_claude_cli(prompt: str, model: str | None = None, timeout: int = 300) -> str:
    """Run a one-shot `claude -p` and return the model's text reply.

    Pure text-in / JSON-out with no tools (`--allowedTools ""`), so no permission
    prompts. Forces UTF-8 decoding (Windows text mode would otherwise use cp1252
    and mangle em-dashes/curly quotes).
    """
    cli = _resolve_claude()
    # Pass the prompt on STDIN, not as a CLI arg — Windows caps command lines at
    # ~32,767 chars (WinError 206), and a full day of prompts easily exceeds that.
    cmd = [cli, "-p", "--output-format", "json", "--allowedTools", ""]
    if model:
        cmd += ["--model", model]
    proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)
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

    def analyze(self, prompts: list[UserPrompt], phrasebook: list[PhraseInfo]) -> Analysis:
        prompt = build_analysis_prompt(prompts, phrasebook, self._config.max_new_phrases) + _CLI_JSON_INSTRUCTION
        text = self._runner(prompt)
        try:
            payload = extract_json_object(text)
        except (ValueError, json.JSONDecodeError):
            # One stricter retry — models occasionally wrap JSON in prose/fences.
            text = self._runner(prompt + "\n\nReturn ONLY the JSON object. No other text.")
            payload = extract_json_object(text)
        return parse_analysis(payload, self._config.max_new_phrases)


# --- Phrase enrichment (definition + dev-context sample usage) --------------

_ENRICH_SYSTEM = (
    "You write concise flashcard content for an English learner who is a Polish-native "
    ".NET / backend developer at a software company. Definitions are one plain-English "
    "sentence. Example sentences must sound natural in a software-development / code-review "
    "context (C#, refactoring, pull requests, architecture, tests, DI) — the kind of thing "
    "this developer would actually say to a teammate or in a PR comment."
)


def build_enrichment_prompt(items: list[dict], examples_per_phrase: int = 3) -> str:
    """items: [{"phrase": str, "your_quote": str | None}]."""
    lines = []
    for it in items:
        q = it.get("your_quote")
        suffix = f'   (the learner actually used it: "{q}")' if q else ""
        lines.append(f"- {it['phrase']}{suffix}")
    listing = "\n".join(lines)
    return (
        f"{_ENRICH_SYSTEM}\n\n"
        f"For EACH phrase below, write a one-sentence definition and {examples_per_phrase} "
        "example sentences in a software-development / code-review context. Do NOT reuse the "
        "learner's own quoted sentence as an example — write fresh ones.\n\n"
        f"Phrases:\n{listing}\n\n"
        "Output ONLY a single JSON object of exactly this shape — no prose, no markdown fences:\n"
        '{"phrases":[{"phrase":"<the phrase verbatim>","definition":"...","examples":["...","..."]}]}\n'
        "Include EVERY phrase listed, with the phrase copied verbatim so it can be matched back."
    )


def enrich_phrases(items: list[dict], runner=None, examples_per_phrase: int = 3) -> dict:
    """Return {phrase: {"definition": str, "examples": [str, ...]}} for the given phrases.

    `runner` is an injectable callable (prompt -> reply text); defaults to the
    Claude Code CLI. One batched call covers all phrases.
    """
    if not items:
        return {}
    runner = runner or (lambda p: run_claude_cli(p))
    prompt = build_enrichment_prompt(items, examples_per_phrase)
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


_PATTERN_SYSTEM = (
    "You explain English grammar rules concisely for a Polish-native .NET / backend "
    "developer. Each 'rule' is 1-2 plain-English sentences: state the rule and the specific "
    "mistake to watch for. Ground it in the developer's own before/after fixes when given."
)


def build_pattern_enrichment_prompt(items: list[dict]) -> str:
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
        f"{_PATTERN_SYSTEM}\n\n"
        "For EACH grammar pattern below, write a crisp 'rule' (1-2 sentences) that states the "
        "rule and the specific mistake to watch for, tailored to the examples.\n\n"
        f"Patterns:\n{listing}\n\n"
        "Output ONLY a single JSON object of exactly this shape — no prose, no markdown fences:\n"
        '{"patterns":[{"pattern":"<the pattern name verbatim>","rule":"..."}]}\n'
        "Include EVERY pattern, name copied verbatim so it can be matched back."
    )


def enrich_patterns(items: list[dict], runner=None) -> dict:
    """Return {pattern: {"rule": str}} for the given patterns. One batched call."""
    if not items:
        return {}
    runner = runner or (lambda p: run_claude_cli(p))
    prompt = build_pattern_enrichment_prompt(items)
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
