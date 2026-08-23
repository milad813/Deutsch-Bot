"""Functional tests for the quiz answer flow (regression for bug B1).

Runs handle_quiz_answer against a throwaway SQLite database with fake
Telegram objects, verifying the full path: parse answer -> record via
learning_engine -> update session -> render feedback/summary.
"""

from handlers.quiz_handlers import handle_quiz_answer
from models import QuizSession


class FakeUser:
    id = 42


class FakeQuery:
    def __init__(self, data: str):
        self.data = data
        self.from_user = FakeUser()
        self.answers = []
        self.edits = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))

    async def edit_message_text(self, text, reply_markup=None):
        self.edits.append((text, reply_markup))


class FakeContext:
    def __init__(self):
        self.user_data = {}


def _make_quiz(correct_index: int) -> dict:
    return {
        "type": "meaning",
        "question": "معنی کلمه چیست؟",
        "options": ["opt0", "opt1", "opt2", "opt3"],
        "correct_index": correct_index,
        "correct_answer": f"opt{correct_index}",
        "word": "Haus",
        "word_id": None,  # None keeps SRS/skill writes out of the picture
        "persian": "خانه",
    }


async def test_correct_answer_completes_without_error():
    context = FakeContext()
    context.user_data["current_quiz"] = _make_quiz(correct_index=1)
    query = FakeQuery("quiz_ans:1")

    await handle_quiz_answer(query, context)

    # Lock released, quiz state consumed, feedback rendered
    assert "quiz_answer_lock" not in context.user_data
    assert "current_quiz" not in context.user_data
    assert query.edits, "expected summary/feedback to be rendered"


async def test_wrong_answer_updates_session_and_shows_summary():
    context = FakeContext()
    session = QuizSession(quiz_type="meaning", total_questions=1)
    context.user_data["quiz_session_obj"] = session
    context.user_data["current_quiz"] = _make_quiz(correct_index=0)
    query = FakeQuery("quiz_ans:2")

    await handle_quiz_answer(query, context)

    assert session.current_index == 1
    assert session.correct_count == 0
    assert session.wrong_count == 1
    assert "current_quiz" not in context.user_data
    assert query.edits, "expected summary to be rendered"
    # No word_id -> nothing tracked for retry
    assert not context.user_data.get("quiz_wrong_word_ids")


async def test_wrong_answer_tracks_word_for_retry():
    context = FakeContext()
    session = QuizSession(quiz_type="meaning", total_questions=2)
    context.user_data["quiz_session_obj"] = session
    quiz = _make_quiz(correct_index=0)
    quiz["word_id"] = 7
    context.user_data["current_quiz"] = quiz
    query = FakeQuery("quiz_ans:3")

    await handle_quiz_answer(query, context)

    assert context.user_data.get("quiz_wrong_word_ids") == [7]
    assert session.question_ids == [7]


async def test_inactive_quiz_shows_alert_and_returns():
    context = FakeContext()
    query = FakeQuery("quiz_ans:0")

    await handle_quiz_answer(query, context)

    assert query.answers and query.answers[0][1] is True  # show_alert=True
    assert not query.edits


async def test_invalid_option_index_is_rejected():
    context = FakeContext()
    context.user_data["current_quiz"] = _make_quiz(correct_index=0)
    query = FakeQuery("quiz_ans:99")

    await handle_quiz_answer(query, context)

    assert query.answers and query.answers[0][1] is True
    # State untouched
    assert "current_quiz" in context.user_data