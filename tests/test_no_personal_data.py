import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Assembled from pieces so this file does not match itself.
FORBIDDEN = [
    r"C:\\Users\\[A-Za-z]",            # absolute Windows user paths
    "soft" + "wareone", "mpt" + "-library", "ai-" + "knowledge",
    "Polish" + "-native", r"\.NET", "lang" + "fuse", "war" + "saw",
]
SCANNED = [ROOT / "README.md", ROOT / "pyproject.toml", *sorted((ROOT / "english_coach").rglob("*.py")),
           *sorted((ROOT / "english_coach" / "assets").glob("*.toml"))]


def test_no_personal_or_internal_strings():
    hits = []
    for path in SCANNED:
        text = path.read_text(encoding="utf-8")
        for pat in FORBIDDEN:
            for m in re.finditer(pat, text, flags=re.IGNORECASE):
                hits.append(f"{path.relative_to(ROOT)}: {m.group(0)!r}")
    assert not hits, "\n".join(hits)
