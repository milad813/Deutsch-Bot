"""Verify that ``context.user_data`` stays JSON-serializable.

Phase-1, item 3: remove fragile Python-only objects (deque, set,
dataclass instances) from session state so a future migration away
from ``PicklePersistence`` to ``JSONPersistence`` is possible.

These tests initialize each major session (flashcard, LTR, quiz) on a
fake Telegram context and then assert that the resulting
``context.user_data`` can be serialized with ``json.dumps`` (no
``default=str`` coercion needed, but provided as a safety net).
"""

import json

from handlers.learning.flashcard_session import FlashcardSessionManager
from handlers.learning.ltr_session import LTRSessionManager
from handlers.quiz_handlers import _init_quiz_session
from models import Word


class FakeContext:
    """Bare-minimum stand-in for a python-telegram-bot context."""

    def __init__(self):
        self.user_data = {}


def _make_word(word_id: int) -> Word:
    """Build a minimal Word stub for LTR/flashcard initialization."""
    return Word(
        id=word_id,
        german=f"wort{word_id}",
        persian=f"کلمه{word_id}",
        article="",
        word_type="Noun",
    )


def _assert_json_safe(user_data: dict) -> None:
    """Serialize ``user_data`` and confirm the round-trip is lossless.

    ``default=str`` is passed defensively so that any future
    non-strictly-JSON value (e.g. ``datetime``) does not mask a real
    bug; the strict ``json.JSONEncoder().encode`` will still be tried
    implicitly by ``json.dumps`` only when no fallback is needed.
    """
    try:
        payload = json.dumps(user_data, default=str)
    except TypeError as exc:
        raise AssertionError(
            f"context.user_data contains a non-JSON-serializable "
            f"value: {exc!r}\nKeys: {sorted(user_data.keys())}"
        ) from exc

    # The payload must round-trip cleanly back to a dict.
    decoded = json.loads(payload)
    assert isinstance(decoded, dict)
    assert set(decoded.keys()) == set(user_data.keys()), (
        "json round-trip lost keys: "
        f"missing={set(user_data.keys()) - set(decoded.keys())}, "
        f"extra={set(decoded.keys()) - set(user_data.keys())}"
    )


# ─── Flashcard session ──────────────────────────────────────────────


def test_flashcard_init_creates_json_safe_user_data():
    """``FlashcardSessionManager.initialize`` must use lists, not sets."""
    context = FakeContext()
    session = FlashcardSessionManager(context)

    session.initialize(
        lesson_id=1,
        only_new=False,
        only_due=True,
        hard_only=False,
    )

    # Type assertions — guard against future regressions to set/deque.
    assert isinstance(context.user_data["flashcard_skipped_ids"], list)

    # Functional behaviour preserved: the skipped-IDs list is empty
    # and uniqueness is enforced on add.
    session.add_to_skipped(101)
    session.add_to_skipped(101)  # idempotent
    session.add_to_skipped(202)
    assert context.user_data["flashcard_skipped_ids"] == [101, 202]

    # Queue helpers store/return plain lists.
    session.set_queue([_make_word(1), _make_word(2), _make_word(3)])
    assert isinstance(context.user_data["flashcard_queue"], list)
    assert context.user_data["flashcard_queue"] == [2, 3]
    assert session.pop_queue() == 2
    assert context.user_data["flashcard_queue"] == [3]
    assert session.get_remaining_count() == 2  # one current + 1 queued

    _assert_json_safe(context.user_data)


def test_flashcard_queue_preserves_requeue_on_again_behavior():
    """Re-queuing on 'Again' must use ``list.insert(0, ...)`` semantics.

    Mirrors the requeue block in ``handle_rate_card``: the just-rated
    word is inserted at the **front** of the queue (not in the middle)
    so it appears as the very next card.  In the live flow the rated
    word is not yet in the queue, so this test starts with a queue
    that does not contain the requeued id.
    """
    context = FakeContext()
    session = FlashcardSessionManager(context)

    session.initialize(lesson_id=None)
    # Word 1 is the current card; the queue holds the rest of the deck.
    session.set_queue([_make_word(1), _make_word(2), _make_word(3)])
    assert context.user_data["flashcard_queue"] == [2, 3]

    # Simulate pressing "Again" on word 1: it gets re-queued at the front.
    queue = context.user_data["flashcard_queue"]
    queue.insert(0, 1)

    assert context.user_data["flashcard_queue"] == [1, 2, 3]
    assert session.pop_queue() == 1  # the requeued word comes first
    assert session.pop_queue() == 2

    _assert_json_safe(context.user_data)


# ─── LTR session ─────────────────────────────────────────────────────


def test_ltr_init_creates_json_safe_user_data():
    """``LTRSessionManager.initialize`` writes lists/dicts only."""
    context = FakeContext()
    ltr = LTRSessionManager(context)
    words = [_make_word(1), _make_word(2), _make_word(3)]

    assert ltr.initialize(user_id=42, lesson_id=None, weak_words=[], new_words=words)

    # Every state slot must be a primitive container.
    assert isinstance(context.user_data["ltr_words"], list)
    assert isinstance(context.user_data["ltr_delayed_tasks"], list)
    assert isinstance(context.user_data["ltr_word_results"], dict)
    assert isinstance(context.user_data["ltr_words_learned"], list)
    assert isinstance(context.user_data["ltr_words_tested"], list)
    assert isinstance(context.user_data["ltr_words_passed"], list)
    assert isinstance(context.user_data["ltr_words_failed"], list)

    _assert_json_safe(context.user_data)


def test_ltr_success_types_uses_lists_not_sets():
    """Recording a successful test must store a list, not a set."""
    context = FakeContext()
    ltr = LTRSessionManager(context)
    words = [_make_word(1)]
    ltr.initialize(user_id=42, lesson_id=None, weak_words=[], new_words=words)

    # Two distinct correct question types must be enough to pass.
    ltr.record_test_result(1, True, "meaning")
    ltr.record_test_result(1, True, "reverse")

    success_types = context.user_data["ltr_word_success_types"]
    assert isinstance(success_types, dict)
    assert isinstance(success_types[1], list)
    # Uniqueness is preserved even if the same type is recorded twice.
    ltr.record_test_result(1, True, "meaning")
    assert success_types[1].count("meaning") == 1
    assert set(success_types[1]) == {"meaning", "reverse"}

    assert 1 in context.user_data["ltr_words_passed"]

    _assert_json_safe(context.user_data)


# ─── Quiz session ────────────────────────────────────────────────────


def test_quiz_init_creates_json_safe_user_data():
    """``_init_quiz_session`` must store a plain dict, not a dataclass."""
    context = FakeContext()

    _init_quiz_session(
        context,
        quiz_type="meaning",
        total_questions=5,
        source_filter="due",
        lesson_id=42,
    )

    session = context.user_data["quiz_session_obj"]
    assert isinstance(session, dict), (
        f"quiz_session_obj must be a plain dict, got {type(session).__name__}"
    )

    # All eight documented fields must be present with the right shape.
    assert session["quiz_type"] == "meaning"
    assert session["total_questions"] == 5
    assert session["current_index"] == 0
    assert session["correct_count"] == 0
    assert session["wrong_count"] == 0
    assert session["question_ids"] == []
    assert session["source_filter"] == "due"
    assert session["lesson_id"] == 42

    # And the whole user_data must round-trip through json.dumps.
    _assert_json_safe(context.user_data)


def test_quiz_init_with_optional_fields_is_json_safe():
    """Optional fields default to None and remain JSON-safe."""
    context = FakeContext()

    _init_quiz_session(context, "reverse", 10)

    session = context.user_data["quiz_session_obj"]
    assert session["source_filter"] is None
    assert session["lesson_id"] is None

    _assert_json_safe(context.user_data)


# ─── End-to-end JSON round-trip across a realistic combined session ──


def test_combined_session_state_is_json_safe():
    """All three session types co-existing in user_data must serialize.

    The bot can hold flashcard + LTR + quiz state concurrently only in
    edge cases, but each one individually must always be
    JSON-serializable so that ``JSONPersistence`` can take over without
    losing user progress.
    """
    context = FakeContext()

    # Flashcard
    fc = FlashcardSessionManager(context)
    fc.initialize(lesson_id=1, only_due=True)
    fc.set_queue([_make_word(1), _make_word(2)])
    fc.add_to_skipped(1)
    context.user_data["current_flashcard"] = {"word_id": 1, "example": None}

    # LTR
    ltr = LTRSessionManager(context)
    ltr.initialize(
        user_id=42, lesson_id=None, weak_words=[], new_words=[_make_word(1)]
    )
    ltr.mark_word_learned(1)
    ltr.record_test_result(1, True, "meaning")
    ltr.record_test_result(1, True, "reverse")

    # Quiz
    _init_quiz_session(context, "meaning", 3, source_filter="weak", lesson_id=1)
    context.user_data["quiz_session_obj"]["correct_count"] = 1
    context.user_data["quiz_session_obj"]["question_ids"] = [1]

    _assert_json_safe(context.user_data)

    # Spot-check the JSON payload for an invariant: question_ids is a
    # list of ints, not a list of dataclass instances.
    payload = json.loads(json.dumps(context.user_data, default=str))
    assert payload["quiz_session_obj"]["question_ids"] == [1]
    assert payload["ltr_word_success_types"]["1"] == ["meaning", "reverse"]
    assert payload["flashcard_skipped_ids"] == [1]
    assert payload["flashcard_queue"] == [2]
