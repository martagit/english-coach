from __future__ import annotations

import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path

_UNREADABLE_GRACE_S = 10

_ALREADY_RUNNING_MSG = "Another english-coach run holds {}"


class AlreadyRunning(RuntimeError):
    pass


def pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        # Set up function signatures
        OpenProcess = kernel32.OpenProcess
        OpenProcess.restype = wintypes.HANDLE
        OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]

        GetExitCodeProcess = kernel32.GetExitCodeProcess
        GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        GetExitCodeProcess.restype = wintypes.BOOL

        CloseHandle = kernel32.CloseHandle
        CloseHandle.argtypes = [wintypes.HANDLE]

        handle = OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            error = ctypes.get_last_error()
            if error == 5:  # ERROR_ACCESS_DENIED
                return True
            return False
        try:
            code = wintypes.DWORD()
            success = GetExitCodeProcess(handle, ctypes.byref(code))
            if not success:
                return True
            return code.value == 259  # STILL_ACTIVE
        finally:
            CloseHandle(handle)
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
        # File is unreadable; check if it's old enough to be stale
        try:
            mtime = path.stat().st_mtime
            return (now() - mtime) > _UNREADABLE_GRACE_S
        except OSError:
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
            raise AlreadyRunning(_ALREADY_RUNNING_MSG.format(path))
        path.unlink(missing_ok=True)
        try:
            _create(path, now)
        except FileExistsError:
            raise AlreadyRunning(_ALREADY_RUNNING_MSG.format(path))
    try:
        yield
    finally:
        path.unlink(missing_ok=True)
