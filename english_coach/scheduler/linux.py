from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

from english_coach.scheduler import ScheduleStatus, SchedulerUnavailable

UNIT = "english-coach"


def _sd_quote(arg: str) -> str:
    escaped = arg.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    return f'"{escaped}"'


def render_service(command: list[str]) -> str:
    return ("[Unit]\nDescription=English Coach daily run\n\n"
            "[Service]\nType=oneshot\n"
            f"ExecStart={' '.join(_sd_quote(a) for a in command)}\n")


def render_timer(time_hhmm: str) -> str:
    return ("[Unit]\nDescription=English Coach daily timer\n\n"
            f"[Timer]\nOnCalendar=*-*-* {time_hhmm}:00\nPersistent=true\n\n"
            "[Install]\nWantedBy=timers.target\n")


def render_crontab(command: list[str], time_hhmm: str) -> str:
    hour, minute = (int(x) for x in time_hhmm.split(":"))
    cmd = " ".join(shlex.quote(a) for a in command)
    return f"{minute} {hour} * * * {cmd}\n@reboot sleep 300 && {cmd}\n"


def _config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def systemd_available(run=subprocess.run) -> bool:
    if not shutil.which("systemctl"):
        return False
    return run(["systemctl", "--user", "show-environment"],
               capture_output=True, text=True).returncode == 0


def install(time_hhmm: str, command: list[str], run=subprocess.run,
            config_home: Path | None = None, systemd_ok: bool | None = None) -> str:
    ok = systemd_available(run) if systemd_ok is None else systemd_ok
    if not ok:
        raise SchedulerUnavailable(
            "systemd user timers are not available. Add these lines with `crontab -e`:\n"
            + render_crontab(command, time_hhmm))
    unit_dir = Path(config_home or _config_home()) / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    (unit_dir / f"{UNIT}.service").write_text(render_service(command), encoding="utf-8")
    (unit_dir / f"{UNIT}.timer").write_text(render_timer(time_hhmm), encoding="utf-8")
    run(["systemctl", "--user", "daemon-reload"], capture_output=True, text=True)
    proc = run(["systemctl", "--user", "enable", "--now", f"{UNIT}.timer"],
               capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"systemctl failed: {(proc.stderr or proc.stdout).strip()}")
    return f"systemd: {UNIT}.timer daily at {time_hhmm} (Persistent: catches up after boot)."


def remove(run=subprocess.run, config_home: Path | None = None) -> None:
    run(["systemctl", "--user", "disable", "--now", f"{UNIT}.timer"], capture_output=True, text=True)
    unit_dir = Path(config_home or _config_home()) / "systemd" / "user"
    for suffix in ("service", "timer"):
        (unit_dir / f"{UNIT}.{suffix}").unlink(missing_ok=True)
    run(["systemctl", "--user", "daemon-reload"], capture_output=True, text=True)


def status(run=subprocess.run) -> ScheduleStatus:
    if not shutil.which("systemctl"):
        return ScheduleStatus(False, "systemd not available (check your crontab).")
    proc = run(["systemctl", "--user", "is-enabled", f"{UNIT}.timer"], capture_output=True, text=True)
    if proc.returncode != 0:
        return ScheduleStatus(False, f"{UNIT}.timer not enabled.")
    nxt = run(["systemctl", "--user", "list-timers", f"{UNIT}.timer", "--no-pager"],
              capture_output=True, text=True).stdout.strip().splitlines()
    return ScheduleStatus(True, nxt[1] if len(nxt) > 1 else f"{UNIT}.timer enabled.")
