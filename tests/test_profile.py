from english_coach.profile import Profile


def test_learner_with_language():
    assert Profile("Polish", "software developer").learner() == "a Polish-native software developer"


def test_learner_uses_an_before_vowel():
    assert Profile("Italian", "data engineer").learner() == "an Italian-native data engineer"


def test_learner_without_language_and_blank_context():
    assert Profile("", "  ").learner() == "a software developer"
    assert Profile("", "architect").learner() == "an architect"


def test_interference_hint_only_with_language():
    assert "Spanish" in Profile("Spanish").interference_hint()
    assert Profile().interference_hint() == ""
