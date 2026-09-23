from __future__ import annotations

import re

from english_coach.models import UserPrompt

TRIVIAL_ACKS = {
    "ok", "okay", "yes", "yep", "yeah", "y", "no", "n", "push", "1", "go",
    "go ahead", "continue", "do it", "sure", "thanks", "thx", "ty", "k",
    "next", "proceed", "stop", "wait",
}

_URL_ONLY = re.compile(r"^https?://\S+$", re.IGNORECASE)
_IMAGE_ONLY = re.compile(r"^(\s*\[Image #\d+\]\s*)+$")
_STACKTRACE_MARKERS = ("Traceback (most recent call last)", "\tat ", "\n  File \"")


def is_noise(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if "<task-notification>" in stripped:
        return True
    if _IMAGE_ONLY.match(stripped):
        return True
    if _URL_ONLY.match(stripped):
        return True
    if any(m in stripped for m in _STACKTRACE_MARKERS):
        return True
    if stripped.lower() in TRIVIAL_ACKS:
        return True
    return False


def filter_prompts(prompts: list[UserPrompt]) -> list[UserPrompt]:
    return [p for p in prompts if not is_noise(p.text)]
