"""Callback-data codec.

One mechanism for building and parsing inline-keyboard callback data from the
``CallbackPrefix`` enum. Replaces hand-written ``f"{prefix.value}{suffix}"``
f-strings duplicated between keyboard builders and the router.

Parsing uses longest-prefix-first matching so overlapping prefixes
(``lesson_words_`` vs ``lesson_``, ``story_listen_read:`` vs
``story_listen_only:``) can never shadow each other.
"""

from typing import Any, Optional, Tuple

from models import CallbackPrefix

# Longest first → no prefix shadowing.
_SORTED_PREFIXES = sorted(CallbackPrefix, key=lambda p: len(p.value), reverse=True)

__all__ = ["cb", "parse", "parse_int"]


def cb(prefix: CallbackPrefix, suffix: Any = "") -> str:
    """Build callback data from a prefix enum member and a suffix."""
    return f"{prefix.value}{suffix}"


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

