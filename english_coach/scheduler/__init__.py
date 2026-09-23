from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ScheduleStatus:
    installed: bool
    detail: str


class SchedulerUnavailable(RuntimeError):
    """No supported scheduler; the message tells the user what to do manually."""


def scheduled_command() -> list[str]:
    exe = Path(sys.executable)
    if sys.platform == "win32":
        pyw = exe.with_name("pythonw.exe")  # no console window flashing every morning
        if pyw.exists():
            exe = pyw
    return [str(exe), "-m", "english_coach", "run"]


def _backend():
    if sys.platform == "win32":
        from english_coach.scheduler import windows as m
    elif sys.platform == "darwin":
        from english_coach.scheduler import macos as m
    else:
        from english_coach.scheduler import linux as m
    return m


def install(time_hhmm: str, log_dir: Path, command: list[str] | None = None,
            run=subprocess.run) -> str:
    m = _backend()
    command = command or scheduled_command()
    if m.__name__.endswith("macos"):
        return m.install(time_hhmm, log_dir, command, run=run)
    return m.install(time_hhmm, command, run=run)


def remove(run=subprocess.run) -> None:
    _backend().remove(run=run)


def status(run=subprocess.run) -> ScheduleStatus:
    return _backend().status(run=run)
