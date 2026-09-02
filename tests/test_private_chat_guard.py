"""Phase-0 private-chat guard integration tests.

The bot must silently ignore (or politely reject) updates that arrive
from non-private chats. The tests in this module build fake Telegram
``Update``/``Message``/``CallbackQuery`` objects and verify the three
integration points — ``handle_text_input``, ``start``/``show_menu``,
and ``inline_handler`` — block (or pass through) the expected way.

We never hit the Telegram network. We also never touch the real DB:
``conftest.py`` has already redirected ``DB_PATH`` to a throwaway
SQLite file and we use ``ALLOW_PUBLIC_ACCESS`` to keep the unrelated
authorization check from getting in our way.
"""

import pytest

import config
from handlers.callback_router import inline_handler
from handlers.menus import show_menu, start
from handlers.text_handlers import handle_text_input


# ─── fake Telegram objects ──────────────────────────────────────────────────


class _FakeUser:
    def __init__(self, user_id: int = 42):
        self.id = user_id
        self.first_name = "Tester"
        self.last_name = None
        self.username = None


class _FakeMessage:
    def __init__(self, chat, text: str = "ignored"):
        self.chat = chat
        self.text = text
        self.sent: list[str] = []

    async def reply_text(self, text, reply_markup=None, **kw):
        self.sent.append(text)
        return None


class _FakeCallbackQuery:
    def __init__(self, chat, data: str = "noop", user_id: int = 42):
        self.data = data
        self.from_user = _FakeUser(user_id)
        self.message = _FakeMessage(chat)
        self.answers: list[tuple[str | None, bool]] = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))

    async def edit_message_text(self, text, reply_markup=None):
        self.message.sent.append(text)


class _FakeUpdate:
    """Minimal Update-like wrapper.

    Exposes ``effective_user`` and either ``message`` or ``callback_query``,
    depending on the call path being exercised.
    """

    def __init__(
        self,
        *,
        chat,
        user_id: int = 42,
        text: str | None = None,
        callback_data: str | None = None,
    ):
        self.effective_chat = chat
        self.effective_user = _FakeUser(user_id)
        if callback_data is not None:
            self.callback_query = _FakeCallbackQuery(
                chat, data=callback_data, user_id=user_id
            )
            self.message = None
        else:
            self.message = _FakeMessage(chat, text=text or "ignored")
            self.callback_query = None
        # Some handlers also look at .from_user (mirrors a real Update).
        self.from_user = self.effective_user


class _FakeContext:
    def __init__(self):
        self.user_data: dict = {}


# ─── fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def public_mode(monkeypatch):
    """Allow any user through ``config.is_authorized_user``.

    The private-chat guard is orthogonal to authorization, so we open
    up the latter to keep these tests focused on the former.
    """
    monkeypatch.setattr(config, "ALLOW_PUBLIC_ACCESS", True)


def _chat(chat_type: str, chat_id: int = 1000):
    from types import SimpleNamespace

    return SimpleNamespace(id=chat_id, type=chat_type)


# ─── text handler ──────────────────────────────────────────────────────────


async def test_handle_text_input_ignores_group_updates(public_mode):
    update = _FakeUpdate(chat=_chat("group"), text="📊 داشبورد")
    context = _FakeContext()

    await handle_text_input(update, context)

    # The handler must NOT have replied to a group chat.
    assert update.message.sent == []


async def test_handle_text_input_ignores_supergroup_updates(public_mode):
    update = _FakeUpdate(chat=_chat("supergroup"), text="ignored")
    context = _FakeContext()

    await handle_text_input(update, context)

    assert update.message.sent == []


async def test_handle_text_input_allows_private_updates(public_mode):
    """A private chat must not be blocked by the guard.

    We don't assert that *any* specific reply is sent — the menu
    branching is exercised elsewhere. We just verify the guard did
    not short-circuit the handler.
    """
    update = _FakeUpdate(chat=_chat("private"), text="not-a-known-menu-action")
    context = _FakeContext()

    await handle_text_input(update, context)

    # The handler must have proceeded (it replies with the "use the
    # menu" prompt for any unknown text in a private chat).
    assert any("منو" in t for t in update.message.sent), update.message.sent


# ─── start / show_menu ─────────────────────────────────────────────────────


async def test_start_blocks_group_updates_with_persian_message(public_mode):
    update = _FakeUpdate(chat=_chat("group"), user_id=7)
    context = _FakeContext()

    await start(update, context)

    # Exactly one reply, in Persian, telling the user to use private chat.
    assert len(update.message.sent) == 1
    assert "چت خصوصی" in update.message.sent[0]


async def test_start_allows_private_updates(public_mode):
    """Private users should pass the guard and reach the welcome flow.

    We don't assert the full welcome body (that's a separate test in
    test_smoke). We only assert the guard did NOT short-circuit.
    """
    update = _FakeUpdate(chat=_chat("private"), user_id=7)
    context = _FakeContext()

    await start(update, context)

    # The "go to private chat" message must not have been sent.
    assert not any("چت خصوصی" in t for t in update.message.sent)


async def test_show_menu_blocks_group_updates(public_mode):
    update = _FakeUpdate(chat=_chat("supergroup"), user_id=7)
    context = _FakeContext()

    await show_menu(update, context)

    assert len(update.message.sent) == 1
    assert "چت خصوصی" in update.message.sent[0]


async def test_show_menu_allows_private_updates(public_mode):
    update = _FakeUpdate(chat=_chat("private"), user_id=7)
    context = _FakeContext()

    await show_menu(update, context)

    assert not any("چت خصوصی" in t for t in update.message.sent)


# ─── inline_handler (callback queries) ─────────────────────────────────────


async def test_inline_handler_blocks_group_callback_queries(public_mode):
    update = _FakeUpdate(
        chat=_chat("supergroup"),
        callback_data="noop",  # data that would otherwise do nothing
    )
    context = _FakeContext()

    await inline_handler(update, context)

    # The callback must have been answered with the Persian notice.
    answered_texts = [t for t, _ in update.callback_query.answers if t]
    assert answered_texts, "expected a non-empty answer to the callback"
    assert "چت خصوصی" in answered_texts[-1]


async def test_inline_handler_blocks_group_callback_with_alert(public_mode):
    """The answer call should set ``show_alert=True`` so the user sees it."""
    update = _FakeUpdate(chat=_chat("group"), callback_data="noop")
    context = _FakeContext()

    await inline_handler(update, context)

    # The last (and only) answer is the Persian guard message.
    last = update.callback_query.answers[-1]
    text, show_alert = last
    assert text is not None
    assert "چت خصوصی" in text
    assert show_alert is True


async def test_inline_handler_allows_private_callback_queries(public_mode):
    """A private callback must not be blocked by the guard.

    ``noop`` is the universal "do nothing" callback used by the router.
    It should be answered with no text and an empty alert flag.
    """
    update = _FakeUpdate(chat=_chat("private"), callback_data="noop")
    context = _FakeContext()

    await inline_handler(update, context)

    # The guard message must NOT be among the answers.
    guard_texts = [t for t, _ in update.callback_query.answers if t and "چت خصوصی" in t]
    assert guard_texts == []
    # And the callback was answered (by the router, not us) at least once.
    assert update.callback_query.answers, "expected at least one answer() call"