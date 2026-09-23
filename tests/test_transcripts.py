import json
import os
import time
from datetime import datetime, timezone, date
from pathlib import Path

import pytest

from english_coach.transcripts import (
    ReadStats, TranscriptSource, default_projects_dir, prompt_from_entry, read_prompts,
)
from english_coach.window import compute_window

T0 = datetime(2026, 7, 5, 0, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 7, 6, 0, 0, tzinfo=timezone.utc)


def _entry(text="How should we name this?", ts="2026-07-05T09:00:00Z", **extra):
    e = {"type": "user", "uuid": extra.pop("uuid", f"u-{text}-{ts}"), "timestamp": ts,
         "cwd": "/home/me/proj", "sessionId": "s1", "isSidechain": False,
         "message": {"role": "user", "content": text}}
    e.update(extra)
    return e


def _write(dir_: Path, name: str, lines: list) -> Path:
    dir_.mkdir(parents=True, exist_ok=True)
    p = dir_ / name
    p.write_text("\n".join(l if isinstance(l, str) else json.dumps(l) for l in lines) + "\n",
                 encoding="utf-8")
    return p


def test_typed_string_prompt_is_kept():
    p = prompt_from_entry(_entry())
    assert p.text == "How should we name this?"
    assert p.timestamp_utc == datetime(2026, 7, 5, 9, tzinfo=timezone.utc)


def test_text_block_list_is_joined():
    e = _entry(message={"role": "user", "content": [
        {"type": "text", "text": "first"}, {"type": "image", "source": {}},
        {"type": "text", "text": "second"}]})
    assert prompt_from_entry(e).text == "first\nsecond"


@pytest.mark.parametrize("entry", [
    _entry(type="assistant"),
    _entry(isSidechain=True),
    _entry(isMeta=True),
    _entry(isCompactSummary=True),
    _entry(message={"role": "user", "content": [{"type": "tool_result", "content": "x"}]}),
    _entry(text="<command-name>/clear</command-name>"),
    _entry(text="<local-command-stdout>ok</local-command-stdout>"),
    _entry(text="<system-reminder>injected</system-reminder>"),
    _entry(text="   "),
    _entry(ts="not-a-date"),
    _entry(message="not a dict"),
])
def test_non_prompt_entries_are_rejected(entry):
    assert prompt_from_entry(entry) is None


def test_exclude_cwd_rejects_coach_own_calls(tmp_path):
    work = tmp_path / "workdir"
    e = _entry(cwd=str(work))
    assert prompt_from_entry(e, exclude_cwd=work) is None
    assert prompt_from_entry(e, exclude_cwd=tmp_path / "other") is not None


def test_exclude_cwd_matches_relative_exclude_against_absolute_cwd(tmp_path, monkeypatch):
    # Claude Code always writes an absolute cwd; a relative workdir (e.g. from
    # an unresolved ENGLISH_COACH_CONFIG_DIR) must still be recognized as the
    # same directory, or the coach would analyze its own CLI calls.
    monkeypatch.chdir(tmp_path)
    work = tmp_path / "workdir"
    work.mkdir()
    e = _entry(cwd=str(work))
    assert prompt_from_entry(e, exclude_cwd=Path("workdir")) is None


def test_read_prompts_filters_window_dedupes_and_sorts(tmp_path):
    proj = tmp_path / "projects"
    _write(proj / "C--a", "s1.jsonl", [
        _entry("later", "2026-07-05T15:00:00Z", uuid="a"),
        _entry("earlier", "2026-07-05T08:00:00Z", uuid="b"),
        _entry("out of window", "2026-07-04T08:00:00Z", uuid="c"),
    ])
    _write(proj / "C--b", "s2.jsonl", [_entry("later", "2026-07-05T15:00:00Z", uuid="a")])  # replayed
    out = read_prompts(proj, T0, T1)
    assert [p.text for p in out] == ["earlier", "later"]


def test_partial_last_line_is_skipped_and_counted(tmp_path):
    proj = tmp_path / "projects"
    _write(proj / "C--a", "s1.jsonl", [_entry("complete"), '{"type": "user", "mess'])
    stats = ReadStats()
    out = read_prompts(proj, T0, T1, stats=stats)
    assert [p.text for p in out] == ["complete"]
    assert stats.malformed == 1
    assert stats.files_scanned == 1
    assert stats.prompts == 1


def test_files_untouched_since_window_start_are_skipped(tmp_path):
    proj = tmp_path / "projects"
    old = _write(proj / "C--a", "old.jsonl", [_entry("in window but file is old")])
    past = T0.timestamp() - 3600
    os.utime(old, (past, past))
    stats = ReadStats()
    assert read_prompts(proj, T0, T1, stats=stats) == []
    assert stats.files_scanned == 0


def test_local_midnight_boundary_uses_window(tmp_path):
    # 2026-07-05 23:30 Warsaw == 21:30 UTC -> belongs to Sunday 07-05.
    # 2026-07-06 00:30 Warsaw == 22:30 UTC on 07-05 -> belongs to Monday (today), excluded.
    proj = tmp_path / "projects"
    _write(proj / "C--a", "s.jsonl", [
        _entry("sunday late", "2026-07-05T21:30:00Z", uuid="1"),
        _entry("monday early", "2026-07-05T22:30:00Z", uuid="2"),
    ])
    now = datetime(2026, 7, 6, 5, tzinfo=timezone.utc)
    w = compute_window(now, None, "Europe/Warsaw", backfill_days=1)
    assert w.days == [date(2026, 7, 5)]
    out = read_prompts(proj, w.start_utc, w.end_utc)
    assert [p.text for p in out] == ["sunday late"]


def test_missing_projects_dir_raises_with_hint(tmp_path):
    with pytest.raises(FileNotFoundError, match="doctor"):
        read_prompts(tmp_path / "nope", T0, T1)


def test_default_projects_dir_honors_claude_config_dir(tmp_path):
    assert default_projects_dir({"CLAUDE_CONFIG_DIR": str(tmp_path)}) == tmp_path / "projects"
    assert default_projects_dir({}) == Path.home() / ".claude" / "projects"


def test_transcript_source_records_stats(tmp_path):
    proj = tmp_path / "projects"
    _write(proj / "C--a", "s.jsonl", [_entry("hello there")])
    src = TranscriptSource(proj)
    assert [p.text for p in src.fetch_prompts(T0, T1)] == ["hello there"]
    assert src.last_stats.prompts == 1


def test_unreadable_file_does_not_abort_scan(tmp_path, monkeypatch):
    proj = tmp_path / "projects"
    good_file = _write(proj / "C--a", "good.jsonl", [_entry("from good file")])
    bad_file = _write(proj / "C--b", "bad.jsonl", [_entry("from bad file")])

    # Make bad_file raise PermissionError when opened
    original_open = Path.open
    def open_with_error(self, *args, **kwargs):
        if self == bad_file:
            raise PermissionError("Access denied")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_with_error)

    stats = ReadStats()
    out = read_prompts(proj, T0, T1, stats=stats)

    # Should still get prompt from good file, and malformed count should be 1 for the bad file
    assert [p.text for p in out] == ["from good file"]
    assert stats.malformed == 1
    assert stats.files_scanned == 2
