"""Integration test: full LTR (Learn → Test → wrong → retry → pass) flow.

Uses the real throwaway database (conftest.py) so that
``finalize_all_passed_words`` provably writes FSRS/SRS state.
"""

import pytest

from models import Word
from services import db, run_db
from handlers.learning.ltr_session import (
    LTRSessionManager,
    MAX_RETRIES,
    MIN_SUCCESS_TYPES,
)

# Unique per-suite UID so repeated runs against the shared temp DB stay sane.
UID = 987_654

_WORDS = [
    ("Haus", "خانه", "das", "Noun"),
    ("laufen", "دویدن", "", "Verb"),
    ("schnell", "سریع", "", "Adjective"),
]


async def _seed_user_and_words():
    """Insert a user + 3 real words; return Word objects with real DB ids."""
    await run_db(
        db.users.register_user,
        user_id=UID,
        username="ltr_flow_test",
        first_name="LTR",
        last_name="Tester",
    )
    book_id = await run_db(db.books.create, "LTRFlowBook", "A1")
    lesson_id = await run_db(db.lessons.create, book_id, 997, "LTR Flow Lesson")

    for german, persian, article, word_type in _WORDS:
        await run_db(
            db.words.upsert_word,
            german_word=german,
            persian_meaning=persian,
            book_id=book_id,
            lesson_id=lesson_id,
            article=article,
            word_type=word_type,
        )

    rows = await run_db(db.words.get_by_lesson_full, lesson_id)
    by_german = {r["german"]: r["id"] for r in rows}

    words = [
        Word(
            id=by_german[german],
            german=german,
            persian=persian,
            article=article,
            word_type=word_type,
        )
        for german, persian, article, word_type in _WORDS
    ]
    assert len(words) == 3 and all(w.id for w in words)
    return words


class FakeContext:
    def __init__(self):
        self.user_data = {}


async def test_ltr_full_flow_learn_test_wrong_retry_pass_updates_srs():
    context = FakeContext()
    words = await _seed_user_and_words()
    ltr = LTRSessionManager(context)

    # ─── 1. LEARN: hand out all three words (DB-backed lookup) ───────
    assert ltr.initialize(UID, None, [], words) is True
    learned_ids = []
    while True:
        w = await ltr.get_next_word_to_learn()
        if w is None:
            break
        ltr.mark_word_learned(w.id)
        learned_ids.append(w.id)
    assert sorted(learned_ids) == sorted(w.id for w in words)

    # Delayed tests are scheduled but not yet due (DELAY_AFTER_LEARN > 3).
    tasks = context.user_data["ltr_delayed_tasks"]
    assert len(tasks) == 3
    assert ltr.get_due_test() is None

    a, b, c = learned_ids
    xp_before = (await run_db(db.users.get_progress, UID))["xp"]

    # ─── 2. TEST A: one correct type is NOT enough ───────────────────
    assert MIN_SUCCESS_TYPES == 2
    ltr.record_test_result(a, True, "meaning")
    assert a not in context.user_data["ltr_words_passed"], (
        "a single successful question type must not pass the word"
    )
    assert any(
        t["word_id"] == a for t in context.user_data["ltr_delayed_tasks"]
    ), "word must be re-scheduled with another question type"
    ltr.record_test_result(a, True, "reverse")
    assert a in context.user_data["ltr_words_passed"]

    # ─── 3. TEST B: wrong → retry scheduled → pass via 2 types ───────
    ltr.record_test_result(b, False, "meaning")
    assert b not in context.user_data["ltr_words_passed"]
    assert b not in context.user_data["ltr_words_failed"], (
        "one mistake must never immediately fail the word"
    )
    retry_task = [
        t
        for t in context.user_data["ltr_delayed_tasks"]
        if t["word_id"] == b and t.get("is_retry")
    ]
    assert retry_task, "a retry task must be scheduled after a wrong answer"

    # Wrong answers do not count towards MIN_SUCCESS_TYPES...
    ltr.record_test_result(b, True, "meaning")
    assert b not in context.user_data["ltr_words_passed"]
    # ...but a second distinct correct type closes the word.
    ltr.record_test_result(b, True, "reverse")
    assert b in context.user_data["ltr_words_passed"]

    # ─── 4. TEST C: mistake in the middle, still passes ──────────────
    ltr.record_test_result(c, True, "cloze")
    ltr.record_test_result(c, False, "cloze")
    assert c not in context.user_data["ltr_words_failed"]
    ltr.record_test_result(c, True, "meaning")
    assert c in context.user_data["ltr_words_passed"]
    assert context.user_data["ltr_word_results"][c] == [True, False, True]

    # Sanity: nobody was pushed to the failed bucket (retry budget intact).
    assert MAX_RETRIES >= 1
    assert context.user_data["ltr_words_failed"] == []

    # ─── 5. FINALIZE: must really persist FSRS updates ───────────────
    await ltr.finalize_all_passed_words()

    for wid in (a, b, c):
        stats = await run_db(db.words.get_stats_full, UID, wid)
        assert stats, f"SRS row missing for word {wid}"
        assert int(stats.get("correct") or 0) >= 1
        assert float(stats.get("stability") or 0) > 0
        assert stats.get("last_reviewed")
        assert stats.get("next_review")
        assert stats.get("phase") in ("learning", "review", "mastered")

    # Activity/XP must be recorded by finalize_word → record_activity.
    xp_after = (await run_db(db.users.get_progress, UID))["xp"]
    assert xp_after >= xp_before + 5

    # Session summary agrees with the flow.
    summary = ltr.get_session_summary()
    assert summary["total_words"] == 3
    assert summary["passed_words"] == 3
    assert summary["failed_words"] == 0
    assert summary["accuracy"] == 100