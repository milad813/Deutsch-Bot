# core/locks.py

from contextlib import suppress
from functools import wraps


def callback_guard(lock_key: str):
    """
    Prevents double-tap on callback handlers.

    Usage:
        @callback_guard("quiz_answer_lock")
        async def handle_quiz_answer(query, context):
            ...
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(query, context, *args, **kwargs):
            if context.user_data.get(lock_key):
                with suppress(Exception):
                    await query.answer()
                return

            context.user_data[lock_key] = True
            try:
                return await func(query, context, *args, **kwargs)
            finally:
                context.user_data.pop(lock_key, None)

        return wrapper

    return decorator