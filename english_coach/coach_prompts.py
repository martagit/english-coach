"""Fixed opening words of every prompt the coach sends to Claude.

Kept in a dependency-free module so both the prompt builders (analyzer, curator)
and the transcript reader can use them: the reader skips any "user" prompt that
starts with one of these, as a second line of defence against analyzing the
coach's own `claude -p` calls.
"""

ANALYSIS_PREAMBLE = "You are an encouraging English teacher for"
ENRICH_PREAMBLE = "You write concise flashcard content"
PATTERN_PREAMBLE = "You explain English grammar rules"
CURATOR_PREAMBLE = "You curate a personal English phrasebook"

CONSTRUCTION_ENRICH_PREAMBLE = "You explain everyday English grammar constructions"
CONSTRUCTION_CURATOR_PREAMBLE = "You curate a personal list of English grammar constructions"

COACH_PROMPT_PREFIXES = (ANALYSIS_PREAMBLE, ENRICH_PREAMBLE, PATTERN_PREAMBLE, CURATOR_PREAMBLE,
                         CONSTRUCTION_ENRICH_PREAMBLE, CONSTRUCTION_CURATOR_PREAMBLE)
