"""Inline before → after markup: ~~only in before~~ **only in after**.

render_fix shows a correction as one sentence with the change marked; parse_fix recovers
the (before, after) pair from it, so notes never need to store the two sentences separately.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

_TOKEN = re.compile(r"\s*(\w+(?:'\w+)*|[^\w\s])")
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


def _tokens(text: str) -> list[tuple[str, str]]:
    """(leading whitespace, token) pairs."""
    return [(m.group(0)[:len(m.group(0)) - len(m.group(1))], m.group(1))
            for m in _TOKEN.finditer(text)]


def _join(toks: list[tuple[str, str]]) -> str:
    return "".join(ws + _escape(t) for ws, t in toks).strip()


def render_fix(before: str, after: str) -> str:
    """One sentence with the change marked: ~~removed~~ **added**."""
    before, after = _norm(before), _norm(after)
    if before == after:
        return _escape(after)
    a, b = _tokens(before), _tokens(after)
    sm = SequenceMatcher(None, [t for _, t in a], [t for _, t in b], autojunk=False)
    if sm.ratio() < _MIN_RATIO:  # mostly rewritten: inline marks would be noise
        return f"~~{_escape(before)}~~ → **{_escape(after)}**"
    out = []
    after_delete = None  # before-side whitespace to restore after a pure deletion
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            toks = list(b[j1:j2])
            if after_delete is not None:
                toks[0] = (toks[0][0] or after_delete, toks[0][1])
            out.append("".join(ws + _escape(t) for ws, t in toks))
            after_delete = None
            continue
        ws = b[j1][0] if j1 < j2 else a[i1][0]
        text = f"~~{_join(a[i1:i2])}~~" if i1 < i2 else ""
        if j1 < j2:
            ins = _join(b[j1:j2])
            gap = " " if text and re.match(r"\w", ins) else ""
            text += f"{gap}**{ins}**"
        out.append(ws + text)
        after_delete = a[i2][0] if (j1 == j2 and i2 < len(a)) else None
    return "".join(out).strip()


def text_key(text: str) -> str:
    """Comparison key for example text: spacing can't survive render → parse exactly
    (equal words take the corrected sentence's spacing), so compare without whitespace."""
    return "".join(_unescape(text).split())


def parse_fix(text: str) -> tuple[str, str]:
    """(before, after) from render_fix output, whitespace-normalised."""
    text = text.strip()
    m = _FALLBACK.match(text)
    if m:
        return _norm(_unescape(m.group("b"))), _norm(_unescape(m.group("a")))
    before = _INS.sub("", _DEL.sub(r"\1", text))
    after = _DEL.sub("", _INS.sub(r"\1", text))
    return _norm(_unescape(before)), _norm(_unescape(after))
