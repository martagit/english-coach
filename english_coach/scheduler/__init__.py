from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ScheduleStatus:
    installed: bool
    detail: str
    unavailable: bool = False  # no scheduler we can query; `installed` is unknown


class SchedulerUnavailable(RuntimeError):
    """No supported scheduler; the message tells the user what to do manually."""


def _abs(p: str) -> str:
    return str(Path(p).expanduser().resolve())


def scheduled_command(env: dict | None = None) -> list[str]:
    """The command the OS job runs. Scheduled jobs don't see the user's shell
    environment, so directory overrides from `env` are baked in as flags."""
    env = {} if env is None else env
    exe = Path(sys.executable)
    if sys.platform == "win32":
        pyw = exe.with_name("pythonw.exe")  # no console window flashing every morning
        if pyw.exists():
            exe = pyw
    cmd = [str(exe), "-m", "english_coach", "run"]
    if env.get("ENGLISH_COACH_CONFIG_DIR"):
        cmd += ["--config-dir", _abs(env["ENGLISH_COACH_CONFIG_DIR"])]
    if env.get("CLAUDE_CONFIG_DIR"):
        cmd += ["--claude-config-dir", _abs(env["CLAUDE_CONFIG_DIR"])]
    return cmd


def _backend():
    if sys.platform == "win32":
        from english_coach.scheduler import windows as m
    elif sys.platform == "darwin":
        from english_coach.scheduler import macos as m
    else:
        from english_coach.scheduler import linux as m
    return m


def install(time_hhmm: str, log_dir: Path, command: list[str] | None = None,
            run=subprocess.run, env: dict | None = None) -> str:
    m = _backend()
    command = command or scheduled_command(env)
    if m.__name__.endswith("macos"):
        return m.install(time_hhmm, log_dir, command, run=run)
    return m.install(time_hhmm, command, run=run)


def remove(run=subprocess.run) -> None:
    _backend().remove(run=run)


def status(run=subprocess.run) -> ScheduleStatus:
    return _backend().status(run=run)
