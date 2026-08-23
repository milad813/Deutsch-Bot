"""Functional tests for «تمرین هوشمند» (adaptive daily plan).

Covers:
- priority matrix: hard > due > mistakes > new
- goal-aware new-word stage (remaining = goal - done)
- celebration path when everything is finished
- route registration in EXACT_ROUTES
"""

import pytest

import services
from handlers.callback_router import EXACT_ROUTES


class FakeUser:
    id = 42


class FakeMessage:
    def __init__(self):
        self.chat_id = 100
        self.sent = []

    async def reply_text(self, text, reply_markup=None, **kw):
        self.sent.append(text)


class FakeQuery:
    def __init__(self, data="smart_plan"):
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


def _patch_state(monkeypatch, *, hard=0, due=0, mistakes=0, goal=10, done=0, streak=5):
    """Deterministic daily-state for the plan builder."""
    monkeypatch.setattr(services.db.words, "count_hard_due", lambda uid: hard)
    monkeypatch.setattr(services.db.words, "get_due_count", lambda uid: due)
    monkeypatch.setattr(
        services.db.learning, "get_mistake_word_count", lambda uid: mistakes
    )
    monkeypatch.setattr(services.db.learning, "get_daily_goal", lambda uid: goal)
    monkeypatch.setattr(
        services.db.learning, "get_today_new_words_count", lambda uid: done
    )
    monkeypatch.setattr(
        services.db.users, "get_progress", lambda uid: {"streak": streak}
    )


def _last_screen(query):
    assert query.edits, "expected a rendered screen"
    return query.edits[-1]


def _callbacks(markup):
    return [btn.callback_data for row in markup.inline_keyboard for btn in row]


async def test_all_stages_prioritized_hard_first(monkeypatch):
    from handlers.smart_plan import show_smart_plan

    _patch_state(monkeypatch, hard=3, due=5, mistakes=7, goal=10, done=2, streak=6)
    query = FakeQuery()
    await show_smart_plan(query, FakeContext())

    text, markup = _last_screen(query)
    callbacks = _callbacks(markup)

    # Primary CTA must be the top-priority stage (hard words).
    assert callbacks[0] == "flashcard_hard"

    # All four stages appear in learning-science order.
    assert text.index("⚡ مرور 3") < text.index("📅 مرور 5")
    assert text.index("📅 مرور 5") < text.index("📒 تمرین 7")
    # remaining new words = goal - done = 8
    assert text.index("📒 تمرین 7") < text.index("🌱 یادگیری 8")

    # Every stage is launchable + chaining helpers exist.
    assert "flashcard_due" in callbacks
    assert "quiz_source:mistakes" in callbacks
    assert "daily_learning" in callbacks
    assert "smart_plan" in callbacks  # refresh button
    assert "back_to_main_menu" in callbacks

    # Streak and goal progress are visible.
    assert "استریک: <b>6</b>" in text
    assert "2/10" in text


async def test_mistakes_primary_when_no_reviews(monkeypatch):
    from handlers.smart_plan import show_smart_plan

    _patch_state(monkeypatch, mistakes=4, goal=10, done=0)
    query = FakeQuery()
    await show_smart_plan(query, FakeContext())

    _, markup = _last_screen(query)
    assert _callbacks(markup)[0] == "quiz_source:mistakes"


async def test_due_primary_over_mistakes(monkeypatch):
    from handlers.smart_plan import show_smart_plan

    _patch_state(monkeypatch, due=2, mistakes=9, goal=10, done=0)
    query = FakeQuery()
    await show_smart_plan(query, FakeContext())

    _, markup = _last_screen(query)
    callbacks = _callbacks(markup)
    assert callbacks[0] == "flashcard_due"
    assert "quiz_source:mistakes" in callbacks


async def test_goal_complete_celebration(monkeypatch):
    from handlers.smart_plan import show_smart_plan

    _patch_state(monkeypatch, hard=0, due=0, mistakes=0, goal=10, done=10)
    query = FakeQuery()
    await show_smart_plan(query, FakeContext())

    text, markup = _last_screen(query)
    callbacks = _callbacks(markup)

    assert "برنامه‌ی امروزت کامل شد" in text
    assert "mixed_exam:10" in callbacks
    assert "back_to_main_menu" in callbacks
    # No new-learning push after the goal is met.
    assert "daily_learning" not in callbacks


def test_smart_plan_route_registered():
    handler = EXACT_ROUTES.get("smart_plan")
    assert callable(handler)