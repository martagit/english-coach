from english_coach.filtering import extract_user_prompts, is_noise, filter_prompts
from english_coach.models import UserPrompt
from datetime import timezone


def test_extract_pulls_user_content_with_utc_timestamp():
    traces = [
        {"input": {"role": "user", "content": "Why do we need the reference here?"},
         "timestamp": "2026-07-05T09:30:00Z"},
        {"input": {"role": "assistant", "content": "Because ..."},
         "timestamp": "2026-07-05T09:31:00Z"},
    ]
    out = extract_user_prompts(traces)
    assert len(out) == 1
    assert out[0].text == "Why do we need the reference here?"
    assert out[0].timestamp_utc.tzinfo == timezone.utc


def test_is_noise_task_notification():
    assert is_noise("<task-notification>build finished</task-notification>") is True


def test_is_noise_image_placeholder_only():
    assert is_noise("[Image #1]") is True
    assert is_noise("[Image #1] [Image #2]") is True


def test_is_noise_url_only():
    assert is_noise("https://example.com/thing?x=1") is True


def test_is_noise_trivial_ack():
    for ack in ["ok", "OK", "yes", "yep", "push", "1", "go ahead", "continue", " sure "]:
        assert is_noise(ack) is True


def test_is_noise_stacktrace():
    assert is_noise("Traceback (most recent call last):\n  File ...") is True


def test_substantive_prose_is_kept():
    assert is_noise("Can you explain why the article is needed in this sentence?") is False


def test_filter_prompts_drops_noise_keeps_prose():
    prompts = [
        UserPrompt("ok", None),
        UserPrompt("Why do we need the reference here?", None),
        UserPrompt("[Image #1]", None),
    ]
    kept = filter_prompts(prompts)
    assert [p.text for p in kept] == ["Why do we need the reference here?"]
