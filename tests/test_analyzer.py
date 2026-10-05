import json
import pytest
from pathlib import Path
from english_coach.analyzer import (
    build_analysis_prompt, parse_analysis, ClaudeAnalyzer, ClaudeCliAnalyzer,
    extract_json_object, build_enrichment_prompt, enrich_phrases, ANALYSIS_TOOL,
)
from english_coach.models import UserPrompt, PhraseInfo
from english_coach.config import Config, DEFAULT_MODEL


def _cfg():
    return Config(vault_path=Path("."))


def test_tool_schema_names_expected_fields():
    props = ANALYSIS_TOOL["input_schema"]["properties"]
    for field in ["wins", "focus_pattern", "recurring", "new_phrases", "reused_phrases", "snapshot"]:
        assert field in props


def test_build_prompt_includes_prompts_phrasebook_and_known_patterns():
    text = build_analysis_prompt(
        [UserPrompt("Why we need here the reference?", None)],
        [PhraseInfo("park it", "learning", 0)],
        known_patterns=[("Articles", "a/an/the usage")],
    )
    assert "Why we need here the reference?" in text
    assert "park it" in text
    assert "- Articles: a/an/the usage" in text


def test_build_prompt_without_known_patterns_says_none_yet():
    text = build_analysis_prompt([UserPrompt("Hello team", None)], [])
    assert "(none yet)" in text


def test_prompts_use_profile_not_hardcoded_learner():
    from english_coach.profile import Profile
    from english_coach.analyzer import build_pattern_enrichment_prompt
    from english_coach.curator import build_curation_prompt
    prof = Profile("German", "QA engineer")
    texts = [
        build_analysis_prompt([UserPrompt("x y z", None)], [], profile=prof),
        build_enrichment_prompt([{"phrase": "park it", "your_quote": None}], profile=prof),
        build_pattern_enrichment_prompt([{"pattern": "Articles", "description": "", "examples": []}],
                                        profile=prof),
        build_curation_prompt([], 12, profile=prof),
    ]
    for t in texts:
        assert "a German-native QA engineer" in t
        assert "Polish" not in t and ".NET" not in t


def test_run_claude_cli_passes_cwd(monkeypatch, tmp_path):
    import english_coach.analyzer as az
    seen = {}

    class P:
        returncode = 0
        stdout = '{"result": "hi"}'
        stderr = ""

    def fake_run(cmd, **kw):
        seen.update(kw)
        return P()

    monkeypatch.setattr(az.subprocess, "run", fake_run)
    assert az.run_claude_cli("hello", cwd=tmp_path) == "hi"
    assert seen["cwd"] == tmp_path


def test_parse_analysis_maps_all_sections():
    payload = {
        "wins": [{"phrase": "park it", "quote": "let's park it"}],
        "focus_pattern": {"pattern": "Articles", "explanation": "use the",
                          "examples": [{"before": "run mcp server", "after": "run the MCP server"}]},
        "recurring": [{"pattern": "Question formation", "before": "why we need?", "after": "why do we need it?"}],
        "new_phrases": [{"phrase": "worth the churn", "meaning": "worth it", "example": "is it worth the churn?"}],
        "reused_phrases": ["park it"],
        "snapshot": ["Articles still the gap."],
    }
    a = parse_analysis(payload)
    assert a.wins[0].phrase == "park it"
    assert a.focus_pattern.pattern == "Articles"
    assert a.focus_pattern.examples[0].after == "run the MCP server"
    assert a.recurring[0].pattern == "Question formation"
    assert a.new_phrases[0].phrase == "worth the churn"
    assert a.reused_phrases == ["park it"]
    assert a.snapshot == ["Articles still the gap."]


def test_parse_analysis_handles_null_focus():
    a = parse_analysis({"wins": [], "focus_pattern": None, "recurring": [],
                        "new_phrases": [], "reused_phrases": [], "snapshot": []})
    assert a.focus_pattern is None


class FakeBlock:
    def __init__(self, payload):
        self.type = "tool_use"
        self.input = payload


class FakeMessage:
    def __init__(self, payload):
        self.content = [FakeBlock(payload)]


class FakeMessages:
    def __init__(self, payload):
        self._payload = payload
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return FakeMessage(self._payload)


class FakeAnthropic:
    def __init__(self, payload):
        self.messages = FakeMessages(payload)


def test_claude_analyzer_returns_analysis():
    payload = {"wins": [], "focus_pattern": None, "recurring": [],
               "new_phrases": [], "reused_phrases": [], "snapshot": ["ok"]}
    fake = FakeAnthropic(payload)
    analyzer = ClaudeAnalyzer(_cfg(), client=fake)
    a = analyzer.analyze([UserPrompt("hello world", None)], [])
    assert a.snapshot == ["ok"]
    assert fake.messages.kwargs["model"] == DEFAULT_MODEL
    assert fake.messages.kwargs["tool_choice"]["name"] == "report_analysis"


# --- ClaudeCliAnalyzer (headless CLI backend) -------------------------------

_VALID_JSON = json.dumps({
    "wins": [{"phrase": "park it", "quote": "let's park it"}],
    "focus_pattern": {"pattern": "Articles", "explanation": "use the",
                      "examples": [{"before": "run mcp server", "after": "run the MCP server"}]},
    "recurring": [],
    "new_phrases": [],
    "reused_phrases": ["park it"],
    "snapshot": ["good"],
})


def test_extract_json_object_plain():
    assert extract_json_object('{"a": 1}') == {"a": 1}


def test_extract_json_object_strips_fences_and_prose():
    text = 'Sure! Here is the analysis:\n```json\n{"a": 1, "b": [2]}\n```\nHope that helps.'
    assert extract_json_object(text) == {"a": 1, "b": [2]}


def test_extract_json_object_raises_when_no_object():
    with pytest.raises(ValueError):
        extract_json_object("no json here")


def test_cli_analyzer_parses_runner_output():
    calls = []

    def runner(prompt):
        calls.append(prompt)
        return _VALID_JSON

    analyzer = ClaudeCliAnalyzer(_cfg(), runner=runner)
    a = analyzer.analyze([UserPrompt("hello world", None)], [PhraseInfo("park it", "learning", 2)])
    assert a.wins[0].phrase == "park it"
    assert a.focus_pattern.pattern == "Articles"
    assert a.reused_phrases == ["park it"]
    assert len(calls) == 1  # no retry needed
    assert "Output ONLY a single JSON object" in calls[0]  # CLI instruction appended


def test_cli_analyzer_retries_once_on_unparseable_output():
    outputs = iter(["I could not comply, sorry.", _VALID_JSON])

    def runner(prompt):
        return next(outputs)

    analyzer = ClaudeCliAnalyzer(_cfg(), runner=runner)
    a = analyzer.analyze([UserPrompt("hi", None)], [])
    assert a.snapshot == ["good"]  # second (valid) attempt used


def test_cli_analyzer_handles_null_focus():
    payload = json.dumps({"wins": [], "focus_pattern": None, "recurring": [],
                          "new_phrases": [], "reused_phrases": [], "snapshot": []})
    analyzer = ClaudeCliAnalyzer(_cfg(), runner=lambda p: payload)
    a = analyzer.analyze([UserPrompt("x", None)], [])
    assert a.focus_pattern is None


# --- Phrase enrichment ------------------------------------------------------

def test_build_enrichment_prompt_lists_phrases_and_work_context():
    p = build_enrichment_prompt([{"phrase": "park it", "your_quote": "let's park it"},
                                 {"phrase": "hoist", "your_quote": None}])
    assert "park it" in p and "hoist" in p
    assert "software developer" in p  # default profile working context requested
    assert "let's park it" in p  # the learner's real quote is hinted


def test_enrich_phrases_parses_runner_output():
    reply = json.dumps({"phrases": [
        {"phrase": "park it", "definition": "set aside for later",
         "examples": ["Let's park it.", "Park the caching question."]},
        {"phrase": "hoist", "definition": "lift code out", "examples": ["Hoist the guard clause."]},
    ]})
    out = enrich_phrases([{"phrase": "park it", "your_quote": None},
                          {"phrase": "hoist", "your_quote": None}], runner=lambda p: reply)
    assert out["park it"]["definition"] == "set aside for later"
    assert out["hoist"]["examples"] == ["Hoist the guard clause."]


def test_enrich_phrases_empty_returns_empty():
    assert enrich_phrases([], runner=lambda p: "unused") == {}


def test_run_claude_cli_sends_prompt_via_stdin_not_argv(monkeypatch):
    import english_coach.analyzer as az
    captured = {}

    class _Result:
        returncode = 0
        stdout = '{"type":"result","is_error":false,"result":"{}"}'
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["input"] = kwargs.get("input")
        return _Result()

    monkeypatch.setattr(az.subprocess, "run", fake_run)
    big = "X" * 100000  # far past the Windows command-line limit
    out = az.run_claude_cli(big)
    assert captured["input"] == big                       # prompt went to stdin
    assert big not in " ".join(captured["cmd"])           # NOT on the command line
    assert "-p" in captured["cmd"]
    assert out == "{}"                                    # envelope .result extracted


def test_parse_analysis_truncates_new_phrases():
    payload = {"wins": [], "focus_pattern": None, "recurring": [],
               "new_phrases": [{"phrase": f"p{i}", "meaning": "m", "example": "e"} for i in range(5)],
               "reused_phrases": [], "snapshot": []}
    a = parse_analysis(payload, max_new_phrases=2)
    assert [n.phrase for n in a.new_phrases] == ["p0", "p1"]


def test_build_prompt_throttles_new_phrases():
    text = build_analysis_prompt([UserPrompt("hello", None)], [], max_new_phrases=2)
    assert "AT MOST 2" in text
    assert "empty list is a fine answer" in text


from english_coach.models import ConstructionInfo
from english_coach.analyzer import _CLI_JSON_INSTRUCTION

_CONS = [ConstructionInfo("be supposed to", "active", 0, "expected behaviour"),
         ConstructionInfo("What if we…?", "backlog", 0, "suggestions"),
         ConstructionInfo("unless", "adopted", 5, "if not")]


def _payload(**extra):
    base = {"wins": [], "focus_pattern": None, "recurring": [], "new_phrases": [],
            "reused_phrases": [], "snapshot": []}
    base.update(extra)
    return base


def test_schema_has_optional_construction_keys():
    schema = ANALYSIS_TOOL["input_schema"]
    for key in ("construction_wins", "missed_constructions", "new_constructions"):
        assert key in schema["properties"]
        assert key not in schema["required"]
        assert key in _CLI_JSON_INSTRUCTION


def test_prompt_lists_constructions_and_active_only_rule():
    text = build_analysis_prompt([UserPrompt("x", None)], [], constructions=_CONS[:2],
                                 max_new_constructions=1)
    assert "- be supposed to | active | expected behaviour" in text
    assert "- What if we…? | backlog | suggestions" in text
    assert "ONLY for constructions with status 'active'" in text
    assert "AT MOST 3" in text


def test_prompt_without_constructions_says_none_yet():
    text = build_analysis_prompt([UserPrompt("x", None)], [])
    assert "Grammar constructions" in text and "- (none yet)" in text


def test_parse_without_construction_keys_gives_empty_lists():
    a = parse_analysis(_payload())
    assert a.construction_wins == [] and a.missed_constructions == [] and a.new_constructions == []


def test_parse_construction_keys_canonicalises_and_filters():
    payload = _payload(
        construction_wins=[{"construction": "be supposed to", "quote": "it's supposed to retry"},
                           {"construction": "BE SUPPOSED TO?", "quote": "case differs"},
                           {"construction": "made up", "quote": "x"},
                           {"construction": "be supposed to"},
                           "not a dict"],
        missed_constructions=[{"construction": "What if we...?", "before": "b", "after": "a"}] * 4
                             + [{"construction": "be supposed to", "before": "", "after": "a"}],
        new_constructions=[{"construction": "end up + -ing", "rule": "r", "example": "e"},
                           {"construction": "as long as", "rule": "r", "example": "e"}])
    a = parse_analysis(payload, known_constructions=["be supposed to", "What if we…?"],
                       max_new_constructions=1)
    assert [(w.phrase, w.quote) for w in a.construction_wins] == [("be supposed to", "it's supposed to retry")]
    assert len(a.missed_constructions) == 3
    assert a.missed_constructions[0].construction == "What if we…?"
    assert [n.construction for n in a.new_constructions] == ["end up + -ing"]


def test_parse_new_construction_matching_known_name_is_dropped():
    a = parse_analysis(_payload(new_constructions=[{"construction": "be supposed to",
                                                    "rule": "r", "example": "e"}]),
                       known_constructions=["be supposed to"])
    assert a.new_constructions == []


def test_cli_analyzer_sends_non_adopted_constructions_and_filters():
    seen = {}

    def runner(prompt):
        seen["prompt"] = prompt
        return json.dumps(_payload(construction_wins=[{"construction": "unless", "quote": "q"},
                                                      {"construction": "be supposed to", "quote": "q2"}]))

    a = ClaudeCliAnalyzer(_cfg(), runner=runner).analyze([UserPrompt("x", None)], [], (), _CONS)
    assert "be supposed to | active" in seen["prompt"]
    assert "unless | adopted" not in seen["prompt"]
    assert [w.phrase for w in a.construction_wins] == ["be supposed to"]


def test_construction_enrichment_prompt_and_parse():
    from english_coach.analyzer import build_construction_enrichment_prompt, enrich_constructions
    from english_coach.coach_prompts import CONSTRUCTION_ENRICH_PREAMBLE
    from english_coach.profile import Profile
    items = [{"construction": "unless", "rule": "if not", "your_quote": "wait unless green"}]
    text = build_construction_enrichment_prompt(items, profile=Profile("German", "QA engineer"))
    assert text.startswith(CONSTRUCTION_ENRICH_PREAMBLE)
    assert "a German-native QA engineer" in text and "unless" in text and "wait unless green" in text
    reply = '{"constructions":[{"construction":"unless","rule":"R","examples":["a","b"]},{"rule":"x"}]}'
    assert enrich_constructions(items, runner=lambda p: reply) == {"unless": {"rule": "R", "examples": ["a", "b"]}}
    assert enrich_constructions([], runner=lambda p: 1 / 0) == {}


def test_parse_collapses_multiline_construction_text():
    a = parse_analysis(_payload(
        construction_wins=[{"construction": "be supposed to", "quote": "it is supposed\n  to work"}],
        missed_constructions=[{"construction": "be supposed to", "before": "line one\nline two",
                               "after": "x\ny"}]),
        known_constructions=["be supposed to"])
    assert a.construction_wins[0].quote == "it is supposed to work"
    assert (a.missed_constructions[0].before, a.missed_constructions[0].after) == ("line one line two", "x y")


def test_parse_drops_missed_for_non_active_constructions():
    a = parse_analysis(_payload(missed_constructions=[
        {"construction": "What if we…?", "before": "b", "after": "a"},
        {"construction": "be supposed to", "before": "b", "after": "a"}]),
        known_constructions=["be supposed to", "What if we…?"],
        active_constructions=["be supposed to"])
    assert [m.construction for m in a.missed_constructions] == ["be supposed to"]


def test_parse_matches_curly_apostrophe():
    a = parse_analysis(_payload(construction_wins=[{"construction": "I’d rather", "quote": "q"}]),
                       known_constructions=["I'd rather"])
    assert [w.phrase for w in a.construction_wins] == ["I'd rather"]


def test_prompt_names_patterns_by_rule_not_symptom():
    from english_coach.analyzer import PATTERN_NAMING_RULE
    text = build_analysis_prompt([UserPrompt("x y z", None)], [],
                                 known_patterns=[("Articles", "a/an/the usage")])
    assert PATTERN_NAMING_RULE in text
    assert "one sentence of advice must fix every example" in PATTERN_NAMING_RULE
    for bad in ("Missing words", "Word choice", "Grammar", "Wrong word", "Typos"):
        assert f'"{bad}"' in PATTERN_NAMING_RULE
    assert "only when the example truly fits that pattern's rule" in text
    assert "Typos and one-off vocabulary slips are not patterns" in text
