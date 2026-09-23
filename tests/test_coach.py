from datetime import datetime, timezone, date
from pathlib import Path
from english_coach.coach import run
from english_coach.config import Config
from english_coach.models import Analysis
from english_coach.state import read_watermark


def _cfg(tmp_path):
    return Config("http://localhost:3000", "pk", "sk", "ak", tmp_path, tmp_path / ".mcp.json")


class FakeLangfuse:
    def __init__(self, traces, reachable=True):
        self._traces = traces
        self._reachable = reachable

    def is_reachable(self):
        return self._reachable

    def fetch_traces(self, start_utc, end_utc):
        return self._traces


class FakeAnalyzer:
    def __init__(self, analysis):
        self._analysis = analysis
        self.called = False

    def analyze(self, prompts, phrasebook):
        self.called = True
        return self._analysis


def _empty_analysis():
    return Analysis(wins=[], focus_pattern=None, recurring=[], new_phrases=[],
                    reused_phrases=["park it"], snapshot=["ok"])


NOW = datetime(2026, 7, 6, 5, tzinfo=timezone.utc)  # Mon; yesterday = Sun 07-05


def test_run_returns_down_when_unreachable(tmp_path):
    status = run(_cfg(tmp_path), FakeLangfuse([], reachable=False), FakeAnalyzer(_empty_analysis()), now_utc=NOW)
    assert status == "down"


def test_run_writes_daily_and_advances_watermark(tmp_path):
    traces = [{"input": {"role": "user", "content": "Why we need here the reference?"},
               "timestamp": "2026-07-05T09:00:00Z"}]
    analyzer = FakeAnalyzer(_empty_analysis())
    status = run(_cfg(tmp_path), FakeLangfuse(traces), analyzer, now_utc=NOW)
    assert status == "wrote:2026-07-05"
    assert (tmp_path / "Daily" / "2026-07-05.md").exists()
    assert (tmp_path / "English Coaching.md").exists()
    assert analyzer.called is True
    assert read_watermark(tmp_path) is not None


def test_run_quiet_day_when_only_noise(tmp_path):
    traces = [{"input": {"role": "user", "content": "ok"}, "timestamp": "2026-07-05T09:00:00Z"}]
    analyzer = FakeAnalyzer(_empty_analysis())
    status = run(_cfg(tmp_path), FakeLangfuse(traces), analyzer, now_utc=NOW)
    assert status == "quiet"
    assert analyzer.called is False
    assert (tmp_path / "Daily" / "2026-07-05.md").exists()


def test_run_empty_window_is_noop(tmp_path):
    # Pre-seed watermark at end of yesterday so window is empty.
    from english_coach.state import write_watermark
    write_watermark(tmp_path, datetime(2026, 7, 5, 22, tzinfo=timezone.utc))
    status = run(_cfg(tmp_path), FakeLangfuse([]), FakeAnalyzer(_empty_analysis()), now_utc=NOW)
    assert status == "empty"


def test_main_rejects_partial_override():
    from english_coach.coach import main
    assert main(["--from", "2026-06-30"]) == 1
    assert main(["--to", "2026-07-02"]) == 1


def test_run_override_does_not_advance_watermark(tmp_path):
    from english_coach.state import write_watermark, read_watermark
    from datetime import date
    wm = datetime(2026, 7, 5, 22, tzinfo=timezone.utc)
    write_watermark(tmp_path, wm)
    traces = [{"input": {"role": "user", "content": "Why we need here the reference?"},
               "timestamp": "2026-06-30T09:00:00Z"}]
    run(_cfg(tmp_path), FakeLangfuse(traces), FakeAnalyzer(_empty_analysis()), now_utc=NOW,
        override_from=date(2026, 6, 30), override_to=date(2026, 6, 30))
    assert read_watermark(tmp_path) == wm  # unchanged by override reprocessing


def test_run_calls_curator_on_normal_day(tmp_path):
    traces = [{"input": {"role": "user", "content": "Why we need here the reference?"},
               "timestamp": "2026-07-05T09:00:00Z"}]
    calls = []
    status = run(_cfg(tmp_path), FakeLangfuse(traces), FakeAnalyzer(_empty_analysis()),
                 now_utc=NOW, curator=lambda: calls.append(1) or 1)
    assert status == "wrote:2026-07-05"
    assert calls == [1]


def test_run_calls_curator_on_quiet_day(tmp_path):
    traces = [{"input": {"role": "user", "content": "ok"}, "timestamp": "2026-07-05T09:00:00Z"}]
    calls = []
    status = run(_cfg(tmp_path), FakeLangfuse(traces), FakeAnalyzer(_empty_analysis()),
                 now_utc=NOW, curator=lambda: calls.append(1) or 0)
    assert status == "quiet"
    assert calls == [1]


def test_run_survives_curator_failure(tmp_path):
    traces = [{"input": {"role": "user", "content": "Why we need here the reference?"},
               "timestamp": "2026-07-05T09:00:00Z"}]

    def boom():
        raise RuntimeError("LLM down")

    status = run(_cfg(tmp_path), FakeLangfuse(traces), FakeAnalyzer(_empty_analysis()),
                 now_utc=NOW, curator=boom)
    assert status == "wrote:2026-07-05"  # run still succeeds
    assert (tmp_path / "Daily" / "2026-07-05.md").exists()
