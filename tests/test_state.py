from datetime import datetime, timezone
from english_coach.state import read_watermark, write_watermark


def test_read_watermark_missing_returns_none(tmp_path):
    assert read_watermark(tmp_path) is None


def test_write_then_read_roundtrip(tmp_path):
    dt = datetime(2026, 7, 5, 22, 0, tzinfo=timezone.utc)
    write_watermark(tmp_path, dt)
    got = read_watermark(tmp_path)
    assert got == dt
    assert got.tzinfo is not None


def test_state_file_is_dot_coach_state(tmp_path):
    write_watermark(tmp_path, datetime(2026, 7, 5, tzinfo=timezone.utc))
    assert (tmp_path / ".coach-state.json").exists()
