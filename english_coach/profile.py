from __future__ import annotations

from dataclasses import dataclass

_DEFAULT_CONTEXT = "software developer"


def _article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


@dataclass(frozen=True)
class Profile:
    native_language: str = ""
    context: str = _DEFAULT_CONTEXT

    def work_context(self) -> str:
        return self.context.strip() or _DEFAULT_CONTEXT

    def learner(self) -> str:
        lang = self.native_language.strip()
        phrase = f"{lang}-native {self.work_context()}" if lang else self.work_context()
        return f"{_article(phrase)} {phrase}"

    def interference_hint(self) -> str:
        lang = self.native_language.strip()
        if not lang:
            return ""
        return (f"Watch especially for calques and interference typical of {lang} speakers "
                "(word order, articles, prepositions, literal translations).")
