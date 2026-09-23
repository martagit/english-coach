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


def test_last_run_with_foreign_json_shape(tmp_path):
    paths = AppPaths(tmp_path / "cfg")
    (tmp_path / "vault").mkdir()
    save_config(paths, Config(vault_path=tmp_path / "vault"))
    paths.last_run_file.parent.mkdir(parents=True, exist_ok=True)
    paths.last_run_file.write_text("{\"unexpected\": \"shape\"}", encoding="utf-8")
    last = _by_name(run_checks(paths, _env(tmp_path), which=lambda n: "c",
                               sched_status=lambda: ScheduleStatus(True, "")))["last run"]
    assert not last.ok and "malformed" in last.detail


def test_last_run_with_naive_timestamp(tmp_path):
    paths = AppPaths(tmp_path / "cfg")
    (tmp_path / "vault").mkdir()
    save_config(paths, Config(vault_path=tmp_path / "vault"))
    naive_time = datetime(2026, 7, 5, 10, 0, 0)  # naive datetime
    write_last_run(paths.last_run_file, "wrote:2026-07-05", ReadStats(1, 2, 0, 1),
                   now=naive_time)
    # Pass a now that's close to the naive timestamp so it's not stale
    checks = _by_name(run_checks(paths, _env(tmp_path), which=lambda n: "c",
                                 sched_status=lambda: ScheduleStatus(True, ""),
                                 now=datetime(2026, 7, 5, 10, 30, 0, tzinfo=timezone.utc)))
    assert checks["last run"].ok


def test_scheduler_exception_is_handled(tmp_path):
    paths = AppPaths(tmp_path / "cfg")
    (tmp_path / "vault").mkdir()
    save_config(paths, Config(vault_path=tmp_path / "vault"))
    write_last_run(paths.last_run_file, "wrote:2026-07-05", ReadStats(1, 2, 0, 1))

    def bad_sched_status():
        raise FileNotFoundError("schtasks not found")

    checks = _by_name(run_checks(paths, _env(tmp_path), which=lambda n: "c",
                                 sched_status=bad_sched_status))
    assert not checks["schedule"].ok and "Could not query" in checks["schedule"].detail


def test_many_unrecognized_entries_warn_about_format_change(tmp_path):
    paths = AppPaths(tmp_path / "cfg")
    (tmp_path / "vault").mkdir()
    save_config(paths, Config(vault_path=tmp_path / "vault"))
    # 5 malformed + 20 unrecognized of 100 lines = 25% -> format-change warning
    write_last_run(paths.last_run_file, "quiet",
                   ReadStats(files_scanned=3, lines_read=100, malformed=5, prompts=0,
                             unrecognized=20))
    last = _by_name(run_checks(paths, _env(tmp_path), which=lambda n: "c",
                               sched_status=lambda: ScheduleStatus(True, "")))["last run"]
    assert not last.ok
    assert "20 unrecognized" in last.detail
    assert "format may have changed" in last.detail


def test_schedule_is_informational_when_scheduler_unavailable(tmp_path, monkeypatch):
    from english_coach.scheduler import linux
    monkeypatch.setattr(linux.shutil, "which", lambda name: None)
    st = linux.status()
    assert st.unavailable and not st.installed
    paths = AppPaths(tmp_path / "cfg")
    sched = _by_name(run_checks(paths, _env(tmp_path), which=lambda n: "c",
                                sched_status=lambda: st))["schedule"]
    assert sched.ok
    assert sched.detail == ("systemd not available - if you use the crontab fallback, "
                            "check `crontab -l`")


def test_default_ping_creates_workdir_first(tmp_path, monkeypatch):
    from english_coach import doctor
    paths = AppPaths(tmp_path / "cfg")
    seen = {}

    def fake_cli(prompt, cwd=None, timeout=None, **kw):
        seen["cwd_exists"] = cwd.is_dir()

    monkeypatch.setattr(doctor, "run_claude_cli", fake_cli)
    checks = _by_name(run_checks(paths, _env(tmp_path), ping=True, which=lambda n: "c",
                                 sched_status=lambda: ScheduleStatus(True, "")))
    assert checks["claude CLI"].ok
    assert seen["cwd_exists"] is True


def test_detail_strings_have_no_em_dashes(tmp_path):
    paths = AppPaths(tmp_path / "cfg")
    checks = run_checks(paths, {"CLAUDE_CONFIG_DIR": str(tmp_path / "none")}, which=lambda n: None,
                        sched_status=lambda: ScheduleStatus(False, "x"))
    assert "?" not in format_checks(checks)
