import sys
from datetime import datetime, timezone

from english_coach.runlog import read_last_run, run_log, write_last_run
from english_coach.transcripts import ReadStats


def test_run_log_tees_stdout_and_stderr(tmp_path, capsys):
    log = tmp_path / "logs" / "coach.log"
    with run_log(log):
        print("hello out")
        print("hello err", file=sys.stderr)
    text = log.read_text(encoding="utf-8")
    assert "hello out" in text and "hello err" in text and "=== run" in text
    captured = capsys.readouterr()
    assert "hello out" in captured.out


def test_run_log_rotates(tmp_path):
    log = tmp_path / "coach.log"
    log.write_text("x" * 600_000, encoding="utf-8")
    with run_log(log):
        print("fresh")
    assert (tmp_path / "coach.log.1").exists()
    assert "fresh" in log.read_text(encoding="utf-8")


def test_run_log_survives_missing_console(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)  # pythonw.exe has no console
    with run_log(tmp_path / "coach.log"):
        print("still logged")
    assert "still logged" in (tmp_path / "coach.log").read_text(encoding="utf-8")


def test_last_run_round_trip(tmp_path):
    p = tmp_path / "last_run.json"
    assert read_last_run(p) is None
    write_last_run(p, "wrote:2026-07-05", ReadStats(3, 40, 1, 12),
                   now=datetime(2026, 7, 6, 5, tzinfo=timezone.utc))
    data = read_last_run(p)
    assert data["status"] == "wrote:2026-07-05"
    assert data["stats"]["malformed"] == 1
    assert data["finished_at"].startswith("2026-07-06T05:00")
