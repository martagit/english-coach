import json
import os
import subprocess
import sys

import pytest

from english_coach import lock as lk


def test_lock_is_exclusive_and_released(tmp_path):
    p = tmp_path / "run.lock"
    with lk.run_lock(p):
        assert p.exists()
        with pytest.raises(lk.AlreadyRunning):
            with lk.run_lock(p):
                pass
    assert not p.exists()


def test_lock_released_on_exception(tmp_path):
    p = tmp_path / "run.lock"
    with pytest.raises(ValueError):
        with lk.run_lock(p):
            raise ValueError("boom")
    assert not p.exists()


def test_stale_by_age_is_taken_over(tmp_path):
    p = tmp_path / "run.lock"
    p.write_text(json.dumps({"pid": os.getpid(), "started": 1000.0}))
    with lk.run_lock(p, stale_after_s=60, now=lambda: 5000.0):
        assert json.loads(p.read_text())["started"] == 5000.0


def test_stale_by_dead_pid_is_taken_over(tmp_path, monkeypatch):
    p = tmp_path / "run.lock"
    p.write_text(json.dumps({"pid": 999999, "started": 5000.0}))
    monkeypatch.setattr(lk, "pid_alive", lambda pid: False)
    with lk.run_lock(p, now=lambda: 5001.0):
        pass


def test_corrupt_lock_is_stale(tmp_path):
    p = tmp_path / "run.lock"
    p.write_text("garbage")
    # Set mtime well in the past so it's considered stale
    os.utime(p, (1000.0, 1000.0))
    with lk.run_lock(p):
        pass


def test_fresh_unreadable_lock_is_not_stale(tmp_path):
    p = tmp_path / "run.lock"
    # Write an empty lock file (unreadable but fresh)
    p.write_text("")
    with pytest.raises(lk.AlreadyRunning):
        with lk.run_lock(p):
            pass


def test_pid_alive_for_self():
    assert lk.pid_alive(os.getpid()) is True


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only test")
def test_pid_alive_for_dead_process():
    # Start a process and wait for it to exit
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    # The process has exited; pid_alive should return False
    assert lk.pid_alive(p.pid) is False
