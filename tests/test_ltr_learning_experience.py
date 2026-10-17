"""Behavioral coverage for spaced LTR and independent recall."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from database import Database
from services.srs import FSRSService
from core.sessions import reset_session, SESSION_KEYS
from handlers.learning import ltr_handlers as h
from handlers.learning import ltr_session as s


class Message:
    next_id = 100

    def __init__(self, text="", reply_to_message=None):
        Message.next_id += 1
        self.message_id = Message.next_id
        self.text = text
        self.reply_to_message = reply_to_message
        self.chat_id = 1
        self.sent = []

    async def reply_text(self, text, **kwargs):
        message = Message(text)
        self.sent.append((message, kwargs))
        return message


class Query:
    def __init__(self):
        self.from_user = SimpleNamespace(id=42)
        self.message = Message()
        self.answer = AsyncMock()
        self.edits = []

    async def edit_message_text(self, text, reply_markup=None, **kwargs):
        self.edits.append((text, reply_markup))


@pytest.fixture
def environment(tmp_path, monkeypatch):
    db = Database(str(tmp_path / "ltr.db"))
    fsrs = FSRSService(db)
    monkeypatch.setattr(h, "db", db)
    monkeypatch.setattr(s, "db", db)
    monkeypatch.setattr(s, "fsrs", fsrs)
    db.users.register_user(42, "learner", "Learner", "")
    db.learning.set_daily_goal(42, 30)
    book = db.books.create("Test", "A1")
    lesson = db.lessons.create(book, 1, "Test")
    for n in range(12):
        db.words.upsert_word(
            f"Wort{n}",
            f"meaning{n}",
            book_id=book,
            lesson_id=lesson,
            article="das",
            word_type="Noun",
            example_de=f"Das ist Wort{n}.",
            example_fa="Example translation",
            plural_form=f"Worte{n}",
        )
    ctx = SimpleNamespace(user_data={})
    yield db, ctx, Query(), lesson
    db.close()


async def start(ctx, query, size=5, lesson=None):
    if lesson is None:
        await h.handle_daily_learning(query, ctx)
    else:
        await h.handle_study_lesson(query, ctx, str(lesson))
    await h.handle_ltr_size(query, ctx, f"{ctx.user_data['ltr_token']}:{size}")


async def finish(ctx, query, *, wrong=False):
    observations = []
    for _ in range(200):
        phase = ctx.user_data.get("ltr_phase")
        token = ctx.user_data.get("ltr_token")
        if phase == "learn":
            await h.handle_ltr_learned(query, ctx, token)
        elif phase == "test":
            wid = ctx.user_data["ltr_current_question"]
            observations.append(
                (wid, ctx.user_data["ltr_activity"], ctx.user_data["ltr_question_type"])
            )
            if ctx.user_data["ltr_question_type"] == "recall":
                if wrong:
                    await h.handle_ltr_action(query, ctx, f"{token}:unknown")
                else:
                    message = Message(
                        ctx.user_data["ltr_current_correct_text"],
                        SimpleNamespace(message_id=ctx.user_data["ltr_prompt_id"]),
                    )
                    update = SimpleNamespace(
                        message=message, effective_message=message, effective_user=query.from_user
                    )
                    await h.handle_ltr_typed(update, ctx)
            else:
                index = ctx.user_data["ltr_current_correct_index"]
                if wrong:
                    index = (index + 1) % len(ctx.user_data["ltr_current_options"])
                await h.handle_ltr_answer(query, ctx, f"{token}:{index}")
        elif phase in ("feedback", "observation"):
            action = "continue" if phase == "feedback" else "observe"
            await h.handle_ltr_action(query, ctx, f"{token}:{action}")
        else:
            return observations
    pytest.fail("LTR did not terminate within its activity budget")


@pytest.mark.parametrize("size", [3, 5, 10])
async def test_complete_sessions_are_spaced_bounded_and_saved(environment, size):
    db, ctx, query, _ = environment
    await start(ctx, query, size)
    observations = await finish(ctx, query)
    assert not ctx.user_data.get("ltr_words")
    assert db.learning.get_today_new_words_count(42) == size
    assert db.conn.execute("SELECT COUNT(*) FROM word_stats WHERE user_id=42").fetchone()[0] == size
    previous = {}
    for wid, activity, kind in observations:
        if wid in previous:
            assert activity - previous[wid] >= s.SUCCESS_DELAY + 1
        previous[wid] = activity
    assert len(observations) <= size * s.MAX_ATTEMPTS_PER_WORD
    if size >= 5:
        assert any(kind == "recall" for _, _, kind in observations)
    assert any("تمرین اولیه" in text for text, _ in query.edits)
    assert "ltr_token" not in ctx.user_data


async def test_failed_session_terminates_and_schedules_review(environment):
    db, ctx, query, _ = environment
    await start(ctx, query)
    observations = await finish(ctx, query, wrong=True)
    assert len(observations) <= 5 * (s.MAX_RETRIES + 1)
    assert (
        db.conn.execute("SELECT COUNT(*) FROM word_stats WHERE phase='learning'").fetchone()[0] == 5
    )
    assert db.conn.execute("SELECT COUNT(*) FROM mistakes").fetchone()[0] > 0


async def test_feedback_waits_for_continue_and_stale_buttons_are_ignored(environment):
    db, ctx, query, _ = environment
    await start(ctx, query)
    for _ in range(3):
        await h.handle_ltr_learned(query, ctx, ctx.user_data["ltr_token"])
    assert ctx.user_data["ltr_phase"] == "test"
    token = ctx.user_data["ltr_token"]
    idx = ctx.user_data["ltr_current_correct_index"]
    await h.handle_ltr_answer(query, ctx, f"{token}:{idx}")
    assert ctx.user_data["ltr_phase"] == "feedback"
    count = db.conn.execute("SELECT COUNT(*) FROM ltr_attempts").fetchone()[0]
    await h.handle_ltr_answer(query, ctx, f"{token}:{idx}")
    await h.handle_ltr_action(query, ctx, f"{token}:continue")
    assert ctx.user_data["ltr_phase"] == "feedback"
    assert db.conn.execute("SELECT COUNT(*) FROM ltr_attempts").fetchone()[0] == count
    assert "Example translation" in query.edits[-1][0]


async def test_guidance_is_not_independent_recall(environment):
    db, ctx, query, _ = environment
    words = db.words.get_next_unseen_words(42, 3)
    mgr = s.LTRSessionManager(ctx)
    mgr.initialize(42, None, [], words)
    mgr.mark_word_learned(words[0].id)
    mgr.record_test_result(words[0].id, True, "meaning")
    await h._show_test_question(query, ctx, words[0].id)
    old_prompt = ctx.user_data["ltr_prompt_id"]
    await h.handle_ltr_action(query, ctx, f"{ctx.user_data['ltr_token']}:hint")
    assert ctx.user_data["ltr_assisted"] is True
    assert ctx.user_data["ltr_question_type"] == "reverse"
    index = ctx.user_data["ltr_current_correct_index"]
    await h.handle_ltr_answer(query, ctx, f"{ctx.user_data['ltr_token']}:{index}")
    assert words[0].id not in ctx.user_data["ltr_words_passed"]
    assert ctx.user_data["ltr_word_success_types"][words[0].id] == ["meaning"]
    assert db.conn.execute("SELECT assisted,question_type FROM ltr_attempts").fetchone() == (
        1,
        "reverse",
    )
    assert old_prompt is not None


async def test_typed_recall_requires_current_reply_and_records_one_attempt(environment):
    db, ctx, query, _ = environment
    words = db.words.get_next_unseen_words(42, 3)
    mgr = s.LTRSessionManager(ctx)
    mgr.initialize(42, None, [], words)
    mgr.mark_word_learned(words[0].id)
    mgr.record_test_result(words[0].id, True, "meaning")
    await h._show_test_question(query, ctx, words[0].id)
    text = f"  DAS   {words[0].german.upper()}!  "
    message = Message(text, SimpleNamespace(message_id=-1))
    update = SimpleNamespace(
        message=message, effective_message=message, effective_user=query.from_user
    )
    await h.handle_ltr_typed(update, ctx)
    assert db.conn.execute("SELECT COUNT(*) FROM ltr_attempts").fetchone()[0] == 0
    message.reply_to_message.message_id = ctx.user_data["ltr_prompt_id"]
    await h.handle_ltr_typed(update, ctx)
    await h.handle_ltr_typed(update, ctx)
    assert db.conn.execute("SELECT COUNT(*) FROM ltr_attempts").fetchone()[0] == 1
    assert words[0].id in ctx.user_data["ltr_words_passed"]


async def test_observation_fallback_never_awards_correctness(environment, monkeypatch):
    db, ctx, query, _ = environment
    await start(ctx, query)
    word = await s.LTRSessionManager(ctx).get_next_word_to_learn()
    await h.handle_ltr_learned(query, ctx, ctx.user_data["ltr_token"])
    monkeypatch.setattr(h, "get_wrong_options", lambda *args, **kwargs: [])
    ctx.user_data["ltr_current_question"] = word.id
    await h._render_meaning_question(query, ctx, word)
    assert ctx.user_data["ltr_assessment"] is False
    await h.handle_ltr_answer(query, ctx, f"{ctx.user_data['ltr_token']}:0")
    assert db.conn.execute("SELECT COUNT(*) FROM ltr_attempts").fetchone()[0] == 0
    await h.handle_ltr_action(query, ctx, f"{ctx.user_data['ltr_token']}:observe")
    assert db.conn.execute("SELECT COUNT(*) FROM word_skills").fetchone()[0] == 0


async def test_partial_exit_preserves_observations_without_fake_answers(environment):
    db, ctx, query, _ = environment
    await start(ctx, query)
    await h.handle_ltr_learned(query, ctx, ctx.user_data["ltr_token"])
    await h.handle_ltr_exit(query, ctx)
    assert db.learning.get_today_new_words_count(42) == 1
    assert db.conn.execute("SELECT correct_count,wrong_count FROM word_stats").fetchone() == (0, 0)
    assert db.conn.execute("SELECT COUNT(*) FROM word_skills").fetchone()[0] == 0
    assert "ltr_token" not in ctx.user_data


async def test_no_force_when_no_other_activities(environment):
    db, ctx, _, _ = environment
    word = db.words.get_next_unseen_words(42, 1)[0]
    mgr = s.LTRSessionManager(ctx)
    mgr.initialize(42, None, [], [word])
    mgr.mark_word_learned(word.id)
    assert await mgr.get_next_action() == "done"
    assert mgr.get_due_test() is None
    assert word.id in ctx.user_data["ltr_words_deferred"]
    await mgr.finalize_all_passed_words()
    assert db.conn.execute("SELECT correct_count,wrong_count FROM word_stats").fetchone() == (0, 0)


async def test_resume_due_words_even_after_daily_goal_is_met(environment):
    db, ctx, query, _ = environment
    await start(ctx, query, 3)
    await finish(ctx, query)
    db.learning.set_daily_goal(42, 3)
    db.conn.execute("UPDATE word_stats SET next_review='2000-01-01 00:00:00'")
    db.conn.commit()
    await start(ctx, query, 3)
    assert len(ctx.user_data["ltr_words"]) == 3
    assert all("meaning" in values for values in ctx.user_data["ltr_word_success_types"].values())
    observations = await finish(ctx, query)
    assert all(kind == "recall" for _, _, kind in observations)


async def test_attempt_failure_rolls_back_and_keeps_question_retryable(environment, monkeypatch):
    db, ctx, query, _ = environment
    await start(ctx, query)
    for _ in range(3):
        await h.handle_ltr_learned(query, ctx, ctx.user_data["ltr_token"])

    def fail(*args):
        raise RuntimeError("write failed")

    monkeypatch.setattr(db.learning, "record_skill", fail)
    token = ctx.user_data["ltr_token"]
    with pytest.raises(RuntimeError):
        await h.handle_ltr_answer(
            query, ctx, f"{token}:{ctx.user_data['ltr_current_correct_index']}"
        )
    assert ctx.user_data["ltr_phase"] == "test"
    assert ctx.user_data["ltr_token"] == token
    assert db.conn.execute("SELECT COUNT(*) FROM ltr_attempts").fetchone()[0] == 0
    assert "ltr_answer_lock" not in ctx.user_data


def test_success_requires_independent_recall_and_attempts_are_bounded():
    ctx = SimpleNamespace(user_data={})
    mgr = s.LTRSessionManager(ctx)
    for _ in range(s.MAX_ATTEMPTS_PER_WORD):
        mgr.record_test_result(1, True, "meaning")
    assert 1 not in ctx.user_data["ltr_words_passed"]
    assert 1 in ctx.user_data["ltr_words_deferred"]
    assert not ctx.user_data["ltr_delayed_tasks"]


def test_accuracy_is_attempt_accuracy_not_completion_ratio():
    ctx = SimpleNamespace(user_data={})
    mgr = s.LTRSessionManager(ctx)
    mgr.record_test_result(1, False, "meaning")
    mgr.record_test_result(1, True, "meaning")
    mgr.record_test_result(1, True, "recall")
    summary = mgr.get_session_summary()
    assert summary["accuracy"] == 66
    assert summary["first_accuracy"] == 0


@pytest.mark.parametrize(
    "text,expected",
    [("  DAS  HAUS! ", "das haus"), ("schön", "schön"), ("schon", "schon"), ("Straße", "straße")],
)
def test_normalization(text, expected):
    assert h._normalise_answer(text) == expected


def test_earlier_due_time_is_preserved(environment):
    db, _, _, _ = environment
    word = db.words.get_next_unseen_words(42, 1)[0]
    db.learning.observe_ltr_word(42, word.id)
    old = "2000-01-01 00:00:00"
    db.conn.execute("UPDATE word_stats SET next_review=?", (old,))
    db.conn.commit()
    assert db.learning.defer_ltr_review(42, word.id) == old


def test_session_reset_clears_all_new_state(environment):
    _, ctx, _, _ = environment
    keys = [
        "ltr_activity",
        "ltr_token",
        "ltr_assisted",
        "ltr_prompt_id",
        "ltr_finalized",
        "ltr_words_deferred",
        "ltr_first_answers",
        "ltr_review_times",
        "ltr_pending_lesson",
    ]
    assert set(keys) <= SESSION_KEYS
    ctx.user_data.update({key: 1 for key in keys})
    reset_session(ctx)
    assert not ctx.user_data


async def test_finalization_is_idempotent_after_session_cache_loss(environment):
    db, ctx, query, _ = environment
    await start(ctx, query)
    for _ in range(3):
        await h.handle_ltr_learned(query, ctx, ctx.user_data["ltr_token"])
    wid = ctx.user_data["ltr_current_question"]
    token = ctx.user_data["ltr_token"]
    await h.handle_ltr_answer(query, ctx, f"{token}:{ctx.user_data['ltr_current_correct_index']}")
    mgr = s.LTRSessionManager(ctx)
    await mgr.finalize_word(wid)
    before = db.words.get_stats_full(42, wid)
    xp = db.users.get_progress(42)["xp"]
    ctx.user_data["ltr_finalized"] = []  # Simulate recovery of older persisted user_data.
    await mgr.finalize_word(wid)
    assert db.words.get_stats_full(42, wid) == before
    assert db.users.get_progress(42)["xp"] == xp
    assert db.conn.execute("SELECT COUNT(*) FROM ltr_finalizations").fetchone()[0] == 1


async def test_finalization_failure_rolls_back_srs_and_can_retry(environment, monkeypatch):
    db, ctx, query, _ = environment
    await start(ctx, query)
    for _ in range(3):
        await h.handle_ltr_learned(query, ctx, ctx.user_data["ltr_token"])
    wid = ctx.user_data["ltr_current_question"]
    await h.handle_ltr_answer(
        query, ctx, f"{ctx.user_data['ltr_token']}:{ctx.user_data['ltr_current_correct_index']}"
    )
    mgr = s.LTRSessionManager(ctx)
    before = db.words.get_stats_full(42, wid)
    original = db.learning.save_ltr_finalization

    def fail(*args):
        raise RuntimeError("ledger unavailable")

    monkeypatch.setattr(db.learning, "save_ltr_finalization", fail)
    with pytest.raises(RuntimeError):
        await mgr.finalize_word(wid)
    assert db.words.get_stats_full(42, wid) == before
    assert wid not in ctx.user_data["ltr_finalized"]
    monkeypatch.setattr(db.learning, "save_ltr_finalization", original)
    await mgr.finalize_word(wid)
    assert wid in ctx.user_data["ltr_finalized"]


async def test_reply_flows_through_the_authorized_text_handler(environment, monkeypatch):
    from handlers import text_handlers

    db, ctx, query, _ = environment
    words = db.words.get_next_unseen_words(42, 3)
    mgr = s.LTRSessionManager(ctx)
    mgr.initialize(42, None, [], words)
    mgr.mark_word_learned(words[0].id)
    mgr.record_test_result(words[0].id, True, "meaning")
    await h._show_test_question(query, ctx, words[0].id)
    message = Message(
        words[0].display_german, SimpleNamespace(message_id=ctx.user_data["ltr_prompt_id"])
    )
    update = SimpleNamespace(
        message=message, effective_message=message, effective_user=query.from_user
    )
    monkeypatch.setattr(text_handlers.config, "is_authorized_user", lambda uid: True)
    await text_handlers.handle_text_input(update, ctx)
    assert db.conn.execute("SELECT question_type FROM ltr_attempts").fetchone()[0] == "recall"
    assert ctx.user_data["ltr_phase"] == "feedback"


def test_guided_answers_and_success_before_latest_error_are_not_carried(environment):
    db, _, _, _ = environment
    for token, correct, assisted, kind in [
        ("a", True, False, "meaning"),
        ("b", False, False, "recall"),
        ("c", True, True, "reverse"),
    ]:
        db.learning.record_ltr_attempt(42, 1, token, kind, correct, assisted, "answer", "correct")
    assert db.learning.get_ltr_success_types(42, 1) == []
    db.learning.record_ltr_attempt(42, 1, "d", "meaning", True, False, "answer", "correct")
    assert db.learning.get_ltr_success_types(42, 1) == ["meaning"]


def test_attempt_ids_prevent_duplicate_recording(environment):
    db, _, _, _ = environment
    assert db.learning.record_ltr_attempt(42, 1, "same", "meaning", True, False, "a", "a")
    assert not db.learning.record_ltr_attempt(42, 1, "same", "meaning", True, False, "a", "a")
    assert db.conn.execute("SELECT COUNT(*) FROM ltr_attempts").fetchone()[0] == 1


async def test_single_due_word_is_tested_before_revealing_its_answer(environment):
    db, ctx, query, lesson = environment
    word = db.words.get_next_unseen_words(42, 1)[0]
    # Remove the unused test vocabulary to model a one-word library.
    db.conn.execute("DELETE FROM words WHERE id<>?", (word.id,))
    db.conn.commit()
    db.learning.observe_ltr_word(42, word.id)
    db.learning.record_ltr_attempt(
        42, word.id, "previous", "meaning", True, False, word.persian, word.persian
    )
    db.conn.execute("UPDATE word_stats SET next_review='2000-01-01 00:00:00'")
    db.conn.commit()
    await start(ctx, query, 3, lesson)
    assert ctx.user_data["ltr_phase"] == "test"
    assert ctx.user_data["ltr_question_type"] == "recall"
    assert word.display_german not in query.edits[-1][0]
    observations = await finish(ctx, query)
    assert observations == [(word.id, 0, "recall")]
    assert not ctx.user_data.get("ltr_words")
