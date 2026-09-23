from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

_FILENAME = ".coach-state.json"


def read_watermark(vault: Path) -> datetime | None:
    path = Path(vault) / _FILENAME
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    raw = data.get("covered_through")
    if not raw:
        return None
    return datetime.fromisoformat(raw).astimezone(timezone.utc)


def write_watermark(vault: Path, covered_through_utc: datetime) -> None:
    path = Path(vault) / _FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"covered_through": covered_through_utc.isoformat()}, indent=2),
        encoding="utf-8",
    )
