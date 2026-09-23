from __future__ import annotations

import os
import plistlib
import subprocess
from pathlib import Path

from english_coach.scheduler import ScheduleStatus

LABEL = "io.github.english-coach"


def render_plist(command: list[str], time_hhmm: str, log_dir: Path,
                  path_env: str | None = None) -> bytes:
    hour, minute = (int(x) for x in time_hhmm.split(":"))
    data = {
        "Label": LABEL,
        "ProgramArguments": list(command),
        "StartCalendarInterval": {"Hour": hour, "Minute": minute},
        "RunAtLoad": True,  # catch up at login; launchd also runs a missed interval after wake
        "StandardOutPath": str(Path(log_dir) / "launchd.log"),
        "StandardErrorPath": str(Path(log_dir) / "launchd.log"),
    }
    if path_env:
        data["EnvironmentVariables"] = {"PATH": path_env}
    return plistlib.dumps(data)


def _agent_path(home: Path) -> Path:
    return Path(home) / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def install(time_hhmm: str, log_dir: Path, command: list[str], run=subprocess.run,
            home: Path | None = None, uid: int | None = None,
            path_env: str | None = None) -> str:
    home = Path(home or Path.home())
    uid = os.getuid() if uid is None else uid
    path_env = os.environ.get("PATH", "") if path_env is None else path_env
    agent = _agent_path(home)
    agent.parent.mkdir(parents=True, exist_ok=True)
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    agent.write_bytes(render_plist(command, time_hhmm, log_dir, path_env))
    run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"], capture_output=True, text=True)
    proc = run(["launchctl", "bootstrap", f"gui/{uid}", str(agent)], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"launchctl bootstrap failed: {(proc.stderr or proc.stdout).strip()}")
    return f"launchd: {agent} daily at {time_hhmm}, plus at login."


def remove(run=subprocess.run, home: Path | None = None, uid: int | None = None) -> None:
    uid = os.getuid() if uid is None else uid
    run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"], capture_output=True, text=True)
    _agent_path(Path(home or Path.home())).unlink(missing_ok=True)


def status(run=subprocess.run, uid: int | None = None) -> ScheduleStatus:
    uid = os.getuid() if uid is None else uid
    proc = run(["launchctl", "print", f"gui/{uid}/{LABEL}"], capture_output=True, text=True)
    if proc.returncode != 0:
        return ScheduleStatus(False, f"launchd agent {LABEL} not loaded.")
    return ScheduleStatus(True, f"launchd agent {LABEL} loaded.")
