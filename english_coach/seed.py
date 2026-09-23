from __future__ import annotations

KNOWN_PATTERNS: list[tuple[str, str]] = [
    ("Articles",
     "a/an/the — the #1 issue: both omits needed ones (\"run mcp server\", \"from "
     "library\") and adds unneeded ones (\"the access\"). Uncountable -> no article; "
     "singular countable -> article."),
    ("Question formation",
     "Direct questions missing the auxiliary + wrong adverb placement (\"Why we need "
     "here the reference?\" -> \"Why do we need the reference here?\"); indirect "
     "questions wrongly inverted (\"show me what would the final version look like\" -> "
     "\"...what the final version would look like\")."),
    ("This vs these",
     "Singular vs plural demonstratives — \"this changes\" vs \"these changes\"."),
    ("Sense verb + adjective",
     "sound/look/feel take an adjective, not an adverb — \"sound fluent\", not "
     "\"sound fluently\"."),
    ("Then-calque in when-clauses",
     "Dropping the redundant \"then\" calqued from Polish in when/if-clauses."),
    ("Possessive + ordinal order",
     "Order of possessive and ordinal — \"Pete's second comment\"."),
]

TAUGHT_IDIOMS: list[str] = [
    "park it", "leaning towards", "live in", "pull up", "push down", "hoist",
    "drop", "get rid of", "it's all or nothing", "is it worth the churn?",
    "my gut tells me", "the culprit behind", "that doesn't seem right",
    "circle back", "go with",
]
