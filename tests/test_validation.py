import pytest

from english_coach.validation import normalize_time, validate_timezone


@pytest.mark.parametrize("raw, expected", [
    ("7:00", "07:00"),
    ("07:00", "07:00"),
    ("0:00", "00:00"),
    ("23:59", "23:59"),
    ("9:05", "09:05"),
])
def test_normalize_time_accepts_valid(raw, expected):
    assert normalize_time(raw) == expected


@pytest.mark.parametrize("raw", ["7am", "7", "25:00", "12:60", "-1:00", "", "12:5", "abc"])
def test_normalize_time_rejects_invalid(raw):
    with pytest.raises(ValueError, match="time must be HH:MM"):
        normalize_time(raw)


def test_validate_timezone_accepts_valid():
    assert validate_timezone("Europe/Berlin") == "Europe/Berlin"


def test_validate_timezone_rejects_invalid():
    with pytest.raises(ValueError, match=r"unknown timezone 'Europe/Berln'"):
        validate_timezone("Europe/Berln")


def test_vault_path_rejects_tilde_username_form():
    import pytest
    from english_coach.validation import validate_vault_path
    with pytest.raises(ValueError, match=r"~/english-coach-vault"):
        validate_vault_path("~english-coach-vault")


def test_vault_path_expands_home_and_creates_folder(tmp_path, monkeypatch):
    from pathlib import Path
    from english_coach.validation import validate_vault_path
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    v = validate_vault_path("~/my-vault")
    assert v == (tmp_path / "my-vault").resolve()
    assert v.is_dir()


def test_vault_path_that_cannot_be_created_is_rejected(tmp_path):
    import pytest
    from english_coach.validation import validate_vault_path
    blocker = tmp_path / "a-file"
    blocker.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="cannot create"):
        validate_vault_path(str(blocker / "vault"))
