"""Pure helpers for inspecting a Telegram ``Update`` before dispatching it.

These helpers perform **no network calls** — they only look at the Python
objects passed in. They are intended to be used inside handler bodies and
tests, so they must remain free of side effects and free of any
``telegram.*`` imports.

The intended usage is:

* :func:`should_block_non_private` to enforce the "private-chat safe"
  Phase-0 goal without needing to know how a chat is exposed on the
  particular :class:`telegram.Update` shape (message vs callback vs inline
  query, etc.).
* :func:`get_user_id` as the canonical way to read the originating user's
  numeric id (works for commands, messages, and callback queries).
"""

from typing import Any, Optional


def _attr(obj: Any, *names: str) -> Any:
    """Return the first non-``None`` attribute found along ``names``.

    Stops as soon as a non-``None`` value is found; returns ``None`` if
    every lookup yields ``None`` or the object itself is falsy.
    """
    if obj is None:
        return None
    for name in names:
        value = getattr(obj, name, None)
        if value is not None:
            return value
    return None


def get_chat_from_update(update: Any) -> Optional[Any]:
    """Return the originating chat object, or ``None`` if it cannot be found.

    Looks at, in order:

    1. ``update.effective_chat``
    2. ``update.message.chat``
    3. ``update.callback_query.message.chat``

    This covers the three shapes a Telegram update normally has when
    dispatched by ``python-telegram-bot``: a bare message, a callback
    query, or an object that already exposes ``effective_chat`` (commands,
    edited messages, etc.).
    """
    if update is None:
        return None

    chat = _attr(update, "effective_chat")
    if chat is not None:
        return chat

    message = _attr(update, "message")
    chat = _attr(message, "chat")
    if chat is not None:
        return chat

    callback_query = _attr(update, "callback_query")
    callback_message = _attr(callback_query, "message")
    chat = _attr(callback_message, "chat")
    return chat


def is_private_chat(chat: Any) -> bool:
    """Return ``True`` only if ``chat`` exists and is a private chat.

    Returns ``False`` for ``None``, groups, supergroups, channels, or any
    object whose ``type`` attribute is not the literal string ``"private"``.
    """
    if chat is None:
        return False
    return getattr(chat, "type", None) == "private"


def should_block_non_private(update: Any) -> bool:
    """Decide whether ``update`` originates outside a private chat.

    * Returns ``False`` when the chat cannot be determined at all (we
      err on the side of letting the existing authorization layer reject
      the request, rather than blocking a legitimate message whose chat
      we simply couldn't find).
    * Returns ``True`` when the chat is known and is **not** private.
    """
    chat = get_chat_from_update(update)
    if chat is None:
        return False
    return not is_private_chat(chat)


def get_user_id(update: Any) -> Optional[int]:
    """Return the numeric user id of the sender, or ``None`` if unknown.

    Tries, in order:

    1. ``update.effective_user.id``
    2. ``update.from_user.id``
    3. ``update.callback_query.from_user.id``

    Anything that isn't an ``int`` is treated as "unknown" and returns
    ``None`` — this prevents callers from accidentally comparing a
    stringified id to the configured admin id.
    """
    if update is None:
        return None

    user = _attr(update, "effective_user", "from_user")
    user_id = _attr(user, "id")
    if isinstance(user_id, int):
        return user_id

    callback_query = _attr(update, "callback_query")
    callback_user = _attr(callback_query, "from_user")
    callback_user_id = _attr(callback_user, "id")
    if isinstance(callback_user_id, int):
        return callback_user_id

    return None


__all__ = [
    "get_chat_from_update",
    "is_private_chat",
    "should_block_non_private",
    "get_user_id",
]