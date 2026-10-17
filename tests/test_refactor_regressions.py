"""Behavioral regression tests for repository and handler refactoring."""

import asyncio
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from database import Database
from database import schema
from domain.content import story_question
from services.llm import LLMService


@pytest.fixture
def db(tmp_path):
    database = Database(str(tmp_path / "refactor.db"))
    yield database
    database.close()


class Query:
    def __init__(self):
        self.from_user = SimpleNamespace(id=1)
        self.data = ""
        self.message = SimpleNamespace(chat_id=1)
        self.answer = AsyncMock()
        self.edits = []

    async def edit_message_text(self, text, reply_markup=None):
        self.edits.append((text, reply_markup))


def test_legacy_columns_are_added_before_indexes():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE words (id INTEGER PRIMARY KEY,german TEXT,persian TEXT)")
    conn.execute("INSERT INTO words VALUES (1,'Haus','home')")
    conn.commit()
    schema.ensure_schema(conn.cursor())
    assert conn.execute("PRAGMA user_version").fetchone()[0] == schema.SCHEMA_VERSION
    indexes = {r[1] for r in conn.execute("PRAGMA index_list(words)")}
    assert "idx_words_cefr" in indexes
    assert "idx_words_lesson" in indexes
    assert conn.execute("SELECT german FROM words WHERE id=1").fetchone()[0] == "Haus"
    schema.ensure_schema(conn.cursor())
    conn.close()


def test_unexpected_migration_failure_rolls_back_entire_upgrade(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE retained (value TEXT)")
    conn.execute("INSERT INTO retained VALUES ('keep')")
    conn.commit()
    monkeypatch.setattr(
        schema,
        "INDEX_STATEMENTS",
        schema.INDEX_STATEMENTS + ("CREATE INDEX invalid_index ON words(no_such_column)",),
    )
    with pytest.raises(sqlite3.OperationalError):
        schema.ensure_schema(conn.cursor())
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
    assert conn.execute("SELECT value FROM retained").fetchone()[0] == "keep"
    assert not conn.execute("SELECT name FROM sqlite_master WHERE name='words'").fetchall()
    conn.close()


def test_newer_database_is_not_downgraded():
    conn = sqlite3.connect(":memory:")
    conn.execute(f"PRAGMA user_version={schema.SCHEMA_VERSION + 1}")
    with pytest.raises(RuntimeError, match="newer"):
        schema.ensure_schema(conn.cursor())
    assert not conn.execute("SELECT name FROM sqlite_master").fetchall()
    conn.close()


def seed_progress(db, uid):
    db.users.update_setting(uid, "B1")
    db.learning.observe_ltr_word(uid, 10)
    db.learning.record_skill(uid, 10, "meaning", False)
    db.learning.record_mistake(uid, word_id=10, skill_type="meaning")
    db.learning.record_grammar_answer(uid, 1, True)
    db.learning.record_story_answer(uid, 1, True)
    db.users.record_activity(uid, 5)
    db.users.update_quiz_stats(uid, True)
    db.learning.record_ltr_attempt(uid, 10, f"attempt{uid}", "meaning", True, False, "a", "a")
    db.learning.save_ltr_finalization(f"session{uid}", uid, 10, "2030-01-01 00:00:00")
    db.learning.increment_llm_usage(uid, "example")


def test_reset_is_complete_isolated_and_preserves_settings_and_quota(db):
    seed_progress(db, 1)
    seed_progress(db, 2)
    db.users.reset_user_progress(1)
    for table in (
        "word_stats",
        "word_skills",
        "mistakes",
        "mistake_stats",
        "grammar_progress",
        "story_progress",
        "user_progress",
        "user_stats",
        "word_first_seen",
        "ltr_attempts",
        "ltr_finalizations",
    ):
        assert db.conn.execute(f"SELECT COUNT(*) FROM {table} WHERE user_id=1").fetchone()[0] == 0
        assert db.conn.execute(f"SELECT COUNT(*) FROM {table} WHERE user_id=2").fetchone()[0] > 0
    assert db.users.get_settings(1)["preferred_level"] == "B1"
    assert db.learning.get_llm_usage(1)["example"] == 1


def test_failed_reset_preserves_all_previous_rows(db, monkeypatch):
    seed_progress(db, 1)
    original = db.users.execute

    def fail(query, *args, **kwargs):
        if "DELETE FROM word_skills" in query:
            raise RuntimeError("injected failure")
        return original(query, *args, **kwargs)

    monkeypatch.setattr(db.users, "execute", fail)
    with pytest.raises(RuntimeError):
        db.users.reset_user_progress(1)
    assert db.conn.execute("SELECT COUNT(*) FROM word_stats").fetchone()[0] == 1
    assert db.conn.execute("SELECT COUNT(*) FROM word_first_seen").fetchone()[0] == 1


def test_reminder_counts_match_dashboard_for_each_local_day(db):
    for uid, offset in ((1, -720), (2, 840)):
        db.users.update_setting(uid, "A1")
        db.users.execute(
            "UPDATE user_settings SET timezone_offset_minutes=? WHERE user_id=?",
            (offset, uid),
            commit=True,
        )
        start, end = db.learning.day_bounds(uid)
        previous = (datetime.fromisoformat(start) - timedelta(seconds=1)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        for wid, stamp in ((1, previous), (2, start), (3, end)):
            db.learning.execute(
                "INSERT INTO word_first_seen VALUES (?,?,?)", (uid, wid, stamp), commit=True
            )
        db.learning.record_skill(
            uid, 1, "meaning", True
        )  # Reviewing an old word never makes it new.
    batch = db.users.get_today_new_counts_for_users([1, 2, 3])
    assert batch == {1: 1, 2: 1}
    assert all(batch.get(uid, 0) == db.learning.get_today_new_words_count(uid) for uid in (1, 2, 3))


def test_concurrent_xp_increments_are_not_lost(db):
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda _: db.users.record_activity(1, 1), range(40)))
    assert db.users.get_progress(1)["xp"] == 40


def test_activity_date_uses_user_timezone(db):
    db.users.update_setting(1, "A1")
    db.users.execute(
        "UPDATE user_settings SET timezone_offset_minutes=-720 WHERE user_id=1", commit=True
    )
    db.users.record_activity(1, 5)
    expected = datetime.now(timezone(timedelta(hours=-12))).strftime("%Y-%m-%d")
    assert db.users.get_progress(1)["last_active_date"] == expected


def test_shared_app_is_built_once_across_worker_threads(monkeypatch):
    import services

    built = []
    app = object()

    def build():
        time.sleep(0.01)
        built.append(app)
        return app

    monkeypatch.setattr(services, "_app", None)
    monkeypatch.setattr(services, "build_app", build)
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: services.get_app(), range(20)))
    assert built == [app]
    assert all(result is app for result in results)


@pytest.mark.parametrize("raw", [None, "abcd", {"a": 1}, 12])
def test_malformed_llm_options_cannot_become_character_choices(raw):
    assert LLMService._normalize_quiz({"options": raw}, "question", "correct") is None


@pytest.mark.parametrize(
    "raw",
    [
        {"question": "q", "options": ["a", "b"], "correct_index": "0"},
        {"question": "q", "options": ["a", "a"], "correct_answer": "a"},
        {"question": "q", "options": "abcd", "correct_answer": "a"},
        {"question": "q", "options": ["a", "b"], "correct_index": True},
    ],
)
def test_invalid_story_questions_are_not_scored(raw):
    assert story_question(raw) is None


def seed_story(db, questions):
    db.learning.execute(
        "INSERT INTO stories (id,lesson_id,questions_json) VALUES (1,1,?)",
        (json.dumps(questions),),
        commit=True,
    )


async def test_story_duplicate_answer_and_stale_next_do_not_score_next_question(db, monkeypatch):
    from handlers.story import quiz as handler

    monkeypatch.setattr(handler, "db", db)
    seed_story(
        db, [{"question": f"q{i}", "options": ["a", "b"], "correct_answer": "a"} for i in (1, 2)]
    )
    query = Query()
    ctx = SimpleNamespace(user_data={})
    await handler.start_story_quiz(query, ctx, 1)
    state = ctx.user_data["story_quiz"]
    token = state["answer_token"]
    idx = state["current_correct_index"]
    await handler.handle_story_answer(query, ctx, f"{token}:{idx}")
    await handler.handle_story_answer(query, ctx, f"{token}:{idx}")
    assert state["correct"] == 1
    assert db.users.get_progress(1)["xp"] == 10
    next_token = state["next_token"]
    await handler.handle_story_next_question(query, ctx, next_token)
    current_token = state["answer_token"]
    text = query.edits[-1][0]
    await handler.handle_story_answer(query, ctx, f"{token}:{idx}")
    await handler.handle_story_next_question(query, ctx, next_token)
    assert state["answer_token"] == current_token
    assert query.edits[-1][0] == text
    assert state["correct"] == 1


async def test_story_failure_leaves_question_unconsumed(db, monkeypatch):
    from handlers.story import quiz as handler

    monkeypatch.setattr(handler, "db", db)
    seed_story(db, [{"question": "q", "options": ["a", "b"], "correct_answer": "a"}])
    ctx = SimpleNamespace(user_data={})
    query = Query()
    await handler.start_story_quiz(query, ctx, 1)
    state = ctx.user_data["story_quiz"]

    def fail(*args):
        raise RuntimeError("progress unavailable")

    monkeypatch.setattr(db.learning, "record_story_answer", fail)
    with pytest.raises(RuntimeError):
        await handler.handle_story_answer(
            query, ctx, f"{state['answer_token']}:{state['current_correct_index']}"
        )
    assert state["awaiting_answer"] is True
    assert state["correct"] == 0
    assert db.users.get_progress(1)["xp"] == 0


@pytest.mark.parametrize("raw", ["null", "{}", '[1,null,"bad",{"de":"Hallo","fa":"hello"}]'])
async def test_grammar_content_validation_survives_wrong_json_shapes(db, monkeypatch, raw):
    from handlers import grammar_handlers as handler

    monkeypatch.setattr(handler, "db", db)
    db.learning.execute(
        "INSERT INTO grammar_points (id,lesson_id,title_fa,explanation_fa,examples_json,exercises_json) "
        "VALUES (1,1,?,?,?,?)",
        ("Title", "Explanation", raw, raw),
        commit=True,
    )
    query = Query()
    ctx = SimpleNamespace(user_data={"grammar_current": {"old": "question"}})
    await handler.show_grammar_point(query, ctx, 1)
    await handler.start_grammar_quiz(query, ctx, 1)
    assert query.edits
    assert "grammar_current" not in ctx.user_data


async def test_listening_skip_is_not_failure_and_stale_skip_is_ignored(db, monkeypatch):
    from handlers import listening_handlers as handler

    monkeypatch.setattr(handler, "db", db)
    monkeypatch.setattr(handler, "_show_listening_question", AsyncMock())
    session = {"words": [10, 11], "current": 0, "correct": 0, "wrong": 0}
    ctx = SimpleNamespace(
        user_data={
            "listening_session": session,
            "listening_current": {"word_id": 10, "answer_token": "current"},
        }
    )
    query = Query()
    await handler.handle_listening_skip(query, ctx, "old")
    assert session["current"] == 0
    await handler.handle_listening_skip(query, ctx, "current")
    await handler.handle_listening_skip(query, ctx, "current")
    assert session["skipped"] == 1 and session["current"] == 1 and session["wrong"] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM word_stats").fetchone()[0] == 0


async def test_unavailable_listening_words_advance_without_recursion(db, monkeypatch):
    from handlers import listening_handlers as handler

    monkeypatch.setattr(handler, "db", db)

    async def inline(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(handler, "run_db", inline)
    session = {"words": list(range(10000, 11500)), "current": 0, "correct": 0, "wrong": 0}
    ctx = SimpleNamespace(user_data={"listening_session": session})
    query = Query()
    await handler._show_listening_question(query, ctx)
    assert session["current"] == 1500
    assert "listening_session" not in ctx.user_data
    assert query.edits


@pytest.mark.parametrize("source", ["weak", "seen", "mistakes"])
async def test_quiz_sources_accept_and_respect_lesson_scope(db, monkeypatch, source):
    from handlers import quiz_questions as handler

    monkeypatch.setattr(handler, "db", db)
    book = db.books.create("Book")
    lessons = [db.lessons.create(book, i, str(i)) for i in (1, 2)]
    ids = [
        db.words.upsert_word(f"Word{i}", f"meaning{i}", book_id=book, lesson_id=lesson)
        for i, lesson in enumerate(lessons)
    ]
    for wid in ids:
        db.learning.observe_ltr_word(1, wid)
        db.learning.record_skill(1, wid, "meaning", False)
        db.words.execute(
            "UPDATE word_stats SET wrong_count=1 WHERE user_id=1 AND word_id=?", (wid,), commit=True
        )
        db.learning.record_mistake(1, word_id=wid, skill_type="meaning")
    words = await handler._fetch_words_by_source(1, lessons[0], source, set())
    assert [word.id for word in words] == [ids[0]]
    assert await handler._fetch_words_by_source(1, lessons[0], source, {ids[0]}) == []


async def test_cloze_does_not_escape_the_selected_source(db, monkeypatch):
    from handlers import quiz_questions as handler

    monkeypatch.setattr(handler, "db", db)
    db.words.upsert_word("Haus", "home", example_de="Das Haus ist neu.")
    assert await handler._get_word_with_example(1, None, "mistakes", set()) is None


async def test_flashcard_requeued_word_rejects_its_previous_buttons(db, monkeypatch):
    from handlers.learning import flashcard_session as handler
    from handlers.learning.flashcard_state import FlashcardSessionManager

    monkeypatch.setattr(handler, "db", db)
    ctx = SimpleNamespace(user_data={})
    mgr = FlashcardSessionManager(ctx)
    mgr.set_current_word(10)
    old = ctx.user_data["current_flashcard"]["answer_token"]
    mgr.set_current_word(10)
    token = ctx.user_data["current_flashcard"]["answer_token"]
    assert old != token
    query = Query()
    await handler.handle_rate_card(query, ctx, f"{old}:10:3")
    await handler.handle_skip_flashcard(query, ctx, f"{old}:10")
    assert ctx.user_data["current_flashcard"]["answer_token"] == token
    assert db.conn.execute("SELECT COUNT(*) FROM word_stats").fetchone()[0] == 0
    with pytest.raises(ValueError):
        handler._card_action(f"{token}:10:99", ctx.user_data["current_flashcard"], rating=True)


async def test_flashcard_completion_preserves_mode_for_summary(monkeypatch):
    from handlers.learning import flashcard_session as handler

    ctx = SimpleNamespace(user_data={"flashcard_only_new": True, "flashcard_queue": []})
    query = Query()
    await handler._go_next_flashcard(query, ctx)
    assert "کلمات جدید" in query.edits[-1][0]
    assert "flashcard_only_new" not in ctx.user_data


async def test_quiz_enrichment_tasks_are_cancelled_at_shutdown():
    from handlers import quiz_questions as handler

    event = asyncio.Event()

    async def work():
        await event.wait()

    handler._spawn_background(work())
    tasks = list(handler._background_tasks)
    await handler.close_background_tasks()
    assert all(task.cancelled() for task in tasks)
    assert not handler._background_tasks


def test_nested_transactions_rollback_only_the_failed_unit(db):
    with db.transaction():
        db.users.update_setting(1, "A1")
        with pytest.raises(RuntimeError):
            with db.transaction():
                db.users.update_setting(1, "B2")
                raise RuntimeError("abort inner")
        db.users.update_setting(2, "B1")
    assert db.users.get_settings(1)["preferred_level"] == "A1"
    assert db.users.get_settings(2)["preferred_level"] == "B1"


async def test_leaving_ltr_finalizes_work_before_clearing_session(db, monkeypatch):
    from handlers.learning import ltr_session
    from handlers.learning.lifecycle import suspend_ltr
    from domain.models import Word
    from services.srs import FSRSService

    monkeypatch.setattr(ltr_session, "db", db)
    monkeypatch.setattr(ltr_session, "fsrs", FSRSService(db))
    ctx = SimpleNamespace(user_data={})
    manager = ltr_session.LTRSessionManager(ctx)
    manager.initialize(1, None, [], [Word(10, "Haus", "home", article="das")])
    db.learning.observe_ltr_word(1, 10)
    manager.mark_word_learned(10)
    manager.record_test_result(10, True, "meaning")
    manager.record_test_result(10, True, "recall")
    await suspend_ltr(ctx)
    assert not ctx.user_data.get("ltr_words")
    assert db.users.get_progress(1)["xp"] == 10
    assert db.words.get_stats_full(1, 10)["correct"] == 1


def test_check_summary_is_safe_on_windows_legacy_console(monkeypatch):
    import io
    import sys
    import runpy
    from pathlib import Path

    _print_summary = runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "scripts/run_checks.py")
    )["_print_summary"]

    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", stream)
    _print_summary([("pytest", True, 0.1, "ok")])
    stream.flush()
    assert b"ALL CHECKS PASSED" in stream.buffer.getvalue()


def test_grammar_streak_is_atomic_across_threads(db):
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda _: db.learning.record_grammar_answer(1, 1, True), range(20)))
    row = db.conn.execute("SELECT correct_streak,correct_count FROM grammar_progress").fetchone()
    assert row == (20, 20)


def test_failed_database_initialization_closes_connection(tmp_path, monkeypatch):
    import database

    connections = []

    def fail(self):
        connections.append(self.conn)
        raise RuntimeError("cannot upgrade")

    monkeypatch.setattr(database.Database, "_ensure_schema", fail)
    with pytest.raises(RuntimeError):
        database.Database(str(tmp_path / "failed.db"))
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connections[0].execute("SELECT 1")


async def test_invalid_story_start_discards_previous_question(db, monkeypatch):
    from handlers.story import quiz as handler

    monkeypatch.setattr(handler, "db", db)
    ctx = SimpleNamespace(user_data={"story_quiz": {"old": "question"}})
    await handler.start_story_quiz(Query(), ctx, 12345)
    assert "story_quiz" not in ctx.user_data


def test_new_flashcard_session_clears_previous_card_and_queue():
    from handlers.learning.flashcard_state import FlashcardSessionManager

    ctx = SimpleNamespace(
        user_data={"current_flashcard": {"word_id": 1}, "flashcard_queue": [2, 3]}
    )
    FlashcardSessionManager(ctx).initialize(only_new=True)
    assert "current_flashcard" not in ctx.user_data
    assert "flashcard_queue" not in ctx.user_data
    assert ctx.user_data["flashcard_only_new"] is True


def test_test_configuration_cannot_inherit_production_database(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    production = tmp_path / "production.db"
    env = dict(os.environ, DB_PATH=str(production), BOT_MODE="online")
    command = "import runpy,os,json; runpy.run_path('tests/conftest.py'); print(json.dumps([os.environ['DB_PATH'],os.environ['BOT_MODE']]))"
    result = subprocess.run(
        [sys.executable, "-c", command],
        env=env,
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=True,
    )
    path, mode = json.loads(result.stdout)
    assert path != str(production)
    assert mode == "offline"
    assert not production.exists()
