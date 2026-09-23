from __future__ import annotations

from pathlib import Path
import yaml


class _NoAliasDumper(yaml.SafeDumper):
    """Never emit YAML anchors/aliases (&id/*id) — inline repeated values instead.
    Otherwise a single-day note's identical from/to dates serialize as an anchor."""

    def ignore_aliases(self, data):
        return True


def parse_note(text: str) -> tuple[dict, str]:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            fm = yaml.safe_load(parts[1]) or {}
            return fm, parts[2].lstrip("\n")
    return {}, text


def render_note(frontmatter: dict, body: str) -> str:
    fm_text = yaml.dump(frontmatter, Dumper=_NoAliasDumper, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{fm_text}\n---\n\n{body.strip()}\n"


def read_note(path: Path) -> tuple[dict, str]:
    return parse_note(Path(path).read_text(encoding="utf-8"))


def write_note(path: Path, frontmatter: dict, body: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_note(frontmatter, body), encoding="utf-8")
