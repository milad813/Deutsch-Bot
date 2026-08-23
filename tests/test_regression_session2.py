"""Functional regression tests for the session-2 bug fixes (B7, B8, B11).

B7: ltr_handlers used run_db without importing it  -> every LTR test crashed.
B8: tts_handlers used run_db without importing it  -> speak-current crashed.
B11: _render_final_fallback_question called but never defined.

These tests exercise the real handlers with fake Telegram objects and a
throwaway database (wired by conftest.py).
"""

import pytest

import services
from models import Word


class FakeUser:
    id = 42


class FakeMessage:
    def __init__(self):
        self.chat_id = 100
        self.sent = []

    async def reply_text(self, text, reply_markup=None, **kw):
        self.sent.append(text)


class FakeQuery:
    def __init__(self, data=""):
        self.data = data
        self.from_user = FakeUser()
        self.message = FakeMessage()
        self.answers = []
        self.edits = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))

    async def edit_message_text(self, text, reply_markup=None):
        self.edits.append((text, reply_markup))


class FakeContext:
    def __init__(self):
        self.user_data = {}


def _word():
    return Word(
        id=9,
        german="Haus",
        persian="خانه",
        article="das",
        word_type="Noun",
    )


@pytest.fixture
def word_lookup(monkeypatch):
    stubs = {"get_by_id": lambda wid: _word() if wid == 9 else None}
    monkeypatch.setattr(services.db.words, "get_by_id", stubs["get_by_id"])
    return stubs


# ─── B7: LTR test-question flow must not NameError ───────────────


async def test_ltr_test_question_renders_without_name_error(word_lookup):
    from handlers.learning.ltr_handlers import _show_test_question

    context = FakeContext()
    query = FakeQuery("ltr_ans:0")

    await _show_test_question(query, context, 9)

    # A question (or final fallback) was rendered; no exception escaped.
    assert query.edits, "expected a rendered question"
    assert context.user_data.get("ltr_current_question") == 9
    assert context.user_data.get("ltr_current_options")


# ─── B8/B11: speak-current fallback + fallback question body ─────


async def test_speak_current_fallback_path_works(word_lookup):
    """current_tts_text missing -> resolve from current_flashcard via run_db."""
    from handlers.tts_handlers import handle_speak_current

    context = FakeContext()
    context.user_data["current_flashcard"] = {"word_id": 9}
    query = FakeQuery("speak_current:x")

    # edge-tts is unavailable in tests -> get_audio_path returns None,
    # so the handler should report unavailability instead of crashing.
    await handle_speak_current(query, context, suffix="x")

    assert any("تلفظ" in t for t in query.message.sent), query.message.sent


async def test_final_fallback_question_is_defined_and_renders(word_lookup):
    from handlers.learning.ltr_handlers import _render_final_fallback_question

    context = FakeContext()
    query = FakeQuery()

    await _render_final_fallback_question(query, context, _word())

    assert query.edits
    assert context.user_data["ltr_current_options"] == ["خانه"]
    assert context.user_data["ltr_current_correct_index"] == 0


# ─── B12: MIN_SUCCESS_TYPES was undefined (NameError on every hit) ──


def test_record_test_result_requires_two_distinct_correct_types():
    """First correct type re-schedules; second distinct type passes the word."""
    from handlers.learning.ltr_session import LTRSessionManager

    context = FakeContext()
    ltr = LTRSessionManager(context)

    ltr.record_test_result(9, True, "meaning")
    # only one distinct type so far -> must be scheduled again, not passed
    assert 9 not in ltr.user_data.get("ltr_words_passed", [])
    tasks = ltr.user_data.get("ltr_delayed_tasks", [])
    assert any(t.get("word_id") == 9 for t in tasks)

    ltr.record_test_result(9, True, "reverse")
    assert 9 in ltr.user_data["ltr_words_passed"]


def test_record_test_result_fails_word_after_max_retries():
    from handlers.learning.ltr_session import MAX_RETRIES, LTRSessionManager

    context = FakeContext()
    ltr = LTRSessionManager(context)

    for _ in range(MAX_RETRIES + 1):
        ltr.record_test_result(9, False, "meaning")

    assert 9 in ltr.user_data["ltr_words_failed"]

