from __future__ import annotations

import io
import json
import sys
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path

_MAX_BYTES = 512_000
_BACKUPS = 3


class _Tee(io.TextIOBase):
    def __init__(self, *streams):
        self._streams = [s for s in streams if s is not None]

    def write(self, s):
        for st in self._streams:
            try:
                st.write(s)
            except (UnicodeEncodeError, ValueError):
                st.write(s.encode("ascii", "replace").decode("ascii"))
        return len(s)

    def flush(self):
        for st in self._streams:
            st.flush()


def _rotate(log_file: Path) -> None:
    if not log_file.exists() or log_file.stat().st_size < _MAX_BYTES:
        return
    for i in range(_BACKUPS, 0, -1):
        src = log_file if i == 1 else log_file.with_name(f"{log_file.name}.{i - 1}")
        dst = log_file.with_name(f"{log_file.name}.{i}")
        if src.exists():
            src.replace(dst)


@contextmanager
def run_log(log_file: Path):
    log_file = Path(log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    _rotate(log_file)
    with log_file.open("a", encoding="utf-8") as fh:
        fh.write(f"\n=== run {datetime.now().isoformat(timespec='seconds')} ===\n")
        out, err = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = _Tee(out, fh), _Tee(err, fh)
        try:
            yield
        finally:
            sys.stdout, sys.stderr = out, err


def write_last_run(path: Path, status: str, stats=None, now: datetime | None = None) -> None:
    """`stats` is a ReadStats, an already-serialized dict (carried over), or None."""
    now = now or datetime.now(timezone.utc)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"finished_at": now.isoformat(), "status": status,
                                "stats": asdict(stats) if is_dataclass(stats) else stats},
                               indent=2), encoding="utf-8")


def read_last_run(path: Path) -> dict | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
