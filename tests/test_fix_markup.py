import re

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
     "every ~~day~~ **day,** one ticket ~~by~~ **per** component is created"),
    ("it seems it was executed for the PROD", "it seems it was executed against PROD",
     "it seems it was executed ~~for the~~ **against** PROD"),
    ("It's done.", "It's done!", "It's ~~done.~~ **done!**"),
    ("So we go", "we go", "~~So~~ we go"),
    ("before x", "after y", "~~before x~~ → **after y**"),
    ("Hello , world", "Hello, world", "~~Hello , world~~ → **Hello, world**"),
    ("same", "same", "same"),
    ("a*b ~x", "a*b ~y z", "~~a\\*b \\~x~~ → **a\\*b \\~y z**"),
    ("", "x", "**x**"),
    ("x", "", "~~x~~"),
]

ROUND_TRIP_ONLY = [
    ("generate a cron expression now+5mins, once a year. it utc",
     "generate a cron expression for now + 5 minutes, once a year, in UTC"),
    ("p → q s", "→ z q s t"),
    ("use **bold** here", "use **bold** there"),
    ("a well-known fix", "a well known fix"),
]


@pytest.mark.parametrize("before,after,rendered", CASES)
def test_render_fix(before, after, rendered):
    assert render_fix(before, after) == rendered


@pytest.mark.parametrize("before,after", [(b, a) for b, a, _ in CASES] + ROUND_TRIP_ONLY)
def test_parse_fix_round_trips_exactly(before, after):
    assert parse_fix(render_fix(before, after)) == (" ".join(before.split()), " ".join(after.split()))


@pytest.mark.parametrize("before,after", [(b, a) for b, a, _ in CASES] + ROUND_TRIP_ONLY)
def test_markers_always_touch_a_space_so_obsidian_renders_them(before, after):
    out = render_fix(before, after)
    # An opening/closing ~~ or ** glued to a non-space on its outer side doesn't render.
    assert not re.search(r"[^\s\\](?<!~~)(?<!\*\*)(?:~~|\*\*)(?=[^\s~*])", out.replace("~~ → **", "  "))


def test_parse_fix_of_plain_text_is_unchanged_pair():
    assert parse_fix("  just   text ") == ("just text", "just text")


def test_text_key_ignores_whitespace_and_escapes():
    assert text_key("now + 5\\*mins") == text_key("now+5*mins") == "now+5*mins"
