from __future__ import annotations

import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path


class AlreadyRunning(RuntimeError):
    pass


def pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _is_stale(path: Path, stale_after_s: int, now) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        pid, started = int(data["pid"]), float(data["started"])
    except (OSError, ValueError, KeyError, TypeError):
        return True
    return (now() - started) > stale_after_s or not pid_alive(pid)


def _create(path: Path, now) -> None:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"pid": os.getpid(), "started": now()}, fh)


@contextmanager
def run_lock(path: Path, stale_after_s: int = 1800, now=time.time):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _create(path, now)
    except FileExistsError:
        if not _is_stale(path, stale_after_s, now):
            raise AlreadyRunning(f"Another english-coach run holds {path}")
        path.unlink(missing_ok=True)
        try:
            _create(path, now)
        except FileExistsError:
            raise AlreadyRunning(f"Another english-coach run holds {path}")
    try:
        yield
    finally:
        path.unlink(missing_ok=True)
