import json
from datetime import datetime, timezone
from pathlib import Path

from english_coach.config import AppPaths, load_config
from english_coach.init_wizard import Prompter, init
from english_coach.profile import Profile

NOW = datetime(2026, 7, 6, 5, tzinfo=timezone.utc)


def _env(tmp_path, prompts=("How should we name this?",)):
    proj = tmp_path / "claude" / "projects" / "C--x"
    proj.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"type": "user", "uuid": f"u{i}", "timestamp": "2026-07-05T09:00:00Z",
                         "cwd": "/p", "message": {"role": "user", "content": t}})
             for i, t in enumerate(prompts)]
    (proj / "s.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"CLAUDE_CONFIG_DIR": str(tmp_path / "claude")}


class Recorder:
    def __init__(self):
        self.schedule_calls, self.run_calls = [], []

    def schedule(self, time_hhmm, log_dir):
        self.schedule_calls.append(time_hhmm)
        return "scheduled"

    def do_run(self, config, paths, env, backfill_days):
        self.run_calls.append(backfill_days)
        return 0, "wrote:x"


def _answers(tmp_path, **over):
    a = {"vault": str(tmp_path / "vault"), "native_language": "Polish",
         "context": "software developer", "timezone": "Europe/Warsaw", "backend": "cli",
         "backfill_days": "7", "run_backfill": True, "time": "07:00", "schedule": True}
    a.update(over)
    return a


def test_init_happy_path(tmp_path):
    paths, rec = AppPaths(tmp_path / "cfg"), Recorder()
    code = init(paths, _env(tmp_path), Prompter(_answers(tmp_path)), check_claude=lambda: None,
                schedule=rec.schedule, do_run=rec.do_run, now_utc=NOW)
    assert code == 0
    cfg = load_config(paths, env={})
    assert cfg.vault_path == tmp_path / "vault"
    assert cfg.profile == Profile("Polish", "software developer")
    assert cfg.timezone == "Europe/Warsaw"
    assert (tmp_path / "vault" / ".obsidian" / "plugins" / "dataview" / "main.js").exists()
    assert rec.run_calls == [7] and rec.schedule_calls == ["07:00"]


def test_init_stops_when_claude_missing(tmp_path):
    paths = AppPaths(tmp_path / "cfg")

    def missing():
        raise RuntimeError("claude not found")

    lines = []
    code = init(paths, _env(tmp_path), Prompter(_answers(tmp_path), out=lines.append),
                check_claude=missing, schedule=Recorder().schedule, do_run=Recorder().do_run)
    assert code == 1
    assert not paths.config_file.exists()
    assert any("claude not found" in l for l in lines)


def test_init_stops_when_no_transcripts(tmp_path):
    paths = AppPaths(tmp_path / "cfg")
    code = init(paths, {"CLAUDE_CONFIG_DIR": str(tmp_path / "none")}, Prompter(_answers(tmp_path)),
                check_claude=lambda: None, schedule=Recorder().schedule, do_run=Recorder().do_run)
    assert code == 1


def test_init_rerun_keeps_existing_and_uses_previous_answers(tmp_path):
    paths, rec = AppPaths(tmp_path / "cfg"), Recorder()
    env = _env(tmp_path)
    init(paths, env, Prompter(_answers(tmp_path, native_language="German", time="06:15")),
         check_claude=lambda: None, schedule=rec.schedule, do_run=rec.do_run, now_utc=NOW)
    note = tmp_path / "vault" / "Phrases" / "park it.md"
    note.write_text("my note", encoding="utf-8")
    # Second run: accept every default -> must reuse previous answers, not factory defaults.
    init(paths, env, Prompter(assume_yes=True), check_claude=lambda: None,
         schedule=rec.schedule, do_run=rec.do_run, now_utc=NOW)
    cfg = load_config(paths, env={})
    assert cfg.profile.native_language == "German"
    assert cfg.schedule_time == "06:15"
    assert note.read_text(encoding="utf-8") == "my note"


def test_init_api_backend_saves_key(tmp_path):
    paths = AppPaths(tmp_path / "cfg")
    init(paths, _env(tmp_path), Prompter(_answers(tmp_path, backend="api", api_key="sk-ant-x")),
         check_claude=lambda: None, schedule=Recorder().schedule, do_run=Recorder().do_run,
         now_utc=NOW)
    assert load_config(paths, env={}).anthropic_api_key == "sk-ant-x"


def test_init_can_skip_backfill_and_schedule(tmp_path):
    paths, rec = AppPaths(tmp_path / "cfg"), Recorder()
    init(paths, _env(tmp_path), Prompter(_answers(tmp_path, run_backfill=False, schedule=False)),
         check_claude=lambda: None, schedule=rec.schedule, do_run=rec.do_run, now_utc=NOW)
    assert rec.run_calls == [] and rec.schedule_calls == []


def test_prompter_uses_input_and_default():
    replies = iter(["", "Spanish"])
    p = Prompter(input_fn=lambda q: next(replies), out=lambda s: None)
    assert p.ask("a", "Vault?", "/v") == "/v"
    assert p.ask("b", "Language?", "") == "Spanish"
