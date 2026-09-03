"""Callback-data codec.

One mechanism for building and parsing inline-keyboard callback data from the
``CallbackPrefix`` enum. Replaces hand-written ``f"{prefix.value}{suffix}"``
f-strings duplicated between keyboard builders and the router.

Parsing uses longest-prefix-first matching so overlapping prefixes
(``lesson_words_`` vs ``lesson_``, ``story_listen_read:`` vs
``story_listen_only:``) can never shadow each other.
"""

import logging
from typing import Any, Optional, Tuple

from models import CallbackPrefix

logger = logging.getLogger(__name__)

# Telegram's hard limit for ``callback_data``. See
# https://core.telegram.org/bots/api#inlinekeyboardbutton
CALLBACK_DATA_MAX_BYTES = 64

# Longest first → no prefix shadowing.
_SORTED_PREFIXES = sorted(CallbackPrefix, key=lambda p: len(p.value), reverse=True)

__all__ = ["cb", "cb_safe", "parse", "parse_int", "CALLBACK_DATA_MAX_BYTES"]


def cb(prefix: CallbackPrefix, suffix: Any = "") -> str:
    """Build callback data from a prefix enum member and a suffix."""
    return f"{prefix.value}{suffix}"


def cb_safe(prefix: CallbackPrefix, suffix: Any = "") -> str:
    """Build callback data, but stay within Telegram's 64-byte limit.

    Always returns a non-empty string: if the built payload would exceed
    ``CALLBACK_DATA_MAX_BYTES`` UTF-8 bytes, this function logs a
    warning and returns the safe ``"noop"`` fallback. Callers that pass
    user-controlled values (e.g. an unbounded ``lesson_id`` or a long
    lesson title) should prefer ``cb_safe`` to avoid Telegram rejecting
    the entire ``InlineKeyboardButton`` at send-time with
    ``BadRequest: Button_data_invalid``.

    Args:
        prefix: A ``CallbackPrefix`` enum member (or any value whose
            ``.value`` is the prefix string).
        suffix: Anything that converts to ``str`` and is appended
            after the prefix. Defaults to "".

    Returns:
        The composed callback data, or ``"noop"`` if it would have
        exceeded the byte budget.
    """
    data = f"{prefix.value}{suffix}"
    try:
        size = len(data.encode("utf-8"))
    except Exception:
        # Worst-case: if the suffix is a weird object that can't be
        # encoded, fall back to noop rather than crashing the keyboard.
        logger.warning(
            "cb_safe: could not encode callback payload; falling back to noop"
        )
        return "noop"
    if size <= CALLBACK_DATA_MAX_BYTES:
        return data
    logger.warning(
        "cb_safe: callback_data too long (%d > %d bytes), falling back to noop: %r",
        size,
        CALLBACK_DATA_MAX_BYTES,
        data,
    )
    return "noop"


def parse(data: str) -> Optional[Tuple[CallbackPrefix, str]]:
    """Split callback data into (prefix member, suffix).

    Returns None when data does not start with any known prefix.
    """
    if not data:
        return None
    for prefix in _SORTED_PREFIXES:
        if data.startswith(prefix.value):
            return prefix, data[len(prefix.value):]
    return None


def parse_int(data: str) -> Optional[int]:
    """Parse callback data whose suffix is an integer. None if not parseable."""
    parsed = parse(data)
    if not parsed:
        return None
    try:
        return int(parsed[1])
    except (TypeError, ValueError):
        return None

