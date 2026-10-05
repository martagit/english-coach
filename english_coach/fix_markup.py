"""Inline before → after markup: ~~only in before~~ **only in after**.

render_fix shows a correction as one sentence with the change marked; parse_fix recovers
the (before, after) pair from it, so notes never need to store the two sentences separately.

The diff works on whitespace-separated words, so every marker sits next to a space or the
end of the text: Markdown (and Obsidian) only renders ** and ~~ that aren't glued to a
letter on their outer side, e.g. `day**,**` shows literal asterisks but `~~day~~ **day,**`
renders.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

_FALLBACK = re.compile(r"^~~(?P<b>.+?)(?<!\\)~~ → \*\*(?P<a>.+)(?<!\\)\*\*$")
_DEL = re.compile(r"(?<!\\)~~(.+?)(?<!\\)~~")
_INS = re.compile(r"(?<!\\)\*\*(.+?)(?<!\\)\*\*")
_MIN_RATIO = 0.5


def _escape(text: str) -> str:
    return text.replace("*", r"\*").replace("~", r"\~")


def _unescape(text: str) -> str:
    return text.replace(r"\*", "*").replace(r"\~", "~")


def _norm(text: str) -> str:
    return " ".join(text.split())


def _words(words: list[str]) -> str:
    return " ".join(_escape(w) for w in words)


def _fallback(before: str, after: str) -> str:
    return f"~~{_escape(before)}~~ → **{_escape(after)}**"


def render_fix(before: str, after: str) -> str:
    """One sentence with the change marked: ~~removed~~ **added**."""
    before, after = _norm(before), _norm(after)
    if before == after:
        return _escape(after)
    if not before:
        return f"**{_escape(after)}**"
    if not after:
        return f"~~{_escape(before)}~~"
    a, b = before.split(), after.split()
    sm = SequenceMatcher(None, a, b, autojunk=False)
    if sm.ratio() < _MIN_RATIO:  # mostly rewritten: inline marks would be noise
        return _fallback(before, after)
    out = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            out.append(_words(b[j1:j2]))
            continue
        if i1 < i2:
            out.append(f"~~{_words(a[i1:i2])}~~")
        if j1 < j2:
            out.append(f"**{_words(b[j1:j2])}**")
    rendered = " ".join(out)
    # Learner text that itself looks like markup could make the result ambiguous.
    return rendered if parse_fix(rendered) == (before, after) else _fallback(before, after)


def text_key(text: str) -> str:
    """Comparison key for example text: compares without escapes or whitespace, so the same
    correction typed with different spacing counts as one."""
    return "".join(_unescape(text).split())


def parse_fix(text: str) -> tuple[str, str]:
    """(before, after) from render_fix output, whitespace-collapsed."""
    text = text.strip()
    m = _FALLBACK.match(text)
    if m:
        return _norm(_unescape(m.group("b"))), _norm(_unescape(m.group("a")))
    before = _INS.sub("", _DEL.sub(r"\1", text))
    after = _DEL.sub("", _INS.sub(r"\1", text))
    return _norm(_unescape(before)), _norm(_unescape(after))
