import os
import time
from datetime import datetime, timezone

from english_coach.config import AppPaths, Config, save_config
from english_coach.doctor import Check, format_checks, run_checks
from english_coach.runlog import write_last_run
from english_coach.scheduler import ScheduleStatus
from english_coach.transcripts import ReadStats


def _env(tmp_path):
    proj = tmp_path / "claude" / "projects" / "C--x"
    proj.mkdir(parents=True)
    (proj / "s.jsonl").write_text("{}\n", encoding="utf-8")
    return {"CLAUDE_CONFIG_DIR": str(tmp_path / "claude")}


def _by_name(checks):
    return {c.name: c for c in checks}


def test_all_green(tmp_path):
    paths = AppPaths(tmp_path / "cfg")
    (tmp_path / "vault").mkdir()
    save_config(paths, Config(vault_path=tmp_path / "vault"))
    write_last_run(paths.last_run_file, "wrote:2026-07-05", ReadStats(1, 2, 0, 1))
    checks = run_checks(paths, _env(tmp_path), which=lambda n: "/bin/claude",
                        sched_status=lambda: ScheduleStatus(True, "next 07:00"))
    assert all(c.ok for c in checks), format_checks(checks)
    assert set(_by_name(checks)) == {"claude CLI", "transcripts", "config", "vault",
                                     "schedule", "last run"}


def test_missing_config_and_claude_fail_with_hints(tmp_path):
    paths = AppPaths(tmp_path / "cfg")
    checks = _by_name(run_checks(paths, {"CLAUDE_CONFIG_DIR": str(tmp_path / "none")},
                                 which=lambda n: None,
                                 sched_status=lambda: ScheduleStatus(False, "not found")))
    assert not checks["claude CLI"].ok and "install" in checks["claude CLI"].detail.lower()
    assert not checks["transcripts"].ok
    assert not checks["config"].ok and "english-coach init" in checks["config"].detail
    assert not checks["schedule"].ok


def test_last_run_error_and_malformed_lines_are_reported(tmp_path):
    paths = AppPaths(tmp_path / "cfg")
    (tmp_path / "vault").mkdir()
    save_config(paths, Config(vault_path=tmp_path / "vault"))
    write_last_run(paths.last_run_file, "error", ReadStats(3, 100, 40, 0))
    last = _by_name(run_checks(paths, _env(tmp_path), which=lambda n: "c",
                               sched_status=lambda: ScheduleStatus(True, "")))["last run"]
    assert not last.ok
    assert "error" in last.detail and "40 malformed" in last.detail


def test_ping_failure_is_reported(tmp_path):
    paths = AppPaths(tmp_path / "cfg")

    def bad_ping():
        raise RuntimeError("not logged in")

    checks = _by_name(run_checks(paths, _env(tmp_path), ping=True, which=lambda n: "c",
                                 sched_status=lambda: ScheduleStatus(True, ""), claude_ping=bad_ping))
    assert not checks["claude CLI"].ok and "not logged in" in checks["claude CLI"].detail


def test_format_is_ascii():
    out = format_checks([Check("a", True, "fine"), Check("b", False, "broken")])
    assert out.isascii() and "[OK]" in out and "[FAIL]" in out
