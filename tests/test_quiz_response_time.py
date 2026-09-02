"""Regression test: ``handle_quiz_answer`` must pass ``response_time_sec``
to ``record_quiz_answer`` so the SRS engine can take answer speed into
account.

Before the fix, the elapsed time from ``sent_at`` to the answer was
computed but discarded — ``run_db(record_quiz_answer, ...)`` never
forwarded it. As a result, slow-but-correct answers were graded as
"Good" instead of "Hard", biasing the SRS schedule toward over-easy
intervals.
"""

import time
from types import SimpleNamespace

import pytest

import handlers.quiz_handlers as qh
from handlers.quiz_handlers import handle_quiz_answer


# ─── fakes ──────────────────────────────────────────────────────────────────


class _FakeUser:
    def __init__(self, user_id: int = 42):
        self.id = user_id


class _FakeQuery:
    def __init__(self, data: str, user_id: int = 42):
        self.data = data
        self.from_user = _FakeUser(user_id)
        self.edits: list = []
        self.answers: list = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))

    async def edit_message_text(self, text, reply_markup=None):
        self.edits.append((text, reply_markup))


class _FakeContext:
    def __init__(self):
        self.user_data: dict = {}


def _make_quiz(correct_index: int = 1) -> dict:
    return {
        "type": "meaning",
        "question": "معنی کلمه چیست؟",
        "options": ["opt0", "opt1", "opt2", "opt3"],
        "correct_index": correct_index,
        "correct_answer": f"opt{correct_index}",
        "word": "Haus",
        "word_id": 7,  # give the SRS a real word to grade
        "persian": "خانه",
    }


# ─── test ──────────────────────────────────────────────────────────────────


async def test_handle_quiz_answer_passes_response_time_sec(monkeypatch):
    """The handler must forward ``response_time_sec`` to ``record_quiz_answer``.

    We monkeypatch the *module-level* ``run_db`` used by
    ``handlers.quiz_handlers`` to capture every invocation without
    touching the real database, then assert the kwargs contain
    ``response_time_sec`` equal to ``time.time() - sent_at``.
    """
    captured: list[tuple] = []

    async def _fake_run_db(func, *args, **kwargs):
        captured.append((func, kwargs))
        return None

    monkeypatch.setattr(qh, "run_db", _fake_run_db)

    # ``record_quiz_answer`` is the only function whose kwargs matter
    # for this regression. The handler also uses ``run_db`` for the
    # wrap-up DB writes (recording skill etc.) — we let those through
    # by stubbing the engine to be a no-op.
    monkeypatch.setattr(qh, "record_quiz_answer", lambda **_: None)

    context = _FakeContext()
    sent_at = time.time() - 2.5  # pretend 2.5s elapsed before answer
    context.user_data["current_quiz"] = _make_quiz(correct_index=1)
    context.user_data["quiz_question_sent_at"] = sent_at

    query = _FakeQuery("quiz_ans:1", user_id=99)

    before = time.time()
    await handle_quiz_answer(query, context)
    after = time.time()

    # ``record_quiz_answer`` is invoked before the summary is rendered,
    # so it must be the first ``run_db`` call in the captured list.
    assert captured, "run_db was not called at all"
    func, kwargs = captured[0]

    assert "response_time_sec" in kwargs, (
        "response_time_sec must be passed to record_quiz_answer so the "
        "SRS can grade slow-but-correct answers as Hard"
    )
    rt = kwargs["response_time_sec"]
    assert rt is not None, "response_time_sec must not be None when sent_at is set"
    # The handler computes ``time.time() - sent_at`` inside the same
    # async frame we just ran, so the value should be within [2.5,
    # (2.5 + wall-clock-during-call)].
    assert 2.5 <= rt <= (after - before) + 2.5 + 0.1, (
        f"response_time_sec={rt!r} does not match the elapsed time "
        f"between sent_at and the call"
    )


async def test_handle_quiz_answer_response_time_sec_none_when_no_sent_at(
    monkeypatch,
):
    """If the quiz was launched without a recorded ``sent_at``, the
    handler must still pass ``response_time_sec`` (as ``None``) so the
    learning engine explicitly sees "no timing data" instead of having
    the value fall off as a missing keyword.
    """
    captured: list[tuple] = []

    async def _fake_run_db(func, *args, **kwargs):
        captured.append((func, kwargs))
        return None

    monkeypatch.setattr(qh, "run_db", _fake_run_db)
    monkeypatch.setattr(qh, "record_quiz_answer", lambda **_: None)

    context = _FakeContext()
    context.user_data["current_quiz"] = _make_quiz(correct_index=0)
    # No "quiz_question_sent_at" key.
    query = _FakeQuery("quiz_ans:0", user_id=99)

    await handle_quiz_answer(query, context)

    assert captured, "run_db was not called at all"
    _, kwargs = captured[0]
    assert "response_time_sec" in kwargs
    assert kwargs["response_time_sec"] is None