from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

from english_coach.scheduler import ScheduleStatus

TASK_NAME = "English Coach"
_LOGON_DELAY = "PT5M"


def _default_user() -> str:
    domain, user = os.environ.get("USERDOMAIN", ""), os.environ.get("USERNAME", "")
    return f"{domain}\\{user}" if domain else user


def render_task_xml(command: list[str], time_hhmm: str, user: str) -> str:
    exe, args = command[0], subprocess.list2cmdline(command[1:])
    u = escape(user)
    # Daily trigger + logon trigger: an Interactive task whose daily trigger fires
    # before the user logs on is dropped, not deferred — the logon trigger catches up.
    # Running twice a day is harmless: the run is watermark-driven.
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Daily English coaching vault from Claude Code prompts.</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2026-01-01T{time_hhmm}:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{u}</UserId>
      <Delay>{_LOGON_DELAY}</Delay>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{u}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <ExecutionTimeLimit>PT30M</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(exe)}</Command>
      <Arguments>{escape(args)}</Arguments>
    </Exec>
  </Actions>
</Task>
"""


def install(time_hhmm: str, command: list[str], run=subprocess.run, user: str | None = None,
            tmp_dir: Path | None = None) -> str:
    xml = render_task_xml(command, time_hhmm, user or _default_user())
    tmp_dir = Path(tmp_dir or tempfile.gettempdir())
    xml_path = tmp_dir / "english-coach-task.xml"
    xml_path.write_text(xml, encoding="utf-16")  # schtasks requires UTF-16
    proc = run(["schtasks", "/Create", "/TN", TASK_NAME, "/XML", str(xml_path), "/F"],
               capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"schtasks failed: {(proc.stderr or proc.stdout).strip()}")
    return f"Task Scheduler: '{TASK_NAME}' daily at {time_hhmm}, plus at logon (+5 min)."


def remove(run=subprocess.run) -> None:
    run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], capture_output=True, text=True)


def status(run=subprocess.run) -> ScheduleStatus:
    proc = run(["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "LIST", "/V"],
               capture_output=True, text=True)
    if proc.returncode != 0:
        return ScheduleStatus(False, f"Task '{TASK_NAME}' not found.")
    keep = [l.strip() for l in proc.stdout.splitlines()
            if l.strip().startswith(("Next Run Time", "Last Run Time", "Last Result"))]
    return ScheduleStatus(True, "; ".join(keep) or f"Task '{TASK_NAME}' registered.")
