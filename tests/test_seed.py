from english_coach.seed import KNOWN_PATTERNS, TAUGHT_IDIOMS


def test_known_patterns_include_articles_and_questions():
    names = [name for name, _ in KNOWN_PATTERNS]
    assert "Articles" in names
    assert "Question formation" in names


def test_taught_idioms_seeded():
    assert "park it" in TAUGHT_IDIOMS
    assert "circle back" in TAUGHT_IDIOMS
    assert len(TAUGHT_IDIOMS) >= 10
