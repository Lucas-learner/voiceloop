from pathlib import Path

from voiceloop.rename import is_default_named, sanitize_topic


def test_is_default_named_matches():
    assert is_default_named(Path("20260522 100732-CF347703.m4a"))
    assert is_default_named(Path("20240101 000000-1234ABCD.m4a"))


def test_is_default_named_no_match():
    assert not is_default_named(Path("my meeting.m4a"))
    assert not is_default_named(Path("20260522_MyTopic.m4a"))
    assert not is_default_named(Path("recording.mp3"))


def test_sanitize_topic():
    assert sanitize_topic("项目周会") == "项目周会"
    assert sanitize_topic("very long topic " * 10) != "very long topic " * 10
    assert "<" not in sanitize_topic("a<b")
