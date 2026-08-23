"""Validation tests for story-generation helpers in handlers/story/core.py.

Covers:
- _format_story_text: markdown cleanup + inflection-aware bolding
- _validate_story_naturalness: length gate + target-word coverage
- _select_smart_words: empty candidate-pool edge cases
"""

import pytest

import services
from handlers.story.core import (
    MIN_STORY_WORDS,
    STORY_WORD_TYPES,
    _format_story_text,
    _select_smart_words,
    _validate_story_naturalness,
)


def _w(german, **extra):
    return {"german": german, **extra}


# ─── _format_story_text ──────────────────────────────────────────


def test_format_strips_markdown_and_bolds_target():
    words = [_w("Haus")]
    out = _format_story_text("Das **Haus** ist groß.", words)

    assert "**" not in out
    assert out == "Das <b>Haus</b> ist groß."


def test_format_bold_inflected_adjective_schlechten():
    # "schlecht" + declension suffix must match as one unit.
    words = [_w("schlecht")]
    out = _format_story_text("Er hatte einen schlechten Tag.", words)

    assert "einen <b>schlechten</b> Tag" in out
    assert out.count("<b>") == 1


def test_format_is_case_insensitive_but_preserves_source_casing():
    words = [_w("haus")]
    out = _format_story_text("Das HAUS ist alt. Im Haus wohnt Anna.", words)

    assert "<b>HAUS</b>" in out
    assert "<b>Haus</b>" in out


def test_format_verb_prefix_inflection_not_matched():
    # Only stem-suffix inflections match; ge- prefixed participles don't.
    words = [_w("sehen")]
    out = _format_story_text("Ich will sehen. Ich habe es gesehen.", words)

    assert "<b>sehen</b>" in out
    assert "gesehen" in out and "<b>gesehen</b>" not in out


def test_format_umlaut_plural_not_matched():
    # Characterization: stem-vowel change (Haus → Häuser) is not bolded.
    words = [_w("Haus")]
    out = _format_story_text("Viele Häuser sind alt. Das Haus ist neu.", words)

    assert "<b>Haus</b>" in out
    assert "<b>Häuser</b>" not in out
    assert "Häuser" in out  # left untouched


def test_format_multiple_targets_and_occurrences():
    words = [_w("Hund"), _w("schlafen")]
    out = _format_story_text(
        "Der Hund ist müde. Der Hund will schlafen. Wir schlafen früh.",
        words,
    )

    assert out.count("<b>Hund</b>") == 2
    assert out.count("<b>schlafen</b>") == 2  # infinitive + conjugated form


def test_format_skips_empty_german_entries():
    words = [{"german": ""}, {"article": "das"}]
    text = "Kein Ziel hier."
    assert _format_story_text(text, words) == text


# ─── _validate_story_naturalness ─────────────────────────────────


def _long_text(repeats=8):
    """Filler German text comfortably above the 50-token gate."""
    return "Ein kleiner Hund läuft schnell durch den Park und bellt. " * repeats


async def test_validate_too_short_story_is_invalid_even_with_targets():
    ok = await _validate_story_naturalness(
        "Das Haus ist schön.", [_w("Haus"), _w("ist"), _w("schön")], level="A1"
    )
    assert ok is False


async def test_validate_long_story_with_fewer_than_min_targets_is_invalid():
    ok = await _validate_story_naturalness(
        _long_text(), [_w("Hund"), _w("läuft")], level="A1"
    )
    assert ok is False  # 2 targets < MIN_STORY_WORDS (3)


async def test_validate_long_story_with_exactly_min_targets_is_valid():
    ok = await _validate_story_naturalness(
        _long_text(), [_w("hund"), _w("läuft"), _w("park")], level="A1"
    )
    assert ok is True


async def test_validate_empty_story_is_invalid():
    ok = await _validate_story_naturalness(
        "", [_w("Haus"), _w("ist"), _w("schön")], level="A1"
    )
    assert ok is False


async def test_validate_counts_compound_substrings_as_coverage():
    # Characterization: matching is plain substring → compounds count.
    text = _long_text() + " Er kaufte ein Haustürschloss."
    ok = await _validate_story_naturalness(
        text, [_w("Haus"), _w("Schloss"), _w("Tür")], level="B2"
    )
    assert ok is True


async def test_validate_level_argument_does_not_change_gate():
    words = [_w("hund"), _w("läuft"), _w("schnell")]
    text = _long_text()

    assert await _validate_story_naturalness(text, words, "A1") is True
    assert await _validate_story_naturalness(text, words, "B2") is True


# ─── _select_smart_words: empty candidate pool ───────────────────


def _patch_pool(monkeypatch, rows):
    monkeypatch.setattr(
        services.db.words, "get_by_lesson_full", lambda lesson_id: rows
    )
    monkeypatch.setattr(
        services.db.words, "get_stats_full", lambda user_id, wid: None
    )


async def test_select_smart_words_empty_lesson_returns_empty(monkeypatch):
    _patch_pool(monkeypatch, [])

    got = await _select_smart_words(user_id=1, lesson_id=5, exclude_ids=set())
    assert got == []


async def test_select_smart_words_no_eligible_types_returns_empty(monkeypatch):
    # Words exist but none is Noun/Verb/Adjective → story pool stays empty.
    rows = [
        {"id": 1, "german": "heute", "word_type": "Adverb"},
        {"id": 2, "german": "weil", "word_type": "Conjunction"},
        {"id": 3, "german": "gern", "word_type": "Adverb"},
    ]
    _patch_pool(monkeypatch, rows)

    got = await _select_smart_words(user_id=1, lesson_id=5, exclude_ids=set())
    assert got == []


async def test_select_smart_words_happy_path_fills_to_minimum(monkeypatch):
    rows = [
        {"id": i, "german": f"Wort{i}", "article": "das", "word_type": "Noun"}
        for i in range(1, 5)
    ]
    _patch_pool(monkeypatch, rows)

    got = await _select_smart_words(user_id=1, lesson_id=5, exclude_ids=set())

    assert got, "with eligible nouns the candidate pool must not be empty"
    assert all(w["word_type"] in STORY_WORD_TYPES for w in got)
    assert len(got) >= MIN_STORY_WORDS