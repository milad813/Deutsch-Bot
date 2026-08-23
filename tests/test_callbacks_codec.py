"""Tests for core/callbacks.py — the callback-data codec."""

from models import CallbackPrefix
from core.callbacks import cb, parse, parse_int


def test_cb_builds_prefix_data():
    assert cb(CallbackPrefix.QUIZ_COUNT, 10) == "quiz_count:10"
    assert cb(CallbackPrefix.LESSON_WORDS, "3_2") == "lesson_words_3_2"
    assert cb(CallbackPrefix.DAILY_LEARNING) == "daily_learning"


def test_parse_round_trip_for_every_member():
    for member in CallbackPrefix:
        parsed = parse(cb(member, "x"))
        assert parsed is not None, member.name
        prefix, suffix = parsed
        assert prefix is member
        assert suffix == "x"


def test_parse_longest_prefix_wins():
    """lesson_words_ must not be swallowed by lesson_ (and vice-versa)."""
    prefix, suffix = parse("lesson_words_7_1")
    assert prefix is CallbackPrefix.LESSON_WORDS
    assert suffix == "7_1"

    prefix, suffix = parse("lesson_7")
    assert prefix is CallbackPrefix.LESSON
    assert suffix == "7"

    prefix, suffix = parse("story_listen_only:5")
    assert prefix is CallbackPrefix.STORY_LISTEN_ONLY


def test_parse_unknown_returns_none():
    assert parse("back_to_main_menu") is None
    assert parse("") is None


def test_parse_int():
    assert parse_int("quiz_book:12") == 12
    assert parse_int("quiz_count:all") is None
    assert parse_int("noop") is None
