"""Tests for the ``/cancel`` command and the improved global error handler.

The ``/cancel`` command is a Phase-0 safety net: it lets the user bail out
of any in-flight session (flashcard, quiz, LTR, story, …) without
crashing the bot. These tests cover the two paths through ``cancel`` plus
the new "answer the callback query on error" behavior in
``bot.on_error``.
"""

from types import SimpleNamespace

import pytest
from telegram import Update
from telegram.error import BadRequest

from bot import on_error
from handlers.menus import cancel
from services import SESSION_KEYS, db


# ─── fake Telegram objects ──────────────────────────────────────────────────


class _FakeUser:
    def __init__(self, user_id: int = 42):
        self.id = user_id
        self.first_name = "Tester"
        self.last_name = None
        self.username = None


class _FakeMessage:
    def __init__(self, text: str = "/cancel"):
        self.text = text
        self.sent: list[str] = []

    async def reply_text(self, text, reply_markup=None, **kw):
        self.sent.append(text)
        return None


class _FakeContext:
    def __init__(self):
        self.user_data: dict = {}


def _fake_update(user_id: int = 42) -> _FakeMessage:
    """Build a minimal Update-like object that ``cancel`` understands.

    ``cancel`` reads ``update.effective_user`` and ``update.message``.
    """
    update = SimpleNamespace()
    update.effective_user = _FakeUser(user_id)
    update.message = _FakeMessage()
    return update


# ─── fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def public_mode(monkeypatch):
    """Let every user through ``config.is_authorized_user`` so we can
    focus on the cancel-specific behavior (which is orthogonal to auth)."""
    import config

    monkeypatch.setattr(config, "ALLOW_PUBLIC_ACCESS", True)


@pytest.fixture
def stub_show_menu_db(monkeypatch):
    """Stub the DB-touching functions inside ``show_menu``.

    The real ``show_menu`` would call ``register_user``, ``get_settings``
    and ``_menu_stats``. We don't need any of that for cancel tests —
    we just want it to render the main menu. Returning empty / safe
    values keeps the path predictable.

    Note: ``run_db`` uses ``asyncio.to_thread`` to run the repository
    methods, so these stubs must be **synchronous** — passing async
    functions here would cause ``to_thread`` to return a never-awaited
    coroutine.
    """
    def _register_user(**_):
        return None

    def _get_settings(_uid):
        # Pre-existing settings row -> ``show_menu`` will render the
        # regular menu instead of branching into ``show_level_select``.
        return {"preferred_level": "A1", "daily_goal": 10}

    async def _menu_stats(_uid):
        return 0, 0, 0  # due, streak, hard

    monkeypatch.setattr(db.users, "register_user", _register_user)
    monkeypatch.setattr(db.users, "get_settings", _get_settings)
    # ``_menu_stats`` is module-level inside handlers.menus.
    import handlers.menus as _menus

    monkeypatch.setattr(_menus, "_menu_stats", _menu_stats)


# ─── /cancel: session-key behavior ─────────────────────────────────────────


async def test_cancel_resets_session_keys(public_mode):
    """``/cancel`` must clear every key in ``SESSION_KEYS`` from user_data."""
    context = _FakeContext()
    # Pre-populate with one key from each feature.
    for key in SESSION_KEYS:
        context.user_data[key] = f"leaked:{key}"
    # A key that is NOT a session key must survive.
    context.user_data["persistent_user_pref"] = "keep-me"

    await cancel(_fake_update(), context)

    for key in SESSION_KEYS:
        assert key not in context.user_data, (
            f"cancel should have cleared {key!r}"
        )
    assert context.user_data["persistent_user_pref"] == "keep-me"


async def test_cancel_does_not_crash_when_user_data_is_empty(public_mode):
    """An empty user_data must not break the handler."""
    context = _FakeContext()
    assert context.user_data == {}

    # We pass an update with no effective_user so the handler returns
    # on the very first check. This exercises the "no user" branch and
    # also implicitly covers "empty user_data".
    update = SimpleNamespace(effective_user=None, message=None)

    await cancel(update, context)

    assert context.user_data == {}


async def test_cancel_returns_silently_for_unauthorized_user(monkeypatch):
    """Unauthorized users must not see the cancel confirmation."""
    import config

    monkeypatch.setattr(config, "ALLOW_PUBLIC_ACCESS", False)
    monkeypatch.setattr(config, "ADMIN_USER_ID", 999_999)

    context = _FakeContext()
    for key in SESSION_KEYS:
        context.user_data[key] = "should-not-be-touched"
    update = _fake_update(user_id=1)

    await cancel(update, context)

    # The handler must NOT have sent any message.
    assert update.message.sent == []
    # And it must NOT have touched user_data (it returned before reset).
    assert all(
        context.user_data[key] == "should-not-be-touched" for key in SESSION_KEYS
    )


# ─── /cancel: end-to-end with a fake update ────────────────────────────────


async def test_cancel_works_with_fake_update(
    public_mode, stub_show_menu_db
):
    """``/cancel`` must complete end-to-end on a synthetic Update.

    It should:
      * clear session keys,
      * send the Persian "operation cancelled" confirmation,
      * and re-show the main menu.
    """
    context = _FakeContext()
    context.user_data["current_quiz"] = {"q": 1}  # would be in SESSION_KEYS
    context.user_data["persistent"] = "kept"
    update = _fake_update(user_id=1234)

    await cancel(update, context)

    # Session key was cleared, non-session key survived.
    assert "current_quiz" not in context.user_data
    assert context.user_data["persistent"] == "kept"

    # Confirmation message was sent.
    sent = update.message.sent
    assert any("لغو شد" in t for t in sent), sent

    # The main menu was re-shown — ``show_menu`` renders via ``render``,
    # which falls back to ``message.reply_text`` on plain Updates. The
    # last message in the log must therefore contain a "main menu" hint.
    assert any("منو" in t for t in sent), sent


async def test_cancel_message_persian_text(public_mode, stub_show_menu_db):
    """The confirmation message must use the exact Persian phrasing."""
    context = _FakeContext()
    update = _fake_update()

    await cancel(update, context)

    assert "❌ عملیات فعلی لغو شد." in update.message.sent


# ─── on_error: callback-query error answering ─────────────────────────────


async def test_on_error_answers_callback_query_on_bad_request():
    """``on_error`` must answer the callback with the Persian notice,
    even for ``BadRequest`` errors (which previously were silently dropped)."""

    async def _answer(text=None, **_):
        _answer.calls.append(text)

    _answer.calls = []
    callback = SimpleNamespace(answer=_answer, message=None)
    # ``on_error`` uses ``isinstance(update, Update)``, so we have to
    # use a real ``Update`` instance.
    update = Update(update_id=1, callback_query=callback)
    context = SimpleNamespace(error=BadRequest("test failure"))

    await on_error(update, context)

    assert _answer.calls, "expected callback_query.answer to be called"
    assert "⚠️ خطایی رخ داد." in _answer.calls[-1]


async def test_on_error_swallows_answer_exceptions():
    """If ``answer()`` itself raises, ``on_error`` must not crash."""

    async def _boom(**_):
        raise RuntimeError("network down")

    # The callback must expose ``message=None`` so that
    # ``Update.effective_message`` does not blow up when ``answer()``
    # raises.
    callback = SimpleNamespace(answer=_boom, message=None)
    update = Update(update_id=1, callback_query=callback)
    context = SimpleNamespace(error=RuntimeError("downstream"))

    # Must not raise.
    await on_error(update, context)


async def test_on_error_no_callback_query_does_not_crash():
    """``on_error`` with a non-callback update must still behave sanely."""
    # No callback_query at all -> the new answer-callback step is a
    # no-op and the existing ``effective_message`` branch is also a
    # no-op. Must not raise.
    update = Update(update_id=1)
    context = SimpleNamespace(error=RuntimeError("boom"))

    await on_error(update, context)
