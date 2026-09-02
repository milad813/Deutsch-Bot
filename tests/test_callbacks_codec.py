"""Tests for core/callbacks.py — the callback-data codec."""

import logging

from models import CallbackPrefix
from core.callbacks import (
    CALLBACK_DATA_MAX_BYTES,
    cb,
    cb_safe,
    parse,
    parse_int,
)


def test_cb_builds_prefix_data():
    assert cb(CallbackPrefix.QUIZ_COUNT, 10) == "quiz_count:10"
    assert cb(CallbackPrefix.LESSON_WORDS, "3_2") == "lesson_words_3_2"
    assert cb(CallbackPrefix.DAILY_LEARNING) == "daily_learning"


def test_cb_safe_returns_normal_data_for_short_suffix():
    """Short payloads must be returned unchanged (no noop fallback)."""
    assert cb_safe(CallbackPrefix.QUIZ_COUNT, 10) == "quiz_count:10"
    assert cb_safe(CallbackPrefix.LESSON_WORDS, "3_2") == "lesson_words_3_2"
    assert cb_safe(CallbackPrefix.DAILY_LEARNING) == "daily_learning"
    # Exactly at the limit must still pass through.
    pad = "x" * (CALLBACK_DATA_MAX_BYTES - len("quiz_count:"))
    assert cb_safe(CallbackPrefix.QUIZ_COUNT, pad) == "quiz_count:" + pad


def test_cb_safe_returns_noop_when_data_exceeds_64_bytes(caplog):
    """Over-long payloads must be coerced to ``"noop"`` and log a warning."""
    pad = "x" * (CALLBACK_DATA_MAX_BYTES - len("quiz_count:") + 1)
    with caplog.at_level(logging.WARNING, logger="core.callbacks"):
        result = cb_safe(CallbackPrefix.QUIZ_COUNT, pad)
    assert result == "noop"
    assert any("too long" in rec.message for rec in caplog.records)


def test_cb_safe_works_with_lesson_words_prefix():
    """Verify the LESSON_WORDS prefix used by the lesson-words pager."""
    assert cb_safe(CallbackPrefix.LESSON_WORDS, "7_0") == "lesson_words_7_0"
    assert cb_safe(CallbackPrefix.LESSON_WORDS, "7_1") == "lesson_words_7_1"
    # Suffix too long (e.g. someone handcrafting a 100-char suffix) → noop.
    long_suffix = "a" * 100
    assert cb_safe(CallbackPrefix.LESSON_WORDS, long_suffix) == "noop"


def test_cb_safe_works_with_quiz_count_prefix():
    """Verify the QUIZ_COUNT prefix used by the quiz-count picker."""
    assert cb_safe(CallbackPrefix.QUIZ_COUNT, 5) == "quiz_count:5"
    assert cb_safe(CallbackPrefix.QUIZ_COUNT, "all") == "quiz_count:all"
    assert cb_safe(CallbackPrefix.QUIZ_COUNT, 20) == "quiz_count:20"


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
