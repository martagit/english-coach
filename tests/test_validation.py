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
    assert validate_timezone("Europe/Warsaw") == "Europe/Warsaw"


def test_validate_timezone_rejects_invalid():
    with pytest.raises(ValueError, match=r"unknown timezone 'Europe/Warsw'"):
        validate_timezone("Europe/Warsw")
