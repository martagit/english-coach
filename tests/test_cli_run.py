from datetime import date, datetime, timezone

from english_coach import cli
from english_coach.config import AppPaths, Config, save_config
from english_coach.models import Analysis, UserPrompt
from english_coach.runlog import read_last_run

NOW = datetime(2026, 7, 6, 5, tzinfo=timezone.utc)


class FakeSource:
    def __init__(self, prompts):
        from english_coach.transcripts import ReadStats
        self._prompts = prompts
        self.last_stats = ReadStats(prompts=len(prompts))

    def fetch_prompts(self, start_utc, end_utc):
        return self._prompts


class FakeAnalyzer:
    def analyze(self, prompts, phrasebook, known_patterns=()):
        return Analysis(wins=[], focus_pattern=None, recurring=[], new_phrases=[],
                        reused_phrases=[], snapshot=["ok"])


def _setup(tmp_path):
    paths = AppPaths(tmp_path / "cfg")
    cfg = Config(vault_path=tmp_path / "vault", timezone="Europe/Warsaw")
    save_config(paths, cfg)
    return paths, cfg


def _prompt():
    return UserPrompt("Why we need here the reference?", datetime(2026, 7, 5, 9, tzinfo=timezone.utc))


def test_execute_run_writes_note_log_and_last_run(tmp_path):
    paths, cfg = _setup(tmp_path)
    code, status = cli.execute_run(cfg, paths, env={}, now_utc=NOW, source=FakeSource([_prompt()]),
                                   analyzer=FakeAnalyzer(), runner=lambda p: '{"phrases": []}')
    assert (code, status) == (0, "wrote:2026-07-05")
    assert (cfg.vault_path / "Daily" / "2026-07-05.md").exists()
    assert "Wrote report" in paths.log_file.read_text(encoding="utf-8")
    assert read_last_run(paths.last_run_file)["status"] == "wrote:2026-07-05"
    assert not paths.lock_file.exists()


def test_execute_run_skips_when_locked(tmp_path):
    from english_coach.lock import run_lock
    paths, cfg = _setup(tmp_path)
    with run_lock(paths.lock_file):
        code, status = cli.execute_run(cfg, paths, env={}, now_utc=NOW,
                                       source=FakeSource([]), analyzer=FakeAnalyzer())
    assert (code, status) == (0, "locked")


def test_execute_run_failure_returns_1_and_keeps_watermark(tmp_path):
    from english_coach.state import read_watermark
    paths, cfg = _setup(tmp_path)

    class Boom(FakeAnalyzer):
        def analyze(self, *a, **k):
            raise RuntimeError("claude CLI failed")

    code, status = cli.execute_run(cfg, paths, env={}, now_utc=NOW,
                                   source=FakeSource([_prompt()]), analyzer=Boom())
    assert (code, status) == (1, "error")
    assert read_watermark(cfg.vault_path) is None
    assert "claude CLI failed" in paths.log_file.read_text(encoding="utf-8")


def test_main_run_without_config_explains_init(tmp_path, capsys):
    code = cli.main(["run"], env={"ENGLISH_COACH_CONFIG_DIR": str(tmp_path / "none")})
    assert code == 1
    assert "english-coach init" in capsys.readouterr().err


def test_main_rejects_partial_override(tmp_path):
    paths, _ = _setup(tmp_path)
    env = {"ENGLISH_COACH_CONFIG_DIR": str(paths.config_dir)}
    assert cli.main(["run", "--from", "2026-06-30"], env=env) == 1
