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
    def analyze(self, prompts, phrasebook, known_patterns=(), constructions=()):
        return Analysis(wins=[], focus_pattern=None, recurring=[], new_phrases=[],
                        reused_phrases=[], snapshot=["ok"])


def _setup(tmp_path):
    paths = AppPaths(tmp_path / "cfg")
    cfg = Config(vault_path=tmp_path / "vault", timezone="Europe/Berlin")
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


def test_execute_run_setup_failure_is_logged_and_recorded(tmp_path, monkeypatch):
    # analyzer/source/runner construction (make_runner, ClaudeAnalyzer, TranscriptSource)
    # must happen inside run_log()/try so a failure there still reaches coach.log
    # and last_run.json instead of crashing a scheduled run silently.
    paths = AppPaths(tmp_path / "cfg")
    cfg = Config(vault_path=tmp_path / "vault", timezone="Europe/Berlin", backend="api")
    save_config(paths, cfg)

    def boom(*a, **k):
        raise RuntimeError("bad api key")

    monkeypatch.setattr(cli, "ClaudeAnalyzer", boom)
    code, status = cli.execute_run(cfg, paths, env={}, now_utc=NOW)
    assert (code, status) == (1, "error")
    assert "bad api key" in paths.log_file.read_text(encoding="utf-8")
    assert read_last_run(paths.last_run_file)["status"] == "error"


def test_main_run_config_dir_flag_reads_that_config(tmp_path, monkeypatch):
    paths, cfg = _setup(tmp_path)
    seen = {}

    def fake_execute_run(config, p, env, **kw):
        seen.update(config=config, paths=p, env=env)
        return 0, "empty"

    monkeypatch.setattr(cli, "execute_run", fake_execute_run)
    env = {"ENGLISH_COACH_CONFIG_DIR": str(tmp_path / "elsewhere")}
    code = cli.main(["run", "--config-dir", str(paths.config_dir),
                     "--claude-config-dir", str(tmp_path / "claude")], env=env)
    assert code == 0
    assert seen["config"].vault_path == cfg.vault_path
    assert seen["paths"].config_dir == paths.config_dir.resolve()
    assert seen["env"]["CLAUDE_CONFIG_DIR"] == str((tmp_path / "claude").resolve())


def test_main_run_config_error_is_logged(tmp_path, capsys):
    paths = AppPaths(tmp_path / "cfg")
    paths.config_dir.mkdir(parents=True)
    paths.config_file.write_text("vault_path = [", encoding="utf-8")  # invalid TOML
    code = cli.main(["run", "--config-dir", str(paths.config_dir)], env={})
    assert code == 1
    assert "Config error" in capsys.readouterr().err
    assert "Config error" in paths.log_file.read_text(encoding="utf-8")


def test_empty_run_keeps_previous_stats(tmp_path):
    from english_coach.runlog import write_last_run
    from english_coach.state import write_watermark
    from english_coach.transcripts import ReadStats
    paths, cfg = _setup(tmp_path)
    write_last_run(paths.last_run_file, "wrote:2026-07-04",
                   ReadStats(files_scanned=2, lines_read=50, malformed=1, prompts=4, unrecognized=3))
    write_watermark(cfg.vault_path, datetime(2026, 7, 5, 22, tzinfo=timezone.utc))  # nothing new
    code, status = cli.execute_run(cfg, paths, env={}, now_utc=NOW, source=FakeSource([]),
                                   analyzer=FakeAnalyzer())
    assert (code, status) == (0, "empty")
    last = read_last_run(paths.last_run_file)
    assert last["status"] == "empty"
    assert last["stats"] == {"files_scanned": 2, "lines_read": 50, "malformed": 1,
                             "prompts": 4, "unrecognized": 3}


def test_run_logs_transcript_stats_line(tmp_path):
    from english_coach.transcripts import ReadStats
    paths, cfg = _setup(tmp_path)
    src = FakeSource([_prompt()])
    src.last_stats = ReadStats(files_scanned=2, lines_read=30, malformed=1, prompts=1, unrecognized=4)
    cli.execute_run(cfg, paths, env={}, now_utc=NOW, source=src, analyzer=FakeAnalyzer(),
                    runner=lambda p: '{"phrases": []}')
    assert ("Transcripts: 2 files, 30 lines, 1 prompts, 1 malformed, 4 unrecognized."
            in paths.log_file.read_text(encoding="utf-8"))


def test_enrich_constructions_flag_only_enriches_constructions(tmp_path, monkeypatch):
    paths, cfg = _setup(tmp_path)
    seen = []
    monkeypatch.setattr(cli.vault, "enrich_phrase_notes", lambda *a, **k: seen.append("phrases") or 0)
    monkeypatch.setattr(cli.vault, "enrich_pattern_notes", lambda *a, **k: seen.append("patterns") or 0)
    monkeypatch.setattr(cli.constructions, "enrich_construction_notes",
                        lambda *a, **k: seen.append("constructions") or 0)
    monkeypatch.setattr(cli, "make_runner", lambda config, p: (lambda prompt: "{}"))
    assert cli.main(["enrich", "--constructions"], env={"ENGLISH_COACH_CONFIG_DIR": str(paths.config_dir)}) == 0
    assert seen == ["constructions"]
    seen.clear()
    assert cli.main(["enrich"], env={"ENGLISH_COACH_CONFIG_DIR": str(paths.config_dir)}) == 0
    assert seen == ["phrases", "patterns", "constructions"]
