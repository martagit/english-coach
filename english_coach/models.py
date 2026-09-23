from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date


@dataclass(frozen=True)
class UserPrompt:
    text: str
    timestamp_utc: datetime


@dataclass(frozen=True)
class Window:
    start_utc: datetime
    end_utc: datetime
    days: list[date]

    @property
    def is_empty(self) -> bool:
        return not self.days or self.start_utc >= self.end_utc


@dataclass(frozen=True)
class Win:
    phrase: str
    quote: str


@dataclass(frozen=True)
class BeforeAfter:
    before: str
    after: str


@dataclass(frozen=True)
class FocusPattern:
    pattern: str
    explanation: str
    examples: list[BeforeAfter]


@dataclass(frozen=True)
class Recurring:
    pattern: str
    before: str
    after: str


@dataclass(frozen=True)
class NewPhrase:
    phrase: str
    meaning: str
    example: str


@dataclass(frozen=True)
class Analysis:
    wins: list[Win]
    focus_pattern: FocusPattern | None
    recurring: list[Recurring]
    new_phrases: list[NewPhrase]
    reused_phrases: list[str]
    snapshot: list[str]


@dataclass(frozen=True)
class PhraseInfo:
    phrase: str
    status: str
    reuse_count: int
