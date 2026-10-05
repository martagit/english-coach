import pytest

from english_coach.fix_markup import parse_fix, render_fix, text_key

CASES = [
    ("prepare a list ... that I can paste to team channel",
     "prepare a list ... that I can paste into the team channel",
     "prepare a list ... that I can paste ~~to~~ **into the** team channel"),
    ("Draft an explanation what happened", "Draft an explanation of what happened",
     "Draft an explanation **of** what happened"),
    ("every day one ticket by component is created",
     "every day, one ticket per component is created",
     "every day**,** one ticket ~~by~~ **per** component is created"),
    ("it seems it was executed for the PROD", "it seems it was executed against PROD",
     "it seems it was executed ~~for the~~ **against** PROD"),
    ("generate a cron expression now+5mins, once a year. it utc",
     "generate a cron expression for now + 5 minutes, once a year, in UTC",
     "generate a cron expression **for** now + ~~5mins~~ **5 minutes**, once a year~~. it utc~~**, in UTC**"),
    ("So we go", "we go", "~~So~~ we go"),
    ("before x", "after y", "~~before x~~ → **after y**"),
    ("same", "same", "same"),
    ("a*b ~x", "a*b ~y z", "a\\*b \\~~~x~~ **y z**"),
]


@pytest.mark.parametrize("before,after,rendered", CASES)
def test_render_fix(before, after, rendered):
    assert render_fix(before, after) == rendered


@pytest.mark.parametrize("before,after,rendered", CASES)
def test_parse_fix_round_trips_ignoring_whitespace(before, after, rendered):
    b, a = parse_fix(rendered)
    assert (text_key(b), text_key(a)) == (text_key(before), text_key(after))


def test_parse_fix_of_plain_text_is_unchanged_pair():
    assert parse_fix("  just   text ") == ("just text", "just text")


def test_parse_fix_returns_collapsed_spacing():
    assert parse_fix("Draft an explanation **of** what happened") == (
        "Draft an explanation what happened", "Draft an explanation of what happened")


def test_text_key_ignores_whitespace_and_escapes():
    assert text_key("now + 5\\*mins") == text_key("now+5*mins") == "now+5*mins"
