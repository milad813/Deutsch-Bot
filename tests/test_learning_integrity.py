"""Regression coverage for learning integrity fixes."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from database import Database
from database.schema import ensure_schema
from services.srs import FSRSService
import learning_engine


@pytest.fixture
def database(tmp_path):
    db = Database(str(tmp_path / "learning.db"))
    yield db
    db.close()


def test_review_does_not_turn_old_word_into_new(database):
    database.conn.execute(
        "INSERT INTO word_first_seen VALUES (1, 10, ?)",
        ((datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"),),
    )
    database.conn.commit()
    database.learning.record_skill(1, 10, "meaning", True)
    database.learning.record_skill(1, 11, "meaning", True)
    database.learning.record_skill(1, 11, "listening", True)
    assert database.learning.get_today_new_words_count(1) == 1
    assert database.learning.get_today_new_words_count(2) == 0


def test_legacy_backfill_preserves_earliest_observation(database):
    database.conn.execute(
        "INSERT INTO word_skills (user_id,word_id,skill_type,last_reviewed) "
        "VALUES (1,10,'meaning','2020-01-01 00:00:00')"
    )
    with database._conn.cursor(commit=True) as cursor:
        ensure_schema(cursor)
    database.learning.record_skill(1, 10, "meaning", True)
    with database._conn.cursor(commit=True) as cursor:
        ensure_schema(cursor)
    assert database.learning.get_today_new_words_count(1) == 0


def test_grammar_streak_changes_interval_and_resets(database):
    for expected in (1, 2, 3):
        database.learning.record_grammar_answer(1, 4, True)
        streak, next_review = database.conn.execute(
            "SELECT correct_streak,next_review FROM grammar_progress"
        ).fetchone()
        assert streak == expected
        delta = datetime.fromisoformat(next_review).replace(tzinfo=timezone.utc) - datetime.now(
            timezone.utc
        )
        assert abs(delta.total_seconds() / 86400 - (1, 2, 4)[expected - 1]) < 0.01
    database.learning.record_grammar_answer(1, 4, False)
    assert database.conn.execute("SELECT correct_streak FROM grammar_progress").fetchone()[0] == 0
    database.learning.record_grammar_answer(1, 4, True)
    assert database.conn.execute("SELECT correct_streak FROM grammar_progress").fetchone()[0] == 1


@pytest.mark.parametrize("fail_at", ["srs", "mistake", "activity"])
def test_quiz_failure_rolls_back_all_writes(database, monkeypatch, fail_at):
    srs = FSRSService(database)
    monkeypatch.setattr(learning_engine, "_deps", lambda: (database, srs))

    def fail(*args, **kwargs):
        raise RuntimeError("injected failure")

    target, method = {
        "srs": (srs, "review"),
        "mistake": (database.learning, "record_mistake"),
        "activity": (database.users, "record_activity"),
    }[fail_at]
    monkeypatch.setattr(target, method, fail)
    with pytest.raises(RuntimeError):
        learning_engine.record_quiz_answer(1, 10, "meaning", False, xp=0)
    for table in (
        "user_stats",
        "word_skills",
        "word_stats",
        "mistakes",
        "word_first_seen",
        "user_progress",
    ):
        assert database.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_quiz_success_commits_all_writes(database, monkeypatch):
    monkeypatch.setattr(learning_engine, "_deps", lambda: (database, FSRSService(database)))
    learning_engine.record_quiz_answer(1, 10, "meaning", False, xp=0)
    for table in (
        "user_stats",
        "word_skills",
        "word_stats",
        "mistakes",
        "word_first_seen",
        "user_progress",
    ):
        assert database.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 1


async def test_grammar_stale_and_duplicate_answers(database, monkeypatch):
    import handlers.grammar_handlers as handler

    monkeypatch.setattr(handler, "db", database)
    monkeypatch.setattr(handler, "render", AsyncMock())
    context = SimpleNamespace(
        user_data={
            "grammar_current": {
                "answer_token": "new",
                "options": ["a", "b"],
                "correct_index": 0,
                "point_id": 4,
                "correct": "a",
                "lesson_id": 1,
            }
        }
    )
    query = SimpleNamespace(from_user=SimpleNamespace(id=1), answer=AsyncMock())
    await handler.handle_grammar_answer(query, context, "old:0")
    assert database.conn.execute("SELECT COUNT(*) FROM grammar_progress").fetchone()[0] == 0
    await handler.handle_grammar_answer(query, context, "new:0")
    await handler.handle_grammar_answer(query, context, "new:0")
    assert database.conn.execute("SELECT correct_count FROM grammar_progress").fetchone()[0] == 1


async def test_listening_audio_title_does_not_expose_word(database, monkeypatch, tmp_path):
    import handlers.listening_handlers as handler
    from domain.models import Word

    word = Word(10, "Haus", "home", article="das")
    monkeypatch.setattr(handler, "db", database)
    monkeypatch.setattr(database.words, "get_by_id", lambda _: word)
    monkeypatch.setattr(handler, "get_wrong_options", lambda *a, **k: ["other"])
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"test")
    monkeypatch.setattr(
        handler, "tts", SimpleNamespace(get_audio_path=AsyncMock(return_value=str(audio)))
    )
    monkeypatch.setattr(handler, "render", AsyncMock())
    context = SimpleNamespace(
        user_data={
            "listening_session": {
                "words": [10],
                "current": 0,
                "correct": 0,
                "wrong": 0,
            }
        },
        bot=SimpleNamespace(send_audio=AsyncMock()),
    )
    query = SimpleNamespace(message=SimpleNamespace(chat_id=1))
    await handler._show_listening_question(query, context)
    await handler.handle_listening_replay(
        SimpleNamespace(message=query.message, answer=AsyncMock()),
        context,
        context.user_data["listening_current"]["answer_token"],
    )
    assert context.bot.send_audio.await_count == 2
    for call in context.bot.send_audio.call_args_list:
        assert "Haus" not in call.kwargs["title"]
    current = dict(context.user_data["listening_current"])
    query.from_user = SimpleNamespace(id=1)
    query.answer = AsyncMock()
    await handler.handle_listening_answer(query, context, "expired:0")
    assert context.user_data["listening_current"] == current
    assert database.conn.execute("SELECT COUNT(*) FROM word_stats").fetchone()[0] == 0


async def test_quiz_rejects_answer_from_previous_question(monkeypatch):
    import handlers.quiz_handlers as handler

    context = SimpleNamespace(
        user_data={
            "current_quiz": {
                "answer_token": "current",
                "options": ["a", "b"],
                "correct_index": 0,
            }
        }
    )
    query = SimpleNamespace(data="quiz_ans:previous:0", answer=AsyncMock())
    recorder = AsyncMock()
    monkeypatch.setattr(handler, "run_db", recorder)
    await handler.handle_quiz_answer(query, context)
    recorder.assert_not_called()
    assert "current_quiz" in context.user_data


def test_new_word_count_uses_user_local_day(database):
    database.conn.execute(
        "INSERT INTO user_settings (user_id, timezone_offset_minutes) VALUES (1,-720)"
    )
    local = timezone(timedelta(hours=-12))
    start = datetime.now(local).replace(hour=0, minute=0, second=0, microsecond=0)
    for word_id, date in enumerate(
        (start - timedelta(seconds=1), start, start + timedelta(days=1)), 1
    ):
        database.conn.execute(
            "INSERT INTO word_first_seen VALUES (1,?,?)",
            (word_id, date.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")),
        )
    database.conn.commit()
    assert database.learning.get_today_new_words_count(1) == 1


async def test_grammar_failure_is_retryable_and_atomic(database, monkeypatch):
    import handlers.grammar_handlers as handler

    monkeypatch.setattr(handler, "db", database)
    monkeypatch.setattr(handler, "render", AsyncMock())
    context = SimpleNamespace(
        user_data={
            "grammar_current": {
                "answer_token": "new",
                "options": ["a", "b"],
                "correct_index": 0,
                "point_id": 4,
                "correct": "a",
                "lesson_id": 1,
            }
        }
    )
    query = SimpleNamespace(from_user=SimpleNamespace(id=1), answer=AsyncMock())

    def fail(*args):
        raise RuntimeError("activity failure")

    monkeypatch.setattr(database.users, "record_activity", fail)
    with pytest.raises(RuntimeError):
        await handler.handle_grammar_answer(query, context, "new:1")
    assert "grammar_current" in context.user_data
    assert "grammar_answer_lock" not in context.user_data
    for table in ("grammar_progress", "mistakes", "user_progress"):
        assert database.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
