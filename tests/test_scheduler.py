import os
import plistlib
import subprocess
import sys
from pathlib import Path

import pytest

from english_coach.scheduler import linux, macos, windows

SPACEY = [r"C:\Users\Jane Doe\AppData\Roaming\uv\tools\english-coach\Scripts\pythonw.exe",
          "-m", "english_coach", "run"]
POSIX_SPACEY = ["/Users/Jane Doe/.local/share/uv/tools/english-coach/bin/python",
                "-m", "english_coach", "run"]


class FakeRun:
    def __init__(self, returncode=0, stdout=""):
        self.calls = []
        self._rc, self._out = returncode, stdout

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        return subprocess.CompletedProcess(cmd, self._rc, self._out, "")


# --- Windows -----------------------------------------------------------------

def test_task_xml_has_daily_and_logon_triggers():
    xml = windows.render_task_xml(SPACEY, "07:05", r"DOMAIN\jane")
    assert "<StartBoundary>2026-01-01T07:05:00</StartBoundary>" in xml
    assert "<DaysInterval>1</DaysInterval>" in xml
    assert "<LogonTrigger>" in xml and "<Delay>PT5M</Delay>" in xml
    assert "<StartWhenAvailable>true</StartWhenAvailable>" in xml
    assert "<LogonType>InteractiveToken</LogonType>" in xml
    assert r"<UserId>DOMAIN\jane</UserId>" in xml


def test_task_xml_quotes_paths_with_spaces():
    xml = windows.render_task_xml(SPACEY, "07:00", "u")
    assert f"<Command>{SPACEY[0]}</Command>" in xml
    assert "<Arguments>-m english_coach run</Arguments>" in xml


def test_task_xml_escapes_xml_chars():
    xml = windows.render_task_xml([r"C:\A&B\python.exe", "-m", "english_coach", "run"], "07:00", "u")
    assert r"C:\A&amp;B\python.exe" in xml


def test_windows_install_calls_schtasks_with_xml(tmp_path):
    run = FakeRun()
    windows.install("07:00", SPACEY, run=run, user="u", tmp_dir=tmp_path)
    cmd = run.calls[0]
    assert cmd[:4] == ["schtasks", "/Create", "/TN", windows.TASK_NAME]
    xml_path = Path(cmd[cmd.index("/XML") + 1])
    assert xml_path.read_bytes()[:2] in (b"\xff\xfe", b"\xfe\xff")  # UTF-16 with BOM


# --- macOS -------------------------------------------------------------------

def test_plist_has_calendar_interval_and_run_at_load(tmp_path):
    data = plistlib.loads(macos.render_plist(POSIX_SPACEY, "07:05", tmp_path))
    assert data["Label"] == macos.LABEL
    assert data["ProgramArguments"] == POSIX_SPACEY  # list form: spaces need no quoting
    assert data["StartCalendarInterval"] == {"Hour": 7, "Minute": 5}
    assert data["RunAtLoad"] is True


def test_macos_install_writes_agent_and_bootstraps(tmp_path):
    run = FakeRun()
    macos.install("07:00", tmp_path / "logs", POSIX_SPACEY, run=run, home=tmp_path, uid=501)
    agent = tmp_path / "Library" / "LaunchAgents" / f"{macos.LABEL}.plist"
    assert agent.exists()
    assert ["launchctl", "bootstrap", "gui/501", str(agent)] in run.calls


# --- Linux -------------------------------------------------------------------

def test_service_quotes_paths_with_spaces():
    unit = linux.render_service(POSIX_SPACEY + ["50%"])
    assert 'ExecStart="/Users/Jane Doe/.local/share/uv/tools/english-coach/bin/python" ' in unit
    assert '"50%%"' in unit  # systemd specifier escaping


def test_timer_is_daily_and_persistent():
    timer = linux.render_timer("07:05")
    assert "OnCalendar=*-*-* 07:05:00" in timer
    assert "Persistent=true" in timer
    assert "WantedBy=timers.target" in timer


def test_crontab_fallback_lines():
    text = linux.render_crontab(POSIX_SPACEY, "07:05")
    assert text.splitlines()[0].startswith("5 7 * * * ")
    assert "@reboot" in text
    assert "'/Users/Jane Doe/.local/share/uv/tools/english-coach/bin/python'" in text


def test_linux_install_without_systemd_raises_with_crontab(tmp_path):
    run = FakeRun(returncode=1)
    with pytest.raises(Exception) as exc:
        linux.install("07:00", POSIX_SPACEY, run=run, config_home=tmp_path, systemd_ok=False)
    assert "crontab" in str(exc.value)


def test_linux_install_writes_units_and_enables(tmp_path):
    run = FakeRun()
    linux.install("07:00", POSIX_SPACEY, run=run, config_home=tmp_path, systemd_ok=True)
    assert (tmp_path / "systemd/user/english-coach.service").exists()
    assert (tmp_path / "systemd/user/english-coach.timer").exists()
    assert ["systemctl", "--user", "enable", "--now", "english-coach.timer"] in run.calls


# --- Real OS (opt-in) --------------------------------------------------------

@pytest.mark.integration
@pytest.mark.skipif(sys.platform != "win32" or os.environ.get("EC_SCHEDULER_IT") != "1",
                    reason="real Task Scheduler; set EC_SCHEDULER_IT=1")
def test_windows_real_install_status_remove(monkeypatch):
    monkeypatch.setattr(windows, "TASK_NAME", "English Coach IT")
    windows.install("03:33", [sys.executable, "-c", "pass"])
    try:
        assert windows.status().installed
    finally:
        windows.remove()
    assert not windows.status().installed


def test_cli_schedule_saves_time_and_installs(tmp_path, monkeypatch):
    from english_coach import cli, scheduler
    from english_coach.config import AppPaths, Config, load_config, save_config
    paths = AppPaths(tmp_path / "cfg")
    save_config(paths, Config(vault_path=tmp_path / "v"))
    seen = {}
    monkeypatch.setattr(scheduler, "install", lambda t, log_dir, **k: seen.setdefault("t", t) or "ok")
    env = {"ENGLISH_COACH_CONFIG_DIR": str(paths.config_dir)}
    assert cli.main(["schedule", "--time", "6:30"], env=env) == 0
    assert seen["t"] == "06:30"
    assert load_config(paths, env={}).schedule_time == "06:30"
