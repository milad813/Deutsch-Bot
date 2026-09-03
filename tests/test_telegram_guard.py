"""Tests for ``core/telegram_guard``.

The helpers are pure and take simple Python objects, so we use
``SimpleNamespace`` to fake the parts of a Telegram update we need.
No network calls, no telegram-python-bot imports.
"""

from types import SimpleNamespace

from core.telegram_guard import (
    get_chat_from_update,
    get_user_id,
    is_private_chat,
    should_block_non_private,
)


# ─── is_private_chat ────────────────────────────────────────────────────────


def test_private_chat_returns_true_for_is_private_chat():
    chat = SimpleNamespace(type="private")
    assert is_private_chat(chat) is True


def test_group_chat_returns_false_for_is_private_chat():
    group = SimpleNamespace(type="group")
    supergroup = SimpleNamespace(type="supergroup")
    channel = SimpleNamespace(type="channel")
    assert is_private_chat(group) is False
    assert is_private_chat(supergroup) is False
    assert is_private_chat(channel) is False


def test_is_private_chat_handles_missing_chat():
    assert is_private_chat(None) is False


def test_is_private_chat_handles_chat_without_type():
    chat = SimpleNamespace()  # no `type` attribute
    assert is_private_chat(chat) is False


# ─── should_block_non_private ───────────────────────────────────────────────


def test_unknown_chat_returns_false_for_should_block_non_private():
    """If we can't find a chat, don't block — let the auth layer decide."""
    update = SimpleNamespace()  # no effective_chat / message / callback_query
    assert should_block_non_private(update) is False


def test_known_group_chat_returns_true_for_should_block_non_private():
    chat = SimpleNamespace(type="group")
    update = SimpleNamespace(effective_chat=chat)
    assert should_block_non_private(update) is True


def test_known_private_chat_returns_false_for_should_block_non_private():
    chat = SimpleNamespace(type="private")
    update = SimpleNamespace(effective_chat=chat)
    assert should_block_non_private(update) is False


def test_callback_query_with_group_message_returns_true():
    """Callback queries hide the chat inside ``callback_query.message.chat``."""
    chat = SimpleNamespace(type="supergroup")
    message = SimpleNamespace(chat=chat)
    callback_query = SimpleNamespace(message=message)
    update = SimpleNamespace(callback_query=callback_query)
    assert should_block_non_private(update) is True


def test_callback_query_with_private_message_returns_false():
    chat = SimpleNamespace(type="private")
    message = SimpleNamespace(chat=chat)
    callback_query = SimpleNamespace(message=message)
    update = SimpleNamespace(callback_query=callback_query)
    assert should_block_non_private(update) is False


def test_message_with_group_chat_returns_true():
    """Plain messages expose the chat directly via ``message.chat``."""
    chat = SimpleNamespace(type="group")
    message = SimpleNamespace(chat=chat)
    update = SimpleNamespace(message=message)
    assert should_block_non_private(update) is True


def test_effective_chat_takes_precedence():
    """If both ``effective_chat`` and ``message.chat`` exist, prefer the former."""
    effective_chat = SimpleNamespace(type="private")
    message_chat = SimpleNamespace(type="group")
    message = SimpleNamespace(chat=message_chat)
    update = SimpleNamespace(effective_chat=effective_chat, message=message)
    assert should_block_non_private(update) is False


# ─── get_chat_from_update ──────────────────────────────────────────────────


def test_get_chat_from_update_prefers_effective_chat():
    effective_chat = SimpleNamespace(type="private", id=1)
    message_chat = SimpleNamespace(type="group", id=2)
    update = SimpleNamespace(
        effective_chat=effective_chat,
        message=SimpleNamespace(chat=message_chat),
    )
    assert get_chat_from_update(update) is effective_chat


def test_get_chat_from_update_falls_back_to_message_chat():
    message_chat = SimpleNamespace(type="private", id=42)
    update = SimpleNamespace(message=SimpleNamespace(chat=message_chat))
    assert get_chat_from_update(update) is message_chat


def test_get_chat_from_update_falls_back_to_callback_message_chat():
    cb_chat = SimpleNamespace(type="group", id=99)
    update = SimpleNamespace(
        callback_query=SimpleNamespace(message=SimpleNamespace(chat=cb_chat))
    )
    assert get_chat_from_update(update) is cb_chat


def test_get_chat_from_update_returns_none_when_missing():
    assert get_chat_from_update(SimpleNamespace()) is None
    assert get_chat_from_update(None) is None


# ─── get_user_id ────────────────────────────────────────────────────────────


def test_get_user_id_from_effective_user():
    update = SimpleNamespace(effective_user=SimpleNamespace(id=123))
    assert get_user_id(update) == 123


def test_get_user_id_from_from_user():
    update = SimpleNamespace(from_user=SimpleNamespace(id=456))
    assert get_user_id(update) == 456


def test_get_user_id_from_callback_query():
    update = SimpleNamespace(
        callback_query=SimpleNamespace(from_user=SimpleNamespace(id=789))
    )
    assert get_user_id(update) == 789


def test_get_user_id_returns_none_when_missing():
    assert get_user_id(SimpleNamespace()) is None
    assert get_user_id(None) is None


def test_get_user_id_ignores_non_int_ids():
    """A stray string id must not be returned as if it were an int."""
    update = SimpleNamespace(effective_user=SimpleNamespace(id="not-an-int"))
    assert get_user_id(update) is None